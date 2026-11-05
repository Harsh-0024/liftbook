#!/usr/bin/env python3
"""Copy everything from the old app's database (Neon) into Liftbook's Supabase project.

    NEON_DATABASE_URL=postgresql://...  SUPABASE_DB_URL=postgresql://... \\
        python scripts/import_to_supabase.py [--dry-run]

Run supabase/schema.sql in the Supabase project first. --dry-run does the
whole import inside one transaction and then rolls it back, printing what it
would have copied.

Safe to run again, as often as needed until the switch to the new app:
  * Every row gets the same id each time (made from its old id), so a second
    run updates rows instead of copying them twice.
  * Sign-ins are only ever added, never changed, so a password someone
    changed in the new app stays.
  * Workouts deleted in the old app since the last run are marked deleted.
After people start using the new app, don't run it again: it would put the
old app's version of anything they changed back.

Passwords carry over as they are: both apps use bcrypt, so everyone signs in
with the password they already have. Accounts without an email can't sign in
to Supabase with a password; they are listed at the end.

Workout times: the old app saved an undated workout with its server's clock
(UTC), and a dated one as midnight of that day. The new app keeps every
workout in the person's own clock time, so undated ones (any time but exactly
midnight) are moved to LIFTBOOK_TIME_ZONE (India by default) as they are
copied: one saved at 1:30 am in India lands on that day, not the night before.
A workout already in Supabase gets the moved time on the next run.

Not copied: `lifts` (the app works it out from the workouts), email codes
(Supabase Auth sends its own), the app icon (a file in the new app) and
profile photos (they move from R2 separately).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras

# Ids in Supabase are made from the old ids, so every run gives the same ones.
NAMESPACE = uuid.UUID("5d0c7a51-58a4-4c4b-9a62-6c1f0f3b2a10")


def new_id(table: str, old_id) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{table}:{old_id}"))


def utc(value):
    """The old app stored server times without a zone; its servers ran on UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


# The people's time zone: undated old workouts were stamped in UTC and move to it.
LOCAL_ZONE = ZoneInfo(os.environ.get("LIFTBOOK_TIME_ZONE", "Asia/Kolkata"))


def local_workout_time(value: datetime) -> datetime:
    """An old workout_logs.date as the person's own clock time (no zone), as the new app keeps it.

    Exactly midnight: a date written in the workout, already the person's day; kept.
    Anything else: the old server's clock (UTC) when an undated workout was saved; moved."""
    if value is None or value.tzinfo is not None:
        return value
    if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
        return value
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_ZONE).replace(tzinfo=None)


def rows(cur, sql: str):
    cur.execute(sql)
    return cur.fetchall()


def source_tables(cur) -> set[str]:
    cur.execute("select table_name from information_schema.tables where table_schema = 'public'")
    return {r["table_name"] for r in cur.fetchall()}


def upsert(cur, table: str, key: tuple[str, ...], record: dict) -> None:
    """Add the row, or update it when anything but its times differs.

    updated_at is "now" so keep_newest() lets the change through; an unchanged
    row isn't touched at all, so running again changes nothing.
    """
    cols = list(record)
    compared = [c for c in cols if c not in key and c not in ("updated_at", "created_at")]
    sql = (
        f"insert into public.{table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
        f"on conflict ({', '.join(key)}) do update set "
        + ", ".join(f"{c} = excluded.{c}" for c in cols if c not in key)
    )
    if compared:
        sql += (
            f" where ({', '.join(f'{table}.{c}' for c in compared)})"
            f" is distinct from ({', '.join(f'excluded.{c}' for c in compared)})"
        )
    cur.execute(sql, [record[c] for c in cols])


def as_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return psycopg2.extras.Json(value)


def ordered_admins(users: list[dict], admin_email: str) -> list[dict]:
    """Same order as the old app: ADMIN_EMAIL's account first, then by id."""
    admins = sorted((u for u in users if u["role"] == "admin"), key=lambda u: u["id"])
    wanted = admin_email.strip().lower()
    first = [u for u in admins if wanted and (u["email"] or "").strip().lower() == wanted]
    return first + [u for u in admins if u not in first]


def import_users(src, dst, counts, notes, admin_email):
    users = rows(src, "select * from users order by id")
    user_ids = {}
    for u in users:
        uid = new_id("users", u["id"])
        user_ids[u["id"]] = uid
        email = (u["email"] or "").strip().lower() or None
        created = utc(u["created_at"]) or datetime.now(timezone.utc)
        meta = {"username": u["username"], "full_name": u["full_name"] or ""}

        dst.execute("select 1 from auth.users where id = %s", (uid,))
        if dst.fetchone() is None:
            if email:
                dst.execute("select 1 from auth.users where lower(email) = %s", (email,))
                if dst.fetchone() is not None:
                    notes.append(f"{u['username']}: {email} already has a different Supabase account; skipped")
                    user_ids.pop(u["id"])
                    continue
            dst.execute(
                """
                insert into auth.users (
                    id, instance_id, aud, role, email, encrypted_password, email_confirmed_at,
                    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
                    confirmation_token, recovery_token, email_change_token_new, email_change)
                values (%s, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',
                        %s, %s, %s, %s, %s, %s, %s, '', '', '', '')
                """,
                (
                    uid, email, u["password_hash"] or "",
                    created if (u["is_verified"] and email) else None,
                    psycopg2.extras.Json({"provider": "email", "providers": ["email"]}),
                    psycopg2.extras.Json(meta), created, utc(u["updated_at"]) or created,
                ),
            )
            if email:
                dst.execute(
                    """
                    insert into auth.identities (
                        id, provider_id, user_id, identity_data, provider, created_at, updated_at)
                    values (%s, %s, %s, %s, 'email', %s, %s)
                    on conflict do nothing
                    """,
                    (
                        new_id("identities", u["id"]), uid, uid,
                        psycopg2.extras.Json({"sub": uid, "email": email, "email_verified": bool(u["is_verified"])}),
                        created, created,
                    ),
                )
            counts["sign-ins added"] += 1
        if not email:
            notes.append(f"{u['username']}: no email, so can't sign in until one is added")
        if not u["is_verified"] and email:
            notes.append(f"{u['username']}: email was never confirmed in the old app")
        if u["password_hash"] and not u["password_hash"].startswith("$2"):
            notes.append(f"{u['username']}: password isn't a bcrypt hash; they'll need to reset it")

        upsert(dst, "profiles", ("user_id",), {
            "user_id": uid,
            "legacy_id": u["id"],
            "username": u["username"],
            "full_name": u["full_name"] or "",
            "bodyweight": u["bodyweight"],
            "created_at": created,
            "updated_at": datetime.now(timezone.utc),
        })
        counts["profiles"] += 1

    for order, admin in enumerate(ordered_admins(users, admin_email)):
        if admin["id"] not in user_ids:
            continue
        dst.execute(
            """
            insert into public.admins (user_id, added_at)
            values (%s, timestamptz '2000-01-01 00:00:00+00' + %s * interval '1 second')
            on conflict (user_id) do update set added_at = excluded.added_at
            """,
            (user_ids[admin["id"]], order),
        )
        counts["admins"] += 1

    return users, user_ids


def import_settings(src, dst, tables, users, user_ids, counts):
    retrieval = {}
    if "custom_retrieval_preferences" in tables:
        retrieval = {r["user_id"]: r for r in rows(src, "select * from custom_retrieval_preferences")}
    stats = {}
    if "stats_preferences" in tables:
        stats = {r["user_id"]: r for r in rows(src, "select * from stats_preferences")}

    for u in users:
        if u["id"] not in user_ids:
            continue
        settings = {
            "follow_shared_plan": bool(u.get("follow_admin_plan", False)),
            "follow_shared_exercises": bool(u.get("follow_admin_exercises", False)),
        }
        if u["id"] in retrieval:
            settings["retrieval_sort"] = retrieval[u["id"]]["sort_mode"]
        if u["id"] in stats:
            settings["stats_sort"] = stats[u["id"]]["sort_mode"]
            settings["stats_range"] = stats[u["id"]]["time_range"]
        upsert(dst, "app_settings", ("user_id",), {
            "user_id": user_ids[u["id"]],
            "json": psycopg2.extras.Json(settings),
            "updated_at": datetime.now(timezone.utc),
        })
        counts["app settings"] += 1


def import_texts(src, dst, tables, user_ids, counts):
    for table, kind in (("plans", "plan"), ("rep_ranges", "rep_ranges"), ("shortcut_key_maps", "shortcut_keys")):
        if table not in tables:
            continue
        for r in rows(src, f"select * from {table}"):
            if r["user_id"] not in user_ids or r["text_content"] is None:
                continue
            upsert(dst, "user_texts", ("user_id", "kind"), {
                "user_id": user_ids[r["user_id"]],
                "kind": kind,
                "text": r["text_content"],
                "updated_at": datetime.now(timezone.utc),
            })
            counts[f"texts: {kind}"] += 1


def import_logs(src, dst, user_ids, counts):
    seen = []
    for r in rows(src, "select * from workout_logs order by id"):
        if r["user_id"] not in user_ids:
            continue
        when = local_workout_time(r["date"])
        if when != r["date"]:
            counts["workout times moved from UTC to local time"] += 1
            if when.date() != r["date"].date():
                counts["  ...of which now on a different (the right) day"] += 1
        upsert(dst, "workout_logs", ("user_id", "id"), {
            "user_id": user_ids[r["user_id"]],
            "id": new_id("workout_logs", r["id"]),
            "legacy_id": r["id"],
            "date": when,
            "workout_name": r["workout_name"],
            "exercise": r["exercise"],
            "exercise_string": r["exercise_string"],
            "sets": as_json(r["sets_json"]),
            "bodyweight": r["bodyweight"],
            "uses_bodyweight": r["uses_bodyweight"],
            "top_weight": r["top_weight"],
            "top_reps": r["top_reps"],
            "estimated_1rm": r["estimated_1rm"],
            "created_at": utc(r["date"]),
            "updated_at": datetime.now(timezone.utc),
            "deleted_at": None,
        })
        seen.append(r["id"])
        counts["workouts"] += 1
    return seen


def import_exercise_settings(src, dst, tables, user_ids, counts):
    merged: dict[tuple[int, str], dict] = {}

    def entry(user_id, key):
        return merged.setdefault((user_id, key), {})

    if "timed_exercise_preferences" in tables:
        for r in rows(src, "select * from timed_exercise_preferences"):
            entry(r["user_id"], r["exercise_key"])["is_timed"] = r["is_timed"]
    if "bodyweight_exercise_preferences" in tables:
        for r in rows(src, "select * from bodyweight_exercise_preferences"):
            e = entry(r["user_id"], r["exercise_key"])
            e["is_bodyweight"] = r["is_bodyweight"]
            e["bodyweight_source"] = r["source"]
            e["exercise_name"] = r["exercise_name"]
    if "exercise_group_choices" in tables:
        for r in rows(src, "select * from exercise_group_choices"):
            entry(r["user_id"], r["exercise_key"])["group_name"] = r["group_name"]
    if "stats_exercise_views" in tables:
        for r in rows(src, "select * from stats_exercise_views"):
            e = entry(r["user_id"], r["exercise_key"])
            e["view_count"] = r["view_count"] or 0
            e["last_viewed_at"] = utc(r["last_viewed_at"])

    for (user_id, key), values in merged.items():
        if user_id not in user_ids:
            continue
        record = {
            "user_id": user_ids[user_id],
            "exercise_key": key,
            "exercise_name": None,
            "is_timed": None,
            "is_bodyweight": None,
            "bodyweight_source": None,
            "group_name": None,
            "view_count": 0,
            "last_viewed_at": None,
        }
        record.update(values)
        record["updated_at"] = datetime.now(timezone.utc)
        upsert(dst, "exercise_settings", ("user_id", "exercise_key"), record)
        counts["exercise settings"] += 1


def import_retrieval_events(src, dst, tables, user_ids, counts):
    seen = []
    if "custom_retrieval_events" not in tables:
        return seen
    for r in rows(src, "select * from custom_retrieval_events order by id"):
        if r["user_id"] not in user_ids:
            continue
        upsert(dst, "retrieval_events", ("user_id", "id"), {
            "user_id": user_ids[r["user_id"]],
            "id": new_id("custom_retrieval_events", r["id"]),
            "legacy_id": r["id"],
            "exercise_key": r["exercise_key"],
            "retrieved_at": utc(r["retrieved_at"]),
            "updated_at": datetime.now(timezone.utc),
            "deleted_at": None,
        })
        seen.append(r["id"])
        counts["retrieval events"] += 1
    return seen


def import_renames(src, dst, tables, user_ids, counts):
    seen = []
    if "exercise_renames" not in tables:
        return seen
    for r in rows(src, "select * from exercise_renames order by id"):
        if r["user_id"] not in user_ids:
            continue
        old_log_ids = r["log_ids"]
        if isinstance(old_log_ids, str):
            try:
                old_log_ids = json.loads(old_log_ids)
            except ValueError:
                old_log_ids = []
        upsert(dst, "exercise_renames", ("user_id", "id"), {
            "user_id": user_ids[r["user_id"]],
            "id": new_id("exercise_renames", r["id"]),
            "legacy_id": r["id"],
            "old_key": r["old_key"],
            "old_name": r["old_name"],
            "new_name": r["new_name"],
            "log_ids": psycopg2.extras.Json([new_id("workout_logs", i) for i in (old_log_ids or [])]),
            "created_at": utc(r["created_at"]),
            "updated_at": datetime.now(timezone.utc),
            "deleted_at": None,
        })
        seen.append(r["id"])
        counts["renames"] += 1
    return seen


def mark_removed(dst, table: str, kept: list[int], counts) -> None:
    """Rows copied on an earlier run whose old row has since been deleted."""
    dst.execute(
        f"""
        update public.{table} set deleted_at = now(), updated_at = now()
        where legacy_id is not null and deleted_at is null and not (legacy_id = any(%s))
        """,
        (kept,),
    )
    if dst.rowcount:
        counts[f"{table} marked deleted"] += dst.rowcount


def import_once_tables(src, dst, tables, user_ids, counts):
    """Tables that are only ever added to: copied once per old row."""
    if "user_api_keys" in tables:
        for r in rows(src, "select * from user_api_keys order by id"):
            if r["user_id"] not in user_ids:
                continue
            dst.execute(
                """
                insert into public.ai_keys (legacy_id, user_id, label, api_key, is_active, created_at, last_used_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (legacy_id) do update set is_active = excluded.is_active,
                                                      last_used_at = excluded.last_used_at
                """,
                (r["id"], user_ids[r["user_id"]], r["account_label"] or "", r["api_key"], r["is_active"],
                 utc(r["created_at"]), utc(r["last_used_at"])),
            )
            counts["AI keys"] += 1
    if "feedback" in tables:
        for r in rows(src, "select * from feedback order by id"):
            if r["user_id"] not in user_ids:
                continue
            dst.execute(
                """
                insert into public.feedback (legacy_id, user_id, kind, message, page, status, created_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (legacy_id) do update set status = excluded.status
                """,
                (r["id"], user_ids[r["user_id"]], r["kind"], r["message"], (r["page"] or "")[:200],
                 r["status"], utc(r["created_at"])),
            )
            counts["feedback"] += 1
    if "coach_answers" in tables:
        for r in rows(src, "select * from coach_answers order by id"):
            if r["user_id"] not in user_ids:
                continue
            dst.execute(
                """
                insert into public.coach_answers (legacy_id, user_id, question, answer, source, model, steps,
                                                  calls, tokens, ms, failed, rating, comment, created_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (legacy_id) do update set rating = excluded.rating, comment = excluded.comment
                """,
                (r["id"], user_ids[r["user_id"]], r["question"], r["answer"], r["source"], r["model"],
                 as_json(r["steps"]), r["calls"], r["tokens"], r["ms"], r["failed"], r["rating"],
                 r["comment"], utc(r["created_at"])),
            )
            counts["coach answers"] += 1


def run(source_url: str, target_url: str, dry_run: bool, admin_email: str = "") -> tuple[Counter, list[str]]:
    counts: Counter = Counter()
    notes: list[str] = []

    source = psycopg2.connect(source_url)
    target = psycopg2.connect(target_url)
    try:
        source.set_session(readonly=True)
        src = source.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        dst = target.cursor()
        dst.execute("set time zone 'UTC'")
        tables = source_tables(src)

        users, user_ids = import_users(src, dst, counts, notes, admin_email)
        import_settings(src, dst, tables, users, user_ids, counts)
        import_texts(src, dst, tables, user_ids, counts)
        mark_removed(dst, "workout_logs", import_logs(src, dst, user_ids, counts), counts)
        import_exercise_settings(src, dst, tables, user_ids, counts)
        mark_removed(dst, "retrieval_events", import_retrieval_events(src, dst, tables, user_ids, counts), counts)
        mark_removed(dst, "exercise_renames", import_renames(src, dst, tables, user_ids, counts), counts)
        import_once_tables(src, dst, tables, user_ids, counts)

        if dry_run:
            target.rollback()
        else:
            target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()
    return counts, notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="copy everything, then undo it")
    args = parser.parse_args()

    source_url = os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL")
    target_url = os.environ.get("SUPABASE_DB_URL")
    if not source_url or not target_url:
        sys.exit("Set NEON_DATABASE_URL (the old database) and SUPABASE_DB_URL (the new one).")

    counts, notes = run(source_url, target_url, args.dry_run, os.environ.get("ADMIN_EMAIL", ""))
    print("Dry run: nothing was saved." if args.dry_run else "Copied:")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    if notes:
        print("\nWorth knowing:")
        for note in notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
