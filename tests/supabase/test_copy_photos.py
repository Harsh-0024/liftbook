"""scripts/copy_photos_to_supabase.py: the plan without a database, then whole runs on a real
Postgres (LIFTBOOK_TEST_PG, as test_supabase_import.py) with R2 and Supabase Storage faked."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import copy_photos_to_supabase as photos  # noqa: E402
from test_supabase_import import SERVER, connect, databases, importer, seed  # noqa: E402,F401  (databases: a fixture)

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 100


def test_paths_and_picture_types():
    uid = photos.user_id_for(5)
    assert photos.normalize_key("static/uploads/avatars/user_5_ab.png") == "avatars/user_5_ab.png"
    assert photos.normalize_key("/avatars/user_5_ab.png") == "avatars/user_5_ab.png"
    assert photos.target_path(uid, "avatars/user_5_ab.png") == f"{uid}/legacy-user_5_ab.png"
    assert photos.is_legacy(uid, f"{uid}/legacy-x.png") and not photos.is_legacy(uid, f"{uid}/avatar-1.png")
    assert photos.content_type(PNG) == "image/png"
    assert photos.content_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert photos.content_type(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert photos.content_type(b"<html>not found</html>") is None


def test_the_plan_leaves_new_app_photos_alone():
    u = {i: photos.user_id_for(i) for i in range(1, 7)}
    old = [(1, "fresh", "avatars/user_1_a.png"), (2, "copied", "avatars/user_2_b.png"),
           (3, "changed", "avatars/user_3_new.png"), (4, "picked_new", "avatars/user_4_c.png"),
           (5, "removed", None), (6, "never", None), (7, "not_imported", "avatars/user_7_d.png")]
    profiles = {u[1]: None, u[2]: f"{u[2]}/legacy-user_2_b.png", u[3]: f"{u[3]}/legacy-user_3_old.png",
                u[4]: f"{u[4]}/avatar-123.png", u[5]: f"{u[5]}/legacy-user_5_e.png", u[6]: None}
    got = {p[1]: p[0] for p in photos.plan(old, profiles)}
    assert got == {"fresh": "copy", "copied": "check", "changed": "copy", "picked_new": "kept-new-app-photo",
                   "removed": "clear", "not_imported": "no-account"}


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def exists(self, path):
        return path in self.objects

    def upload(self, path, data, ctype):
        self.objects[path] = (data, ctype)

    def remove(self, path):
        self.objects.pop(path, None)


@pytest.mark.skipif(not SERVER, reason="LIFTBOOK_TEST_PG isn't set")
def test_copy_then_again_then_after_changes(databases, monkeypatch):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)
    with connect(source) as cur:
        cur.execute("update users set profile_image = 'avatars/user_1_aaaa.png' where id = 1")
        cur.execute("update users set profile_image = 'static/uploads/avatars/user_2_gone.png' where id = 2")

    r2 = {"avatars/user_1_aaaa.png": PNG, "avatars/user_1_bbbb.png": PNG + b"2"}
    storage = FakeStorage()
    monkeypatch.setattr(photos.R2, "get", lambda self, key: r2.get(key))
    monkeypatch.setattr(photos, "Storage", lambda url, key: storage)
    env = {"NEON_DATABASE_URL": source, "SUPABASE_DB_URL": target, "SUPABASE_SERVICE_ROLE_KEY": "test"}
    lines = []
    me = photos.user_id_for(1)

    def avatar(uid):
        with connect(target) as cur:
            cur.execute("select avatar_path from public.profiles where user_id = %s", (uid,))
            return cur.fetchone()[0]

    dry = photos.run(env, dry_run=True, out=lines.append)
    assert dry == {"would copy": 1, "missing in R2": 1}
    assert storage.objects == {} and avatar(me) is None

    assert photos.run(env, dry_run=False, out=lines.append) == {"copied": 1, "missing in R2": 1}
    assert storage.objects == {f"{me}/legacy-user_1_aaaa.png": (PNG, "image/png")}
    assert avatar(me) == f"{me}/legacy-user_1_aaaa.png"

    # Again: nothing to do.
    assert photos.run(env, dry_run=False, out=lines.append) == {"already copied": 1, "missing in R2": 1}

    # A new photo in the old app replaces the copy; R2 still has both.
    with connect(source) as cur:
        cur.execute("update users set profile_image = 'avatars/user_1_bbbb.png' where id = 1")
    assert photos.run(env, dry_run=False, out=lines.append)["copied"] == 1
    assert set(storage.objects) == {f"{me}/legacy-user_1_bbbb.png"}
    assert set(r2) == {"avatars/user_1_aaaa.png", "avatars/user_1_bbbb.png"}

    # A photo picked in the new app is never replaced.
    with connect(target) as cur:
        cur.execute("update public.profiles set avatar_path = %s, updated_at = clock_timestamp() where user_id = %s",
                    (f"{me}/avatar-1.png", me))
    assert photos.run(env, dry_run=False, out=lines.append)["kept (picked in the new app)"] == 1
    assert avatar(me) == f"{me}/avatar-1.png"

    # Removed in the old app (and still the copied one here): the copy goes.
    with connect(target) as cur:
        cur.execute("update public.profiles set avatar_path = %s, updated_at = clock_timestamp() where user_id = %s",
                    (f"{me}/legacy-user_1_bbbb.png", me))
    with connect(source) as cur:
        cur.execute("update users set profile_image = null where id = 1")
    assert photos.run(env, dry_run=False, out=lines.append)["removed"] == 1
    assert avatar(me) is None and storage.objects == {}
    assert not any("test" in line for line in lines), "the service key is never printed"


def test_settings_file_is_read_without_a_shell(tmp_path, monkeypatch):
    f = tmp_path / "env"
    f.write_text("# comment\nNEON_DATABASE_URL=postgresql://u:p@h/db?sslmode=require&channel_binding=require\n"
                 "export SUPABASE_DB_URL='postgresql://x'\nEMPTY=\n")
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_DB_URL", "from-shell")
    env = photos.load_env(f)
    assert env["NEON_DATABASE_URL"].endswith("&channel_binding=require")
    assert env["SUPABASE_DB_URL"] == "from-shell"
    assert env["EMPTY"] == ""
