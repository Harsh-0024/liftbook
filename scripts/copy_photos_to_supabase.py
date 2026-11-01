#!/usr/bin/env python3
"""Copy profile photos from the old app's Cloudflare R2 bucket into Liftbook's Supabase project.

    .venv/bin/python scripts/copy_photos_to_supabase.py --dry-run    # first: shows what it would do
    .venv/bin/python scripts/copy_photos_to_supabase.py

The settings come from ~/.liftbook-import.env (KEY=value lines; the shell's own variables win).

Run it after scripts/import_to_supabase.py (it finds each person by the id the import gave them).

What it does, for each old account with a photo (users.profile_image, e.g.
"avatars/user_5_ab12cd34.png"):
  * reads the photo from R2: with R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY if they are set, else
    from the bucket's public address (the old app shows photos from there too);
  * puts it in the private "avatars" bucket as "<user id>/legacy-user_5_ab12cd34.png";
  * sets profiles.avatar_path to that, so the app shows it.

Safe to run again, as often as needed until the switch:
  * a photo already copied is left alone; a newer one in the old app replaces the old copy;
  * a photo someone picked in the new app is never touched;
  * someone who removed their photo in the old app loses the copy too.
Nothing in R2 is ever changed or deleted: it is only read.

Needs (in ~/.liftbook-import.env, chmod 600; never printed):
  NEON_DATABASE_URL          the old database
  SUPABASE_DB_URL            the new database
  SUPABASE_SERVICE_ROLE_KEY  Supabase > Project Settings > API keys (service_role or a secret key);
                             a dry run works without it
  SUPABASE_URL               optional; https://qjlmxlnmfowqsunpzvac.supabase.co by default
  R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID, R2_BUCKET_NAME   optional
"""

from __future__ import annotations

import argparse
import os
import posixpath
import sys
import urllib.parse
import uuid
from collections import Counter
from pathlib import Path

import psycopg2
import requests

# The same ids scripts/import_to_supabase.py gives people.
NAMESPACE = uuid.UUID("5d0c7a51-58a4-4c4b-9a62-6c1f0f3b2a10")
DEFAULT_SUPABASE_URL = "https://qjlmxlnmfowqsunpzvac.supabase.co"
# utils/profile_images.py
R2_DEFAULT_ACCOUNT_ID = "c60933f634439b0fb2e6c7762535ba6c"
R2_DEFAULT_BUCKET_NAME = "workout-tracker-avatars"
R2_PUBLIC_BASE_URL = "https://pub-b7699fec85f44832bc1255cae990054b.r2.dev"
BUCKET = "avatars"
MAX_BYTES = 2 * 1024 * 1024  # the avatars bucket's limit
TIMEOUT = 30


def user_id_for(old_id) -> str:
    return str(uuid.uuid5(NAMESPACE, f"users:{old_id}"))


def normalize_key(profile_image) -> str:
    """utils/profile_images.normalize_profile_image_key."""
    key = str(profile_image or "").strip().lstrip("/")
    for prefix in ("static/uploads/", "uploads/"):
        if key.startswith(prefix):
            return key[len(prefix):]
    return key


def target_path(user_id: str, key: str) -> str:
    return f"{user_id}/legacy-{posixpath.basename(key)}"


def is_legacy(user_id: str, path) -> bool:
    return bool(path) and str(path).startswith(f"{user_id}/legacy-")


def content_type(data: bytes) -> str | None:
    """From the file itself (PNG/JPEG/WebP signatures); the old app saved PNGs."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class R2:
    """Read-only access to the old bucket."""

    def __init__(self, env):
        self.client = None
        if env.get("R2_ACCESS_KEY_ID") and env.get("R2_SECRET_ACCESS_KEY"):
            import boto3

            self.client = boto3.client(
                "s3",
                endpoint_url=f"https://{env.get('R2_ACCOUNT_ID') or R2_DEFAULT_ACCOUNT_ID}.r2.cloudflarestorage.com",
                aws_access_key_id=env["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
                region_name="auto",
            )
            self.bucket = env.get("R2_BUCKET_NAME") or R2_DEFAULT_BUCKET_NAME

    @property
    def how(self) -> str:
        return "R2 with its access key" if self.client else "R2's public address"

    def get(self, key: str) -> bytes | None:
        """The photo's bytes, or None if R2 doesn't have it."""
        if self.client:
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except self.client.exceptions.NoSuchKey:
                return None
        r = requests.get(f"{R2_PUBLIC_BASE_URL}/{urllib.parse.quote(key)}", timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content


class Storage:
    """Supabase Storage with the service key (only what this script needs)."""

    def __init__(self, url: str, key: str):
        self.base = f"{url.rstrip('/')}/storage/v1"
        self.headers = {"apikey": key}
        if key.startswith("eyJ"):  # the older service_role key is a JWT; secret keys go in apikey only
            self.headers["Authorization"] = f"Bearer {key}"

    def _url(self, *parts: str) -> str:
        return "/".join([self.base, *parts[:-1], urllib.parse.quote(parts[-1])])

    def exists(self, path: str) -> bool:
        r = requests.get(self._url("object", "info", BUCKET, path), headers=self.headers, timeout=TIMEOUT)
        if r.status_code in (400, 404):
            return False
        r.raise_for_status()
        return True

    def upload(self, path: str, data: bytes, ctype: str) -> None:
        r = requests.post(self._url("object", BUCKET, path), data=data, timeout=TIMEOUT,
                          headers={**self.headers, "Content-Type": ctype, "x-upsert": "true", "Cache-Control": "3600"})
        if r.status_code >= 300:
            raise RuntimeError(f"upload failed ({r.status_code}): {r.text[:200]}")

    def remove(self, path: str) -> None:
        r = requests.delete(f"{self.base}/object/{BUCKET}", json={"prefixes": [path]}, headers=self.headers, timeout=TIMEOUT)
        if r.status_code >= 300:
            raise RuntimeError(f"remove failed ({r.status_code}): {r.text[:200]}")


def plan(old_users, profiles):
    """What to do for each person: [(action, username, user_id, key, target, current)].

    old_users: [(old id, username, profile_image)]; profiles: {user_id: avatar_path}."""
    out = []
    for old_id, username, profile_image in old_users:
        uid = user_id_for(old_id)
        if uid not in profiles:
            if profile_image:
                out.append(("no-account", username, uid, normalize_key(profile_image), None, None))
            continue
        current = profiles[uid]
        key = normalize_key(profile_image)
        if not key:
            # No photo in the old app any more: drop our copy of the old one, never a new-app photo.
            if is_legacy(uid, current):
                out.append(("clear", username, uid, None, None, current))
            continue
        target = target_path(uid, key)
        if current and not is_legacy(uid, current):
            out.append(("kept-new-app-photo", username, uid, key, target, current))
        elif current == target:
            out.append(("check", username, uid, key, target, current))
        else:
            out.append(("copy", username, uid, key, target, current))
    return out


def set_avatar(db, uid: str, path) -> None:
    # updated_at moves on so the change wins over older copies and devices pull it.
    db.execute("update public.profiles set avatar_path = %s, updated_at = clock_timestamp() where user_id = %s",
               (path, uid))


def run(env, dry_run: bool, out=print) -> Counter:
    counts = Counter()
    r2 = R2(env)
    # A dry run can go without the service key; it then can't check copies already made.
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    storage = Storage(env.get("SUPABASE_URL") or DEFAULT_SUPABASE_URL, key) if key else None
    src = psycopg2.connect(env["NEON_DATABASE_URL"])
    dst = psycopg2.connect(env["SUPABASE_DB_URL"])
    try:
        with src.cursor() as cur:
            cur.execute("select id, username, profile_image from users order by id")
            old_users = cur.fetchall()
        with dst.cursor() as cur:
            cur.execute("select user_id::text, avatar_path from public.profiles")
            profiles = dict(cur.fetchall())
        out(f"{'DRY RUN: nothing is changed. ' if dry_run else ''}Reading photos from {r2.how}.")

        for action, username, uid, key, target, current in plan(old_users, profiles):
            if action == "no-account":
                out(f"  {username}: has a photo but no Supabase account yet (run the import first)")
                counts["no account"] += 1
                continue
            if action == "kept-new-app-photo":
                counts["kept (picked in the new app)"] += 1
                continue
            if action == "clear":
                out(f"  {username}: removed their photo in the old app; removing the copy")
                if not dry_run:
                    with dst, dst.cursor() as cur:
                        set_avatar(cur, uid, None)
                    storage.remove(current)
                counts["removed"] += 1
                continue
            if action == "check" and (storage is None or storage.exists(target)):
                counts["already copied" if storage else "already set (not checked)"] += 1
                continue

            data = r2.get(key)
            if data is None:
                out(f"  {username}: {key} isn't in R2 (an old photo kept on the old server's disk?); skipped")
                counts["missing in R2"] += 1
                continue
            ctype = content_type(data)
            if not ctype:
                out(f"  {username}: {key} isn't a PNG, JPEG or WebP picture; skipped")
                counts["not a picture"] += 1
                continue
            if len(data) > MAX_BYTES:
                out(f"  {username}: {key} is over 2 MB; skipped")
                counts["too big"] += 1
                continue
            out(f"  {username}: {'would copy' if dry_run else 'copying'} {key} ({len(data) // 1024} KB)")
            if not dry_run:
                storage.upload(target, data, ctype)
                with dst, dst.cursor() as cur:
                    set_avatar(cur, uid, target)
                # The copy of an older old-app photo goes; R2 keeps everything.
                if is_legacy(uid, current) and current != target:
                    storage.remove(current)
            counts["would copy" if dry_run else "copied"] += 1
    finally:
        src.close()
        dst.close()
    return counts


ENV_FILE = Path.home() / ".liftbook-import.env"


def load_env(path: Path = ENV_FILE) -> dict:
    """KEY=value lines (quotes optional, # comments), then the shell's own variables on top."""
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            env[k.strip().removeprefix("export ").strip()] = v
    env.update({k: v for k, v in os.environ.items() if v})
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show what would be copied; change nothing")
    args = parser.parse_args()
    needed = ("NEON_DATABASE_URL", "SUPABASE_DB_URL") + (() if args.dry_run else ("SUPABASE_SERVICE_ROLE_KEY",))
    env = load_env()
    missing = [k for k in needed if not env.get(k)]
    if missing:
        sys.exit(f"Fill in {', '.join(missing)} in {ENV_FILE}.")
    counts = run(env, args.dry_run)
    print("Done." if not args.dry_run else "Dry run done.", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "No photos.")


if __name__ == "__main__":
    main()
