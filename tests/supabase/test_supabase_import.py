"""supabase/schema.sql and scripts/import_to_supabase.py, on a real Postgres.

Needs a Postgres server it may create databases on:

    LIFTBOOK_TEST_PG=postgresql://localhost/postgres pytest tests/supabase

Skipped when LIFTBOOK_TEST_PG isn't set.
"""

import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import bcrypt
import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import errors  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import import_to_supabase as importer  # noqa: E402
from models import Base  # noqa: E402

SERVER = os.environ.get("LIFTBOOK_TEST_PG")
pytestmark = pytest.mark.skipif(not SERVER, reason="LIFTBOOK_TEST_PG isn't set")

PASSWORD_HASH = bcrypt.hashpw(b"lift-heavy-123", bcrypt.gensalt(rounds=4)).decode()


def database_url(name):
    return SERVER.rsplit("/", 1)[0] + "/" + name


@pytest.fixture
def databases():
    names = [f"lb_test_{kind}_{uuid.uuid4().hex[:8]}" for kind in ("source", "target")]
    admin = psycopg2.connect(SERVER)
    admin.autocommit = True
    with admin.cursor() as cur:
        for name in names:
            cur.execute(f"create database {name}")
    source_url, target_url = (database_url(n) for n in names)
    try:
        engine = create_engine(source_url.replace("postgresql://", "postgresql+psycopg2://"))
        Base.metadata.create_all(engine)
        engine.dispose()
        with connect(target_url) as cur:
            cur.execute((ROOT / "tests/supabase/auth_stub.sql").read_text())
            apply_schema(cur)
        yield source_url, target_url
    finally:
        with admin.cursor() as cur:
            for name in names:
                cur.execute(f"drop database if exists {name} with (force)")
        admin.close()


@contextmanager
def connect(url):
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()


def apply_schema(cur):
    cur.execute((ROOT / "supabase/schema.sql").read_text())


@contextmanager
def signed_in(url, user_id):
    """A connection that acts like the app signed in as user_id."""
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("set role authenticated")
            cur.execute("select set_config('request.jwt.claim.sub', %s, false)", (str(user_id),))
            yield cur
        conn.commit()
    finally:
        conn.close()


def seed(url):
    with connect(url) as cur:
        cur.execute(
            """
            insert into users (id, username, full_name, email, password_hash, role, is_verified, bodyweight,
                               follow_admin_plan, follow_admin_exercises, created_at, updated_at)
            values (1, 'harsh', 'Harsh', 'Owner@Example.com', %s, 'admin', true, 72.5, false, false,
                    '2025-01-02 03:04:05', '2025-06-01 00:00:00'),
                   (2, 'friend', null, 'friend@example.com', %s, 'user', true, null, true, true,
                    '2025-02-01 00:00:00', null),
                   (3, 'noemail', null, null, %s, 'user', true, null, true, true, '2025-03-01 00:00:00', null)
            """,
            (PASSWORD_HASH, PASSWORD_HASH, PASSWORD_HASH),
        )
        cur.execute("insert into plans (user_id, text_content) values (1, 'Day 1: Bench, Squat'), (2, '')")
        cur.execute("insert into rep_ranges (user_id, text_content) values (1, 'Bench: 5-8')")
        cur.execute(
            """
            insert into workout_logs (id, user_id, date, workout_name, exercise, exercise_string, sets_json,
                                      top_weight, top_reps, estimated_1rm)
            values (10, 1, '2025-05-01 18:30:00', 'Day 1', 'Bench Press', 'Bench Press 80x5',
                    '{"weights": [80], "reps": [5]}', 80, 5, 93.3),
                   (11, 1, '2025-05-03 18:30:00', 'Day 2', 'Squat', 'Squat 100x5',
                    '{"weights": [100], "reps": [5]}', 100, 5, 116.7),
                   (12, 2, '2025-05-02 07:00:00', null, 'Pull Up', 'Pull Up bw x 8', null, null, 8, null)
            """
        )
        cur.execute(
            "insert into timed_exercise_preferences (user_id, exercise_key, is_timed, created_at, updated_at) "
            "values (1, 'plank', true, now(), now())"
        )
        cur.execute(
            "insert into bodyweight_exercise_preferences (user_id, exercise_key, exercise_name, is_bodyweight, "
            "source, created_at, updated_at) values (1, 'plank', 'Plank', true, 'manual', now(), now())"
        )
        cur.execute(
            "insert into stats_exercise_views (user_id, exercise_key, view_count, last_viewed_at) "
            "values (1, 'bench press', 4, now())"
        )
        cur.execute("insert into stats_preferences (user_id, sort_mode, time_range, updated_at) "
                    "values (1, 'recent', '3m', now())")
        cur.execute("insert into custom_retrieval_events (user_id, exercise_key, retrieved_at) "
                    "values (1, 'bench press', now())")
        cur.execute(
            "insert into exercise_renames (user_id, old_key, old_name, new_name, log_ids, created_at) "
            "values (1, 'bench', 'Bench', 'Bench Press', '[10]', now())"
        )
        cur.execute(
            "insert into user_api_keys (user_id, account_label, api_key, is_active, created_at) "
            "values (1, 'main', 'AIzaSecretKey1234', true, now())"
        )
        cur.execute("insert into feedback (user_id, kind, message, page, status, created_at) "
                    "values (2, 'idea', 'Dark mode please', '/stats', 'new', now())")
        cur.execute(
            "insert into coach_answers (user_id, question, answer, source, created_at) "
            "values (1, 'How is my bench?', 'Going up.', 'ai', now())"
        )


def uid(old_id):
    return importer.new_id("users", old_id)


def test_import_copies_everything_and_again_changes_nothing(databases):
    source, target = databases
    seed(source)

    counts, notes = importer.run(source, target, dry_run=False)
    assert counts["sign-ins added"] == 3
    assert counts["workouts"] == 3
    assert counts["admins"] == 1
    assert any("noemail" in n for n in notes)

    with connect(target) as cur:
        cur.execute("select email, encrypted_password, email_confirmed_at is not null from auth.users where id = %s",
                    (uid(1),))
        assert cur.fetchone() == ("owner@example.com", PASSWORD_HASH, True)
        cur.execute("select count(*) from auth.identities")
        assert cur.fetchone()[0] == 2  # not for the account without an email
        cur.execute("select username, bodyweight from public.profiles where legacy_id = 1")
        assert cur.fetchone() == ("harsh", 72.5)
        cur.execute("select date, sets from public.workout_logs where legacy_id = 10")
        assert cur.fetchone() == (datetime(2025, 5, 1, 18, 30), {"weights": [80], "reps": [5]})
        cur.execute("select is_timed, is_bodyweight, exercise_name from public.exercise_settings "
                    "where exercise_key = 'plank'")
        assert cur.fetchone() == (True, True, "Plank")
        cur.execute("select view_count from public.exercise_settings where exercise_key = 'bench press'")
        assert cur.fetchone() == (4,)
        cur.execute("select json from public.app_settings where user_id = %s", (uid(1),))
        assert cur.fetchone()[0] == {"follow_shared_plan": False, "follow_shared_exercises": False,
                                     "stats_sort": "recent", "stats_range": "3m"}
        cur.execute("select log_ids from public.exercise_renames")
        assert cur.fetchone()[0] == [importer.new_id("workout_logs", 10)]
        cur.execute("select key_hint from public.ai_keys")
        assert cur.fetchone() == ("1234",)
        cur.execute("select max(server_updated_at) from public.workout_logs")
        first_stamp = cur.fetchone()[0]

    again, _ = importer.run(source, target, dry_run=False)
    assert again["sign-ins added"] == 0
    with connect(target) as cur:
        cur.execute("select count(*), max(server_updated_at) from public.workout_logs")
        assert cur.fetchone() == (3, first_stamp)  # nothing copied twice, nothing rewritten
        cur.execute("select count(*) from public.feedback")
        assert cur.fetchone()[0] == 1


def test_running_again_brings_changes_and_deletions(databases):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)

    with connect(source) as cur:
        cur.execute("delete from workout_logs where id = 11")
        cur.execute("update workout_logs set top_weight = 82.5 where id = 10")
        cur.execute("update plans set text_content = 'Day 1: Bench, Squat, Row' where user_id = 1")
    counts, _ = importer.run(source, target, dry_run=False)
    assert counts["workout_logs marked deleted"] == 1

    with connect(target) as cur:
        cur.execute("select legacy_id, top_weight, deleted_at is not null from public.workout_logs "
                    "where user_id = %s order by legacy_id", (uid(1),))
        assert cur.fetchall() == [(10, 82.5, False), (11, 100.0, True)]
        cur.execute("select text from public.user_texts where user_id = %s and kind = 'plan'", (uid(1),))
        assert cur.fetchone() == ("Day 1: Bench, Squat, Row",)


def test_dry_run_saves_nothing(databases):
    source, target = databases
    seed(source)
    counts, _ = importer.run(source, target, dry_run=True)
    assert counts["workouts"] == 3
    with connect(target) as cur:
        cur.execute("select (select count(*) from auth.users), (select count(*) from public.workout_logs)")
        assert cur.fetchone() == (0, 0)


def test_schema_runs_again_without_losing_anything(databases):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)
    with connect(target) as cur:
        apply_schema(cur)
        cur.execute("select count(*) from public.workout_logs")
        assert cur.fetchone()[0] == 3


def test_people_only_reach_their_own_rows(databases):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)
    me, other = uid(2), uid(1)

    with signed_in(target, me) as cur:
        cur.execute("select exercise from public.workout_logs")
        assert cur.fetchall() == [("Pull Up",)]
        cur.execute("select count(*) from public.user_texts")
        assert cur.fetchone()[0] == 1  # only their own (empty) plan
        cur.execute("select count(*) from public.feedback")
        assert cur.fetchone()[0] == 1
        cur.execute("select count(*) from public.ai_keys")
        assert cur.fetchone()[0] == 0
        # Changing someone else's row finds nothing to change.
        cur.execute("update public.workout_logs set top_reps = 99, updated_at = now() where user_id = %s", (other,))
        assert cur.rowcount == 0

    with signed_in(target, me) as cur:
        new_log = str(uuid.uuid4())
        cur.execute("insert into public.workout_logs (id, date, exercise) values (%s, now(), 'Dip')", (new_log,))
        cur.execute("select user_id from public.workout_logs where id = %s", (new_log,))
        assert cur.fetchone() == (me,)

    for statement, args in (
        ("insert into public.workout_logs (user_id, id, date, exercise) values (%s, %s, now(), 'Dip')",
         (other, str(uuid.uuid4()))),
        ("delete from public.workout_logs", None),
        ("update public.workout_logs set legacy_id = 1", None),
        ("select api_key from public.ai_keys", None),
        ("update public.feedback set status = 'done'", None),
        ("select * from public.admins", None),
        ("select public.admin_feedback()", None),
    ):
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            with signed_in(target, me) as cur:
                cur.execute(statement, args)


def test_signed_out_requests_get_nothing(databases):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)
    conn = psycopg2.connect(target)
    try:
        with conn.cursor() as cur:
            cur.execute("set role anon")
            cur.execute("select public.username_available('harsh'), public.username_available('newname')")
            assert cur.fetchone() == (False, True)
            with pytest.raises(errors.InsufficientPrivilege):
                cur.execute("select * from public.workout_logs")
    finally:
        conn.close()


def test_an_older_upload_never_wins(databases):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)
    with signed_in(target, uid(2)) as cur:
        cur.execute("update public.workout_logs set top_reps = 10, updated_at = '2001-01-01' "
                    "where legacy_id = 12")
        cur.execute("select top_reps from public.workout_logs where legacy_id = 12")
        assert cur.fetchone() == (8,)
        cur.execute("update public.workout_logs set top_reps = 10, updated_at = now() + interval '1 minute' "
                    "where legacy_id = 12")
        cur.execute("select top_reps from public.workout_logs where legacy_id = 12")
        assert cur.fetchone() == (10,)


def test_followers_see_the_admins_plan(databases):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)
    with signed_in(target, uid(2)) as cur:
        cur.execute("select public.shared_plan()")
        shared = cur.fetchone()[0]
        assert shared["plan"] == "Day 1: Bench, Squat"
        assert shared["rep_ranges"] == "Bench: 5-8"
        cur.execute("select public.is_admin()")
        assert cur.fetchone() == (False,)
    with signed_in(target, uid(1)) as cur:
        cur.execute("select public.is_admin(), json_array_length(public.admin_feedback())")
        assert cur.fetchone() == (True, 1)


def test_deleting_an_account_removes_everything(databases):
    source, target = databases
    seed(source)
    importer.run(source, target, dry_run=False)
    with signed_in(target, uid(1)) as cur:
        cur.execute("select public.delete_my_account()")
    with connect(target) as cur:
        cur.execute(
            "select (select count(*) from public.workout_logs where user_id = %(u)s),"
            "       (select count(*) from public.user_texts where user_id = %(u)s),"
            "       (select count(*) from public.ai_keys where user_id = %(u)s),"
            "       (select count(*) from public.workout_logs)",
            {"u": uid(1)},
        )
        assert cur.fetchone() == (0, 0, 0, 1)


def test_ai_keys_and_shortcut_keys_stay_private(databases):
    _, target = databases
    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    with connect(target) as cur:
        cur.execute("insert into auth.users (id, email) values (%s, 'me@x'), (%s, 'other@x')", (me, other))

    with signed_in(target, me) as cur:
        cur.execute("insert into public.ai_keys (label, api_key) values ('groq', 'gsk_abcdefghijkl'), ('gemini', 'AIzaabcdefghijk')")
        cur.execute("select label, provider, key_hint from public.ai_keys order by id")
        assert cur.fetchall() == [("groq", "groq", "ijkl"), ("gemini", "gemini", "hijk")]
        cur.execute("select public.new_shortcut_key()")
        first = cur.fetchone()[0]
        cur.execute("select public.new_shortcut_key()")
        key = cur.fetchone()[0]
        assert key.startswith("lbk_") and len(key) == 68 and key != first
        cur.execute("select key_hint from public.shortcut_keys")
        assert cur.fetchall() == [(key[-4:],)]

    # Only the hash is kept: the one the shortcut function looks up (sha256 of the key, hex).
    import hashlib
    with connect(target) as cur:
        cur.execute("select user_id::text from public.shortcut_keys where key_hash = %s", (hashlib.sha256(key.encode()).hexdigest(),))
        assert cur.fetchall() == [(me,)]

    with signed_in(target, other) as cur:
        cur.execute("select count(*) from public.ai_keys")
        assert cur.fetchone()[0] == 0
        cur.execute("delete from public.ai_keys")
        assert cur.rowcount == 0
        cur.execute("select public.remove_shortcut_key()")
    with signed_in(target, me) as cur:
        cur.execute("delete from public.ai_keys where label = 'gemini'")
        assert cur.rowcount == 1
        cur.execute("select count(*) from public.shortcut_keys")
        assert cur.fetchone()[0] == 1

    for statement in ("select key_hash from public.shortcut_keys", "select api_key from public.ai_keys",
                      "insert into public.shortcut_keys (user_id, key_hash, key_hint) values (auth.uid(), repeat('a', 64), 'aaaa')",
                      "update public.ai_keys set api_key = 'gsk_stolen_key_123'"):
        with pytest.raises(errors.InsufficientPrivilege):
            with signed_in(target, me) as cur:
                cur.execute(statement)


def test_edge_functions_service_role_can_do_what_they_need(databases):
    _, target = databases
    me = str(uuid.uuid4())
    with connect(target) as cur:
        cur.execute("insert into auth.users (id, email) values (%s, 'fn@x')", (me,))
    with signed_in(target, me) as cur:
        cur.execute("insert into public.ai_keys (label, api_key) values ('g', 'AIzaabcdefghijk')")
        cur.execute("select public.new_shortcut_key()")
    with connect(target) as cur:
        cur.execute("set role service_role")
        cur.execute("select user_id::text from public.shortcut_keys")
        assert cur.fetchall() == [(me,)]
        cur.execute("update public.shortcut_keys set last_used_at = now()")
        cur.execute("select api_key from public.ai_keys")
        assert cur.fetchall() == [("AIzaabcdefghijk",)]
        cur.execute("update public.ai_keys set last_used_at = now()")
        cur.execute("insert into public.coach_answers (user_id, question, answer) values (%s, 'q', 'a')", (me,))
        cur.execute("insert into public.user_texts (user_id, kind, text) values (%s, 'plan', 'Session 1')", (me,))
        cur.execute("select count(*) from public.admins")
        cur.execute("select public.shared_plan()")
    with pytest.raises(errors.InsufficientPrivilege):
        with connect(target) as cur:
            cur.execute("set role service_role")
            cur.execute("delete from public.shortcut_keys")
