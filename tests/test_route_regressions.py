import io
import re
import unittest
import os
import sys
from io import BytesIO
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from unittest.mock import Mock, patch

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

import workout_tracker
from config import Config
from models import (
    Base,
    BodyweightExercisePreference,
    CustomRetrievalEvent,
    CustomRetrievalPreference,
    Lift,
    Plan,
    StatsExerciseView,
    StatsPreference,
    User,
    UserRole,
    WorkoutLog,
)
from parsers.workout import workout_parser
from services.bodyweight import bodyweight_exercise_key
from services.exercise_matching import build_name_index, normalize_exercise_name
from services.logging import (
    _get_best_log,
    classify_exercise_performance,
    compute_workout_summary_for_date,
    comparison_set_count,
    get_best_log_for_exercise_before_date,
    handle_workout_log,
    resolve_target_sets_for_exercise,
)
from workout_tracker import create_app
from workout_tracker.routes.auth import _infer_bulk_import_dates
from utils import profile_images


class _RouteTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    ENABLE_CSRF = False
    WTF_CSRF_ENABLED = False


class TestRouteRegressions(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session = scoped_session(sessionmaker(bind=self.engine))
        Base.metadata.create_all(self.engine)

        # Rebind app/session globals used across route modules.
        self._patchers = [
            patch("models.Session", self.session),
            patch("workout_tracker.Session", self.session),
            patch("workout_tracker.routes.auth.Session", self.session),
            patch("workout_tracker.routes.workouts.Session", self.session),
            patch("workout_tracker.routes.stats.Session", self.session),
            patch("workout_tracker.routes.plans.Session", self.session),
        ]
        for p in self._patchers:
            p.start()

        self.app = create_app(config_object=_RouteTestConfig, init_db=False)
        self.client = self.app.test_client()

    def tearDown(self):
        for p in reversed(self._patchers):
            p.stop()
        self.session.remove()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_logged_in_user(self, *, username="route_tester", follow_admin=False):
        # Tests usually give the user their own plan; new accounts in the app follow the admin.
        user = User(
            username=username,
            role=UserRole.USER,
            is_verified=True,
            bodyweight=80.0,
            follow_admin_plan=follow_admin,
            follow_admin_exercises=follow_admin,
        )
        self.session.add(user)
        self.session.commit()
        user_id = int(user.id)
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True
            sess["_id"] = "route-test-session"
        return user

    def test_timed_preference_only_redirects_within_the_site(self):
        self._create_logged_in_user(username="timed_redirect_user")
        for next_url in ("//evil.com", "/\\evil.com", "https://evil.com/"):
            for query in (f"exercise=Plank&is_timed=yes&next={next_url}", f"next={next_url}"):
                response = self.client.get(f"/timed-preference/set?{query}")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/log", query)

        response = self.client.get("/timed-preference/set?exercise=Plank&is_timed=no&next=/workout/2026-09-30")
        self.assertEqual(response.headers["Location"], "/workout/2026-09-30")

    def test_service_worker_is_served_from_root_without_login(self):
        # Browsers refuse a service worker behind a redirect, so '/<username>'
        # must not catch /sw.js and send it to the login page.
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/javascript")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache")
        self.assertIn(b"addEventListener('fetch'", response.data)
        response.close()

        # A workout kept offline for a day that already has one waits to be added, never dropped.
        sync = self.client.get("/static/offline-sync.js")
        script = sync.get_data(as_text=True)
        sync.close()
        self.assertIn("already has a workout, so the one saved offline is waiting", script)
        self.assertNotIn("wasn't added", script)

        # The offline page says logging still works, and offers it.
        offline = self.client.get("/static/offline.html")
        self.assertIn('href="/log"', offline.get_data(as_text=True))
        offline.close()

        # What the worker fetches on install must not need a login either.
        for path in ("/static/offline.html", "/static/manifest.json"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()

    def test_pages_tell_the_service_worker_who_is_signed_in(self):
        # Signed out, the worker drops saved pages; signed in, it learns where '/' leads.
        login_page = self.client.get("/login").get_data(as_text=True)
        self.assertIn("{ type: 'signed-out' }", login_page)
        self.assertNotIn("type: 'signed-in'", login_page)

        self._create_logged_in_user(username="sw_owner")
        log_page = self.client.get("/log").get_data(as_text=True)
        self.assertIn('home: "/sw_owner",', log_page)
        self.assertIn('user: "sw_owner",', log_page)
        # Signed in, pages upload workouts kept offline.
        self.assertIn('offline-sync.js', log_page)
        self.assertNotIn('offline-sync.js', login_page)

    def _upload_offline(self, text, saved_at=None, user=None):
        payload = {"text": text}
        if saved_at is not None:
            payload["saved_at"] = int(saved_at.timestamp() * 1000)
        if user is not None:
            payload["user"] = user
        return self.client.post("/api/offline-workouts", json=payload)

    def test_offline_workout_uploads_on_the_day_it_was_saved(self):
        user = self._create_logged_in_user(username="offline_owner")
        saved_at = datetime.now().replace(microsecond=0) - timedelta(days=3)

        response = self._upload_offline("Push Day\nBench Press 100x5", saved_at, "Offline_Owner")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "saved")
        self.assertEqual(body["date"], saved_at.strftime("%Y-%m-%d"))
        self.assertEqual(body["url"], f"/summary/{saved_at:%Y-%m-%d}")
        log = self.session.query(WorkoutLog).filter_by(user_id=user.id).one()
        self.assertEqual(log.date, saved_at)

        # Sent again (the phone gave up waiting, but the first try got through).
        body = self._upload_offline("Push Day\nBench Press 100x5", saved_at).get_json()
        self.assertEqual(body["status"], "saved")
        # A different workout for that day is not added.
        body = self._upload_offline("Pull Day\nPull Ups 10", saved_at).get_json()
        self.assertEqual(body["status"], "already_there")
        self.assertEqual(body["url"], f"/workout/{saved_at:%Y-%m-%d}")
        self.assertEqual(self.session.query(WorkoutLog).filter_by(user_id=user.id).count(), 1)

    def test_offline_workout_upload_keeps_what_it_cannot_take(self):
        response = self._upload_offline("Push Day\nBench Press 100x5")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "signed_out")

        self._create_logged_in_user(username="offline_owner")
        response = self._upload_offline("Push Day\nBench Press 100x5", user="someone_else")
        self.assertEqual(response.status_code, 409)

        response = self._upload_offline("# nothing to read")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["status"], "invalid")
        self.assertTrue(response.get_json()["error"])
        self.assertNotIn("date", response.get_json())
        # A dated one that can't be read says which day it is, for "Your Thu 25 Sept workout...".
        response = self._upload_offline("25/9/26 Legs\n100, 5")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["date"], "2026-09-25")
        self.assertEqual(self.session.query(WorkoutLog).count(), 0)

    def test_offline_workout_kept_under_an_old_username_still_uploads(self):
        user = self._create_logged_in_user(username="renamed_now")
        page = self.client.get("/log").get_data(as_text=True)
        self.assertIn(f'data-user-id="{user.id}"', page)
        self.assertIn(f"userId: {user.id},", page)

        # Kept before the rename: the old username, but this account's id.
        response = self.client.post("/api/offline-workouts", json={
            "text": "20/9/26 Legs\nSquat 100x5", "user": "old_name", "user_id": user.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "saved")

        # Another account's workout is refused, whatever the name.
        response = self.client.post("/api/offline-workouts", json={
            "text": "21/9/26 Legs\nSquat 100x5", "user": "renamed_now", "user_id": user.id + 1})
        self.assertEqual(response.status_code, 409)

    def test_csrf_token_refresh_for_pages_opened_offline(self):
        self.assertEqual(self.client.get("/api/csrf-token").status_code, 302)
        self._create_logged_in_user(username="token_user")
        response = self.client.get("/api/csrf-token")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["token"])
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_fixed_offline_workout_keeps_its_saved_day(self):
        user = self._create_logged_in_user(username="offline_fixer")
        saved_at = datetime.now().replace(microsecond=0) - timedelta(days=2)
        response = self.client.post("/log", data={
            "workout_text": "Leg Day\nSquat 120x5",
            "saved_at": str(int(saved_at.timestamp() * 1000)),
            "offline_id": "kept-1",
        })
        self.assertEqual(response.status_code, 302)
        # The workout page it lands on tells the phone to forget its kept copy.
        location = urlsplit(response.headers["Location"])
        self.assertEqual(location.path, f"/workout/{saved_at:%Y-%m-%d}")
        self.assertIn("offline_saved=kept-1", location.query)
        log = self.session.query(WorkoutLog).filter_by(user_id=user.id).one()
        self.assertEqual(log.date, saved_at)

        # A time far in the future is ignored: the workout is saved as of now.
        self.client.post("/log", data={
            "workout_text": "Arm Day\nCurl 20x10",
            "saved_at": str(int((datetime.now() + timedelta(days=30)).timestamp() * 1000)),
        })
        newest = self.session.query(WorkoutLog).filter_by(user_id=user.id).order_by(WorkoutLog.id.desc()).first()
        self.assertEqual(newest.date.date(), date.today())

    def test_offline_workout_that_fails_again_keeps_its_place_on_the_phone(self):
        self._create_logged_in_user(username="offline_retry")
        saved_at = datetime.now().replace(microsecond=0) - timedelta(days=4)
        stamp = str(int(saved_at.timestamp() * 1000))
        response = self.client.post("/log", data={
            "workout_text": "# nothing to read",
            "saved_at": stamp,
            "offline_id": "kept-2",
        })
        self.assertEqual(response.status_code, 422)
        page = response.get_data(as_text=True)
        # Sent again from this page, it is still the same kept workout, dated the same day.
        self.assertIn('name="offline_id" value="kept-2"', page)
        self.assertIn(f'name="saved_at" value="{stamp}"', page)

        # An id that isn't one the phone makes is not echoed back.
        page = self.client.post("/log", data={
            "workout_text": "# nothing to read",
            "offline_id": '"><script>',
        }).get_data(as_text=True)
        self.assertNotIn('name="offline_id"', page)

        # A normal save doesn't mention the phone at all.
        response = self.client.post("/log", data={"workout_text": "Leg Day\nSquat 120x5"})
        self.assertNotIn("offline_saved", response.headers["Location"])

    def test_log_preview_checks_an_offline_workout_against_the_day_it_was_kept(self):
        user = self._create_logged_in_user(username="offline_preview")
        saved_at = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=5)
        self.session.add(WorkoutLog(
            user_id=user.id, date=saved_at, workout_name="Leg Day", exercise="Squat",
            top_weight=100, top_reps=5,
        ))
        self.session.commit()

        body = self.client.post("/log/preview", data={
            "workout_text": "Leg Day\nLeg Press 200x10",
            "mode": "append",
            "saved_at": str(int(saved_at.timestamp() * 1000)),
        }).get_json()
        self.assertEqual(body["date_str"], saved_at.strftime("%Y-%m-%d"))
        self.assertEqual(body["existing"]["date_str"], saved_at.strftime("%Y-%m-%d"))

    def test_every_page_has_its_own_title(self):
        # Titles name the page in tabs, history and for screen readers.
        self._create_logged_in_user(username="title_user")
        self.client.post("/log", data={"workout_text": "20/9/26 Leg Day\nSquat 120x5"})
        pages = {
            "/log": "Log workout",
            "/stats": "Stats",
            "/workouts": "All workouts",
            "/retrieve/categories": "Retrieve",
            "/retrieve/custom": "Custom workout",
            "/set_plan": "Workout plan",
            "/set_exercises": "Rep ranges",
            "/settings": "Settings",
            "/settings/account": "Account",
            "/settings/data": "Your data",
            "/settings/integrations": "Integrations",
            "/settings/more": "Bodyweight exercises",
            "/bulk-import": "Bulk import",
            "/shortcut/urls": "Apple Shortcuts",
            "/shortcut/mapping": "Session names",
            "/workout/2026-09-20": "Leg Day, Sun, 20 Sep 2026",
            "/workout/2026-09-20/edit": "Edit workout",
            "/no-such-page/really": "Page not found",
        }
        for path, title in pages.items():
            page = self.client.get(path).get_data(as_text=True)
            found = re.search(r"<title>(.*?)</title>", page, re.S)
            self.assertIsNotNone(found, path)
            self.assertEqual(found.group(1).strip(), f"{title} - Liftbook", path)

        self.assertIn(f"{date.today().year} Liftbook", self.client.get("/log").get_data(as_text=True))

    def test_integrations_page_does_not_overstate_how_keys_are_kept(self):
        # Keys are saved as written (not encrypted), so the page mustn't say "stored securely".
        self._create_logged_in_user(username="keys_page")
        page = self.client.get("/settings/integrations").get_data(as_text=True)
        self.assertNotIn("stored securely", page)
        self.assertIn("only ever shown by their last four characters", page)

    def test_keyboard_shortcut_list_shows_admin_panel_to_admins_only(self):
        user = self._create_logged_in_user(username="keys_user")
        page = self.client.get("/log").get_data(as_text=True)
        self.assertNotIn("Admin panel</span>", page)
        self.assertIn("key === 'a' && isAdminShortcutEnabled", page)
        self.assertIn(".modal.show:not(#shortcutsModal)", page)

        self.session.query(User).filter_by(id=user.id).update({"role": UserRole.ADMIN})
        self.session.commit()
        self.assertIn("Admin panel</span>", self.client.get("/log").get_data(as_text=True))

    def test_plan_changes_that_did_not_reach_the_server_come_back(self):
        self._create_logged_in_user(username="plan_keeper")
        page = self.client.get("/set_plan").get_data(as_text=True)
        self.assertIn("data-editor data-editor-keep>", page)
        self.assertIn("Not saved yet: your changes are back", page)
        # Bulk import shares the editor but not this (it shows other text after an import).
        self.assertNotIn("data-editor-keep>", self.client.get("/bulk-import").get_data(as_text=True))

    def test_edits_that_did_not_reach_the_server_come_back(self):
        # A save that ended on the sign-in page lost the edits; the page now keeps what was
        # sent and puts it back, and the workout page forgets it once saved.
        self._create_logged_in_user(username="edit_keeper")
        self.client.post("/log", data={"workout_text": "20/9/26 Legs\nSquat\n100, 5"})
        edit = self.client.get("/workout/2026-09-20/edit").get_data(as_text=True)
        self.assertIn('id="editRestored" role="status" hidden', edit)
        self.assertIn("sessionStorage.setItem(SENT_KEY, JSON.stringify(", edit)
        workout = self.client.get("/workout/2026-09-20").get_data(as_text=True)
        self.assertIn("k.startsWith('wt-edit-sent:", workout)

    def test_log_draft_is_kept_until_the_save_is_confirmed(self):
        # The draft was cleared as Save was pressed: a save that ended on the sign-in page
        # (session expired) lost the typed workout.
        self._create_logged_in_user(username="draft_keeper")
        page = self.client.get("/log").get_data(as_text=True)
        submit = page[page.index("form.addEventListener('submit'"):page.index("window.addEventListener('pageshow'")]
        self.assertNotIn("removeItem(DRAFT_KEY)", submit)
        self.assertIn("sessionStorage.setItem(SENT_KEY, textarea.value)", submit)
        self.client.post("/log", data={"workout_text": "20/9/26 Legs\nSquat\n100, 5"})
        saved_page = self.client.get("/workout/2026-09-20?saved=1").get_data(as_text=True)
        self.assertIn("if (localStorage.getItem(draftKey) === sent) localStorage.removeItem(draftKey);", saved_page)

    def test_export_date_range_problems_show_under_the_dates(self):
        self._create_logged_in_user(username="range_user")
        page = self.client.get("/settings/data").get_data(as_text=True)
        self.assertNotIn("window.alert(", page)
        self.assertIn('id="exportRangeError" role="alert" hidden', page)
        self.assertIn("The end date is before the start date.", page)

    def test_deleting_several_workouts_uses_the_app_confirm_box(self):
        self._create_logged_in_user(username="bulk_confirm")
        page = self.client.get("/workouts").get_data(as_text=True)
        self.assertIn("confirm: 'true', confirmTitle: title", page)
        self.assertIn("confirmDestructive: 'true'", page)
        # The browser's own box only where the form can't go through the app's one.
        self.assertIn("if (!form.requestSubmit && !window.confirm(", page)

    def test_log_page_sends_a_workout_once(self):
        # "Add to that day" skipped the Save button's guard, so a double tap added the exercises twice.
        self._create_logged_in_user(username="once_user")
        page = self.client.get("/log").get_data(as_text=True)
        self.assertIn("if (sending) {", page)
        self.assertIn("addBtn.el.textContent = 'Adding…';", page)

    def test_log_and_edit_bars_keep_the_count_readable_on_phones(self):
        # The check count sits beside the buttons; on narrow phones it stacks onto two
        # lines instead of being cut off, and Edit's button is as short as Log's.
        self._create_logged_in_user(username="bar_user")
        self.client.post("/log", data={"workout_text": "20/9/26 Leg Day\nSquat 120x5"})
        log_page = self.client.get("/log").get_data(as_text=True)
        edit_page = self.client.get("/workout/2026-09-20/edit").get_data(as_text=True)
        for page in (log_page, edit_page):
            self.assertIn(".lg-meta.is-stacked .lg-meta-part", page)
            self.assertIn("function fitMeta(el)", page)
        self.assertIn('id="saveBtn">Save</button>', edit_page)

    def test_an_exercise_done_twice_in_a_day_is_one_chart_point(self):
        user = self._create_logged_in_user(username="chart_twice")
        for day, sets in ((datetime(2026, 6, 1, 18), [(100.0, 5)]), (datetime(2026, 6, 3, 18), [(110.0, 5), (60.0, 12)])):
            handle_workout_log(self.session, user, {
                "date": day, "workout_name": "Legs",
                "exercises": [{"name": "Zercher Squat", "exercise_string": f"Zercher Squat\n{w}, {r}",
                               "weights": [w] * 3, "reps": [r] * 3, "valid": True} for w, r in sets],
            })
        self.session.commit()

        body = self.client.get("/stats/data/Zercher%20Squat").get_json()
        self.assertEqual(body["labels"], ["2026-06-01", "2026-06-03"])
        # The day's stronger entry is the point, not the lighter back-off after it.
        self.assertEqual(body["weight"], [100.0, 110.0])
        self.assertGreater(body["stats"]["improvement_pct"], 0)
        self.assertEqual(body["series"]["tonnage"][1], 110.0 * 5 * 3 + 60.0 * 12 * 3)

        average = self.client.get("/stats/data/average").get_json()
        self.assertEqual(average["labels"], ["2026-06-01", "2026-06-03"])
        self.assertGreater(average["data"][1], 0)

    def test_stats_range_buttons_show_the_saved_range_and_say_which_is_on(self):
        self._create_logged_in_user(username="pill_user")
        page = self.client.get("/stats").get_data(as_text=True)
        self.assertIn("b.setAttribute('aria-pressed', String(b.dataset.range === currentRange));", page)
        self.assertIn('data-range="90" aria-label="Last 3 months">3M<', page)
        self.assertIn("// The saved range (say 3M) was used for the chart while \"All\" stayed highlighted.\n    syncActivePills();", page)

    def test_stats_chart_draws_only_the_latest_request_and_says_when_it_fails(self):
        self._create_logged_in_user(username="chart_net")
        page = self.client.get("/stats").get_data(as_text=True)
        self.assertIn("if (ticket === chartTicket) renderChart(data);", page)
        self.assertIn("Couldn't load this chart. Check your connection and try again.", page)
        self.assertIn('id="chartEmptyText" role="status"', page)  # read out when it changes
        self.assertNotIn(".then(response => response.json())\n            .then(data => renderChart(data))", page)

    def test_bodyweight_exercise_chart_keeps_the_load_as_logged(self):
        # Stats showed "Last session 90 kg × 8" for pull-ups logged as BW+10.
        self._create_logged_in_user(username="chart_bw")
        self.client.post("/log", data={"workout_text": "20/9/26 Pull\nPull Ups\nBW+10 x 8\n\nBarbell Row\n70 x 8"})
        pull = self.client.get("/stats/data/Pull%20Ups").get_json()
        self.assertEqual((pull["weight"], pull["bodyweight_offset"]), ([90.0], [10.0]))
        row = self.client.get("/stats/data/Barbell%20Row").get_json()
        self.assertEqual(row["bodyweight_offset"], [None])
        page = self.client.get("/stats").get_data(as_text=True)
        self.assertIn("setTile(2, 'Last session', loadText(data, lastIdx)", page)

    def test_saving_a_workout_looks_each_exercise_up_once(self):
        # Whether an exercise is timed was worked out twice per exercise on every save.
        from sqlalchemy import event

        user = self._create_logged_in_user(username="save_speed")
        names = ["Flat Barbell Press", "Incline Dumbbell Press", "Cable Lateral Raise",
                 "Tricep Pushdown", "Low Cable Fly", "Overhead Extension"]
        for i in range(5):
            handle_workout_log(self.session, user, {
                "date": datetime(2026, 5, 1, 18) + timedelta(days=3 * i), "workout_name": "Push",
                "exercises": [{"name": n, "exercise_string": f"{n}\n{50 + i} 45, 8 9",
                               "weights": [50.0 + i, 45.0, 45.0], "reps": [8, 9, 9], "valid": True} for n in names],
            })
        self.session.commit()

        queries = []
        listener = lambda *args, **kwargs: queries.append(1)
        event.listen(self.engine, "before_cursor_execute", listener)
        try:
            text = "30/9/26 Push\n" + "\n".join(f"{n}\n60 55, 8 9" for n in names)
            response = self.client.post("/log", data={"workout_text": text})
        finally:
            event.remove(self.engine, "before_cursor_execute", listener)
        self.assertEqual(response.status_code, 302)
        # Per exercise, plus one per save for the user's renamed exercises.
        self.assertLess(len(queries), 11 * len(names) + 1)

    def test_exercise_chart_asks_the_database_a_fixed_number_of_times(self):
        # One query per session made long histories slow to chart on a remote database.
        from sqlalchemy import event

        user = self._create_logged_in_user(username="chart_speed")
        start = datetime(2026, 1, 1, 18, 0)
        for i in range(40):
            day = start + timedelta(days=2 * i)
            handle_workout_log(self.session, user, {
                "date": day, "workout_name": "Legs",
                "exercises": [{"name": "Back Squat", "exercise_string": f"Back Squat\n{100 + i} 90, 5 6",
                               "weights": [100.0 + i, 90.0, 90.0], "reps": [5, 6, 6], "valid": True}],
            })
        self.session.commit()

        queries = []
        listener = lambda *args, **kwargs: queries.append(1)
        event.listen(self.engine, "before_cursor_execute", listener)
        try:
            body = self.client.get("/stats/data/Back%20Squat").get_json()
        finally:
            event.remove(self.engine, "before_cursor_execute", listener)
        self.assertEqual(len(body["labels"]), 40)
        self.assertFalse(body["is_timed"])
        self.assertLess(len(queries), 25)

        # The Stats page itself doesn't build whole exports (it used to, twice, on every visit).
        queries.clear()
        event.listen(self.engine, "before_cursor_execute", listener)
        try:
            self.assertEqual(self.client.get("/stats").status_code, 200)
        finally:
            event.remove(self.engine, "before_cursor_execute", listener)
        self.assertLess(len(queries), 15)

    def test_header_buttons_show_keyboard_focus(self):
        # Bootstrap hides the outline on a plain .btn; the header's Settings and Log out are plain .btn.
        self._create_logged_in_user(username="focus_user")
        page = self.client.get("/log").get_data(as_text=True)
        self.assertIn('class="btn btn-sm mobile-header-btn"', page)
        # On phones the header buttons are icons only (their text is hidden), so they carry a name.
        self.assertIn('mobile-header-btn" aria-label="Settings"', page)
        self.assertIn('mobile-header-btn" aria-label="Log out"', page)
        rule = re.search(r"\.btn:focus-visible\s*\{([^}]*)\}", page)
        self.assertIsNotNone(rule)
        self.assertIn("outline: 2px solid", rule.group(1))

    def test_time_history_is_found_on_a_real_database(self):
        # Only logs with brackets are fetched; a hint in one of them still marks the exercise timed.
        from services.logging import _has_time_history

        user = self._create_logged_in_user(username="time_history")
        for day, text in ((1, "Dead Hang\nBW, 40"), (2, "Dead Hang - [30-60s]\nBW, 45"), (3, "Squat - [5-8]\n100, 5")):
            self.session.add(WorkoutLog(user_id=user.id, date=datetime(2026, 9, day), exercise=text.split(" - ")[0].split("\n")[0],
                                        exercise_string=text, top_weight=1, top_reps=1))
        self.session.add(WorkoutLog(user_id=user.id, date=datetime(2026, 9, 4), exercise="Plank", exercise_string=None,
                                    top_weight=1, top_reps=1))
        self.session.commit()
        self.assertTrue(_has_time_history(self.session, user.id, "Dead Hang"))
        self.assertFalse(_has_time_history(self.session, user.id, "Squat"))
        self.assertFalse(_has_time_history(self.session, user.id, "Plank"))

    def test_log_check_shows_seconds_like_the_workout_page(self):
        self._create_logged_in_user(username="timed_check")
        text = "29/9/26 Grip\nDead Hang\nBW, 40 35\n\nWrist Curl\n15, 15 12\n\nFarmer Walk - [20-60s]\n30, 40"

        def labels():
            body = self.client.post("/log/preview", data={"workout_text": text}).get_json()
            return {row["name"]: row["sets_label"] for row in body["exercises"]}

        # Known timed exercises and written time targets read as seconds; others as reps.
        self.assertEqual(labels(), {
            "Dead Hang": "BW×40s · BW×35s · BW×35s",
            "Wrist Curl": "15×15 · 15×12 · 15×12",
            "Farmer Walk": "30×40s · 30×40s · 30×40s",
        })
        # Once the user says Dead Hang is counted in reps, the check follows that answer.
        self.client.get("/timed-preference/set?exercise=Dead+Hang&is_timed=no&next=/log")
        self.assertEqual(labels()["Dead Hang"], "BW×40 · BW×35 · BW×35")

    def test_tab_bar_only_for_people_signed_in(self):
        # Signed out, every tab leads to the sign-in page; the share page has its own invite instead.
        page = self.client.get("/no-such-page/really").get_data(as_text=True)
        self.assertNotIn('class="mobile-bottom-nav', page)
        self.assertNotIn('<a class="nav-link" href="/stats">', page)  # nor the desktop links
        self.assertIn('mobile-header-btn" aria-label="Log in"', page)
        self.assertIn('mobile-header-btn" aria-label="Create account"', page)
        self.assertRegex(page, r'<body class="[^"]*is-signed-out')
        self._create_logged_in_user(username="tab_user")
        page = self.client.get("/log").get_data(as_text=True)
        self.assertIn('class="mobile-bottom-nav', page)
        self.assertIn('<a class="nav-link" href="/stats">', page)
        self.assertNotRegex(page, r'<body class="[^"]*is-signed-out')

    def test_a_page_left_open_for_hours_can_still_save(self):
        # A workout typed over a long gym session is saved hours after the Log page loaded.
        import time as time_module

        class _CsrfConfig(_RouteTestConfig):
            WTF_CSRF_ENABLED = True

        app = create_app(config_object=_CsrfConfig, init_db=False)
        self.assertIsNone(app.config["WTF_CSRF_TIME_LIMIT"])
        client = app.test_client()
        user = self._create_logged_in_user(username="slow_logger")
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
        page = client.get("/log").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        three_hours_later = time_module.time() + 3 * 3600
        with patch("time.time", return_value=three_hours_later):
            response = client.post("/log", data={"csrf_token": token, "workout_text": "20/9/26 Legs\nSquat 100x5"})
        self.assertEqual(response.status_code, 302)

        # A page that really is out of date says so, and that nothing was saved.
        response = client.post("/log", data={"csrf_token": "stale", "workout_text": "20/9/26 Legs\nSquat 100x5"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Nothing was saved", response.get_data(as_text=True))

    def test_settings_refuse_a_bodyweight_that_is_not_a_weight(self):
        user = self._create_logged_in_user(username="bw_setter")
        for raw in ("nan", "inf", "780"):
            self.client.post("/settings", data={"form_type": "bodyweight", "bodyweight": raw})
            self.session.expire_all()
            self.assertEqual(self.session.get(User, user.id).bodyweight, 80.0, raw)
        self.client.post("/settings", data={"form_type": "bodyweight", "bodyweight": "76.5"})
        self.session.expire_all()
        self.assertEqual(self.session.get(User, user.id).bodyweight, 76.5)

    def test_password_change_that_fails_does_not_say_it_worked(self):
        from services.auth import AuthService

        user = self._create_logged_in_user(username="pw_changer")
        self.session.query(User).filter_by(id=user.id).update({"password_hash": AuthService.hash_password("secret123")})
        self.session.commit()
        form = {"form_type": "password", "current_password": "secret123",
                "new_password": "newsecret1", "confirm_password": "newsecret1"}
        with patch("workout_tracker.routes.auth.AuthService.set_password", return_value=False):
            page = self.client.post("/settings", data=form, follow_redirects=True).get_data(as_text=True)
        self.assertNotIn("Password updated", page)
        self.assertIn("wasn&#39;t changed", page)

    def test_messages_are_short_and_calm(self):
        # "…updated successfully!" didn't match the redesign's tone ("Saved").
        self._create_logged_in_user(username="calm_user")
        self.client.post("/log", data={"workout_text": "20/9/26 Legs\nSquat\n100, 5"})
        page = self.client.post("/workout/2026-09-20/edit", data={
            "workout_title": "Legs", "workout_date": "2026-09-20", "workout_text": "Squat\n100, 6",
        }, follow_redirects=True).get_data(as_text=True)
        self.assertIn("Workout saved.", page)
        self.assertNotIn("successfully", page)
        page = self.client.post("/settings", data={"form_type": "bodyweight", "bodyweight": "77"},
                                follow_redirects=True).get_data(as_text=True)
        self.assertIn("Bodyweight updated.", page)

    def test_error_messages_skip_jargon(self):
        self._create_logged_in_user(username="plain_words")
        page = self.client.get("/workout/2026-02-30", follow_redirects=True).get_data(as_text=True)
        self.assertIn("That link doesn&#39;t point to a workout.", page)
        self.assertNotIn("Invalid date format", page)

    def test_messages_leave_room_for_their_close_button(self):
        # The app's .alert padding replaced Bootstrap's room for the ×, so long messages ran under it.
        self._create_logged_in_user(username="alert_user")
        page = self.client.get("/log").get_data(as_text=True)
        rules = re.findall(r"\.alert\.alert-dismissible\s*\{([^}]*)\}", page)
        self.assertTrue(rules)
        self.assertTrue(all("padding-right: 48px" in rule for rule in rules))

    def test_exports_give_every_logged_set_in_the_chosen_range(self):
        import csv
        import io
        import json

        user = self._create_logged_in_user(username="exporter")
        self.client.post("/log", data={"workout_text": "10/9/26 Push\nBench Press\n80 75, 8 10"})
        self.client.post("/log", data={"workout_text": "20/9/26 Legs\nSquat\n100, 5"})
        other = User(username="someone_else", role=UserRole.USER, is_verified=True)
        self.session.add(other)
        self.session.commit()
        self.session.add(WorkoutLog(user_id=other.id, date=datetime(2026, 9, 15), exercise="Secret Lift",
                                    top_weight=1, top_reps=1))
        self.session.commit()

        response = self.client.get("/export_csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=workout_history_exporter_", response.headers["Content-Disposition"])
        rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual([r["Exercise"] for r in rows], ["Squat", "Bench Press"])  # newest first
        self.assertEqual(rows[1]["Weights"], "80.0,75.0,75.0")
        self.assertEqual(rows[1]["Reps"], "8,10,10")
        self.assertEqual((rows[1]["Uses Bodyweight"], rows[1]["Bodyweight (kg)"]), ("no", "80.0"))

        body = json.loads(self.client.get("/export_json?start_date=2026-09-01&end_date=2026-09-12").get_data(as_text=True))
        self.assertEqual(body["user"], "exporter")
        self.assertEqual([w["date"] for w in body["workouts"]], ["2026-09-10"])
        self.assertEqual(body["workouts"][0]["entries"][0]["bodyweight"], 80.0)
        self.assertIn("uses_bodyweight", body["workouts"][0]["entries"][0])

        # A bodyweight exercise says so, so "10" reads as BW+10 kg rather than 10 kg.
        self.client.post("/log", data={"workout_text": "12/9/26 Pull\nPull Ups\nBW+10, 8"})
        body = json.loads(self.client.get("/export_json?start_date=2026-09-12&end_date=2026-09-12").get_data(as_text=True))
        entry = body["workouts"][0]["entries"][0]
        self.assertEqual((entry["exercise"], entry["uses_bodyweight"], entry["bodyweight"]), ("Pull Ups", True, 80.0))
        self.assertEqual(entry["sets_json"]["weights"][0], 10.0)
        self.assertFalse(entry["timed"])

        # A timed exercise says its reps are seconds.
        self.client.post("/log", data={"workout_text": "13/9/26 Core\nPlank - [30-60s]\n0, 45"})
        body = json.loads(self.client.get("/export_json?start_date=2026-09-13&end_date=2026-09-13").get_data(as_text=True))
        self.assertTrue(body["workouts"][0]["entries"][0]["timed"])
        rows = list(csv.DictReader(io.StringIO(self.client.get("/export_csv?start_date=2026-09-13&end_date=2026-09-13").get_data(as_text=True))))
        self.assertEqual(rows[0]["Timed"], "yes")
        self.assertNotIn("Secret Lift", json.dumps(body))

        # Nothing in range, or a bad range: back to the data page with a message.
        for query in ("start_date=2025-01-01&end_date=2025-01-31", "start_date=2026-09-20",
                      "start_date=2026-09-20&end_date=2026-09-01", "start_date=bad&end_date=2026-09-01"):
            response = self.client.get(f"/export_csv?{query}")
            self.assertEqual(response.status_code, 302, query)
            self.assertEqual(urlsplit(response.headers["Location"]).path, "/settings/data", query)

    def test_pages_are_not_framed_or_sniffed_and_cookies_stay_same_site(self):
        from config import Config

        response = self.client.get("/login")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(self.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertEqual(self.app.config["REMEMBER_COOKIE_SAMESITE"], "Lax")
        self.assertTrue(self.app.config["SESSION_COOKIE_HTTPONLY"])
        # Secure (HTTPS-only) where deployed; a local http run can still sign in.
        self.assertEqual(self.app.config["SESSION_COOKIE_SECURE"], Config.DEPLOYED)
        self.assertEqual(self.app.config["REMEMBER_COOKIE_SECURE"], Config.DEPLOYED)

        self._create_logged_in_user(username="cookie_user")
        cookie = self.client.get("/log").headers.get("Set-Cookie", "")
        if cookie:
            self.assertIn("SameSite=Lax", cookie)
            self.assertIn("HttpOnly", cookie)

    def test_stats_chart_is_described_for_screen_readers(self):
        self._create_logged_in_user(username="chart_reader")
        page = self.client.get("/stats").get_data(as_text=True)
        self.assertIn('<canvas id="progressChart" role="img" aria-label=', page)
        self.assertIn("document.getElementById('progressChart').setAttribute('aria-label'", page)
        # Consistency counts weeks from your first workout in the year you started.
        self.assertIn("const from = startedThisYear ? firstDay : win.start;", page)
        self.assertIn("workouts a week since ${", page)
        # Enter in the exercise search takes the first match and puts the list and keyboard away.
        self.assertIn("items[pick].click();", page)
        self.assertIn("event.target.blur();", page)

    def test_bodyweight_line_only_moves_the_setting_for_the_newest_workout(self):
        user = self._create_logged_in_user(username="bw_line_user")  # bodyweight 80

        def current():
            self.session.expire_all()
            return self.session.get(User, user.id).bodyweight

        def logged(day):
            return {log.bodyweight for log in self.session.query(WorkoutLog).filter(
                WorkoutLog.user_id == user.id, WorkoutLog.date >= datetime(2026, 9, day),
                WorkoutLog.date < datetime(2026, 9, day + 1))}

        self.client.post("/log", data={"workout_text": "20/9/26 Pull\nBody Weight - 78 kg\nPull Ups\nBW+5, 8"})
        self.assertEqual(current(), 78.0)
        self.assertEqual(logged(20), {78.0})

        # An older workout keeps its own bodyweight, but today's setting stays.
        self.client.post("/log", data={"workout_text": "5/9/26 Pull\nBody Weight - 70 kg\nPull Ups\nBW, 8"})
        self.assertEqual(current(), 78.0)
        self.assertEqual(logged(5), {70.0})

        # A typo isn't a bodyweight.
        self.client.post("/log", data={"workout_text": "25/9/26 Pull\nBody Weight - 7800 kg\nPull Ups\nBW, 9"})
        self.assertEqual(current(), 78.0)
        self.assertEqual(logged(25), {78.0})

        # Editing the old workout (the edit box has no bodyweight line) keeps its 70 kg.
        self.client.post("/workout/2026-09-05/edit", data={
            "workout_title": "Pull A", "workout_date": "2026-09-05", "workout_text": "Pull Ups\nBW, 10"})
        self.session.expire_all()
        self.assertEqual(logged(5), {70.0})
        self.assertEqual(current(), 78.0)

    def test_pages_are_gzipped_when_the_browser_asks(self):
        import gzip

        self._create_logged_in_user(username="gzip_user")
        plain = self.client.get("/log")
        self.assertNotIn("Content-Encoding", plain.headers)
        packed = self.client.get("/log", headers={"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual(packed.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", packed.headers["Vary"])
        self.assertEqual(gzip.decompress(packed.data), plain.data)
        self.assertLess(len(packed.data) * 3, len(plain.data))
        self.assertEqual(int(packed.headers["Content-Length"]), len(packed.data))

        # Files, tiny answers and images are left alone.
        script = self.client.get("/static/offline-sync.js", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", script.headers)
        script.close()
        tiny = self.client.get("/api/csrf-token", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", tiny.headers)

    def test_error_pages_say_what_happened(self):
        page = self.client.get("/no-such-page/really").get_data(as_text=True)
        self.assertIn("That page doesn&#39;t exist, or it has moved.", page)
        self.assertNotIn("Something went wrong. Please try again", page)

    def test_theme_is_set_before_the_page_is_drawn(self):
        # Light mode drew dark first and faded to light on every page when only the end of the page set it.
        page = self.client.get("/login").get_data(as_text=True)
        head = page.split("</head>", 1)[0]
        self.assertIn("document.documentElement.setAttribute('data-theme'", head)
        self.assertLess(head.index("data-theme"), head.index("<link"))

    def test_desktop_bar_fits_between_phone_and_desktop_widths(self):
        self._create_logged_in_user(username="tablet_user")
        page = self.client.get("/log").get_data(as_text=True)
        self.assertIn("@media (min-width: 576px) and (max-width: 991.98px)", page)
        # Icons only on the narrowest of these, words kept for screen readers (not display:none).
        narrow = page.split("@media (min-width: 576px) and (max-width: 767.98px)", 1)[1][:400]
        self.assertIn("clip: rect(0 0 0 0)", narrow)
        self.assertNotIn("display: none", narrow)

    def test_unsent_drafts_belong_to_one_account(self):
        # Someone else signing in on the same phone must not see your unsent workout.
        user = self._create_logged_in_user(username="draft_owner")
        self.assertIn(f"const DRAFT_KEY = 'wt-log-draft:{user.id}';", self.client.get("/log").get_data(as_text=True))
        self.assertIn(f"const DRAFT_KEY = 'wt-custom-draft:{user.id}';", self.client.get("/retrieve/custom").get_data(as_text=True))

    def test_log_check_points_out_an_exercise_written_twice(self):
        self._create_logged_in_user(username="twice_user")
        text = "20/9/26 Legs\nSquat\n100, 5\n\nLeg Press\n200, 10\n\nsquat\n80, 8"
        body = self.client.post("/log/preview", data={"workout_text": text}).get_json()
        states = [(row["name"], row["state"], row["note"]) for row in body["exercises"]]
        self.assertEqual(states[0][1], "new")
        self.assertEqual(states[2][1], "twice")
        self.assertEqual(states[2][2], "Also at no. 1: saved as a second entry")
        self.assertTrue(body["ok"])  # a note, not a blocker

    def test_a_workout_with_only_a_date_on_the_first_line(self):
        user = self._create_logged_in_user(username="date_only_user")
        body = self.client.post("/log/preview", data={"workout_text": "2026-09-20\nBench Press\n60, 8"}).get_json()
        self.assertEqual((body["date_str"], body["title"]), ("2026-09-20", "Workout"))
        self.client.post("/log", data={"workout_text": "2026-09-20\nBench Press\n60, 8"})
        self.assertEqual(self.session.query(WorkoutLog).filter_by(user_id=user.id).one().date.date().isoformat(), "2026-09-20")
        self.assertEqual(self.client.get("/workout/2026-09-20").status_code, 200)

    def test_a_date_that_does_not_exist_is_not_saved_under_today(self):
        user = self._create_logged_in_user(username="bad_date_user")
        body = self.client.post("/log/preview", data={"workout_text": "31/9 Push\nBench Press\n60, 8"}).get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["errors"][0]["message"], "Line 1: “31/9” isn't a real date. Check the day and month.")
        self.assertTrue(body["date_invalid"])
        response = self.client.post("/log", data={"workout_text": "31/9 Push\nBench Press\n60, 8"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.session.query(WorkoutLog).filter_by(user_id=user.id).count(), 0)

    def test_timed_sets_written_as_times(self):
        # "Plank\n60s, 45s" used to be skipped ("couldn't read"), and "3 x 60s" was 3 kg for 60.
        user = self._create_logged_in_user(username="times_user")
        text = "20/9/26 Core\nPlank\n60s, 45s\n\nDead Hang\n3 x 40s\n\nWall Sit\n1:30 1:00"
        body = self.client.post("/log/preview", data={"workout_text": text}).get_json()
        labels = {row["name"]: row["sets_label"] for row in body["exercises"]}
        # Only times written: the load is bodyweight, as with "BW, 60 45".
        self.assertEqual(labels["Plank"], "BW×60s · BW×45s · BW×45s")
        self.assertEqual(labels["Dead Hang"], "BW×40s · BW×40s · BW×40s")
        self.assertEqual(labels["Wall Sit"], "BW×90s · BW×60s · BW×60s")

        self.client.post("/log", data={"workout_text": text})
        logs = {log.exercise: log for log in self.session.query(WorkoutLog).filter_by(user_id=user.id)}
        self.assertEqual(logs["Wall Sit"].sets_json["reps"], [90, 60, 60])
        self.assertTrue(logs["Wall Sit"].uses_bodyweight)
        self.assertGreater(logs["Wall Sit"].estimated_1rm or 0, 0)  # scored at bodyweight, so it charts
        page = self.client.get("/workout/2026-09-20").get_data(as_text=True)
        self.assertIn("90s", page)

    def test_retrieve_placeholder_sets_left_as_they_are_are_not_saved(self):
        # Retrieve writes "1, 1" under an exercise with no history; pasted back untouched it
        # was saved as real 1 kg x 1 sets.
        user = self._create_logged_in_user(username="placeholder_user")
        text = ("20/9/26 - Session 4 - Legs\n\nLeg Press - [10–20]\n1, 1\n\n"
                "Pull Ups\nbw/4, 1\n\nLeg Extension - [2, 12–20]\n60, 12")
        body = self.client.post("/log/preview", data={"workout_text": text}).get_json()
        states = [(row["name"], row["state"]) for row in body["exercises"]]
        self.assertEqual(states[:2], [("Leg Press", "skip"), ("Pull Ups", "skip")])
        self.assertNotEqual(states[2][1], "skip")
        self.assertTrue(body["ok"])
        self.assertIn("Retrieve's 1, 1", body["exercises"][0]["note"])

        self.client.post("/log", data={"workout_text": text})
        saved = [row.exercise for row in self.session.query(WorkoutLog).filter_by(user_id=user.id)]
        self.assertEqual(saved, ["Leg Extension"])

        # All still placeholders: nothing to save, and it says so.
        body = self.client.post("/log/preview", data={"workout_text": "21/9/26 Legs\nLeg Press\n1, 1"}).get_json()
        self.assertFalse(body["ok"])

    def test_log_check_suggests_the_name_behind_a_superset_label(self):
        user = self._create_logged_in_user(username="superset_user")
        handle_workout_log(self.session, user, {
            "date": datetime(2026, 9, 20, 18), "workout_name": "Legs",
            "exercises": [{"name": "Zercher Squat", "exercise_string": "Zercher Squat\n100, 5",
                           "weights": [100.0] * 3, "reps": [5] * 3, "valid": True}],
        })
        self.session.commit()
        body = self.client.post("/log/preview", data={"workout_text": "29/9/26 Legs\nA1 Zercher Squat\n100, 5"}).get_json()
        row = body["exercises"][0]
        self.assertEqual((row["state"], row["suggestion"], row["fix_line"]), ("suggest", "Zercher Squat", "Zercher Squat"))
        # The fix button's name says what it does, beyond its visible "Use it".
        self.assertIn('aria-label="Use it: ${esc(ex.suggestion)} on line ${ex.line}"', self.client.get("/log").get_data(as_text=True))

    def test_log_check_says_when_numbers_could_not_be_read(self):
        self._create_logged_in_user(username="unread_user")
        text = "20/9/26 Legs\nSquat\n100/5, 105/4\n\nPlank"
        body = self.client.post("/log/preview", data={"workout_text": text}).get_json()
        notes = [(row["state"], row["note"]) for row in body["exercises"]]
        self.assertEqual(notes, [("skip", "Couldn't read the sets, so this line won't be saved"),
                                 ("skip", "No numbers, so this line won't be saved")])

    def test_shared_workout_page_shows_medals_preview_and_invite_when_logged_out(self):
        from itsdangerous import URLSafeSerializer

        user = self._create_logged_in_user(username="share_owner")
        exercise = "Flat Dumbbell Press"
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Push",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press\n30 30 30, 8 8 8",
                sets_json={"weights": [30, 30, 30], "reps": [8, 8, 8]},
                bodyweight=user.bodyweight,
            )
        )
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 10, 9, 0, 0),
                workout_name="Push Day",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press\n32.5 30 30, 8 8 8",
                sets_json={"weights": [32.5, 30, 30], "reps": [8, 8, 8]},
                bodyweight=user.bodyweight,
            )
        )
        self.session.commit()

        token = URLSafeSerializer(self.app.config.get("SECRET_KEY", "workout-share")).dumps(
            {"user_id": user.id, "date": "2026-01-10"}
        )
        visitor = self.app.test_client()  # a friend opening the link, not logged in
        response = visitor.get(f"/share/{token}")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Push Day", page)
        self.assertIn('property="og:title"', page)
        self.assertIn("1 new personal best", page)
        self.assertIn("🥇", page)
        self.assertIn("32.5×8", page)
        self.assertIn("Start free", page)
        self.assertNotIn("Est. 1RM", page)
        # "Copy" text spells every set out for newcomers instead of the app shorthand.
        self.assertIn("32.5 kg × 8, 30 kg × 8, 30 kg × 8", page)

        expired = visitor.get("/share/not-a-real-token")
        self.assertEqual(expired.status_code, 200)
        self.assertIn("This link has expired", expired.get_data(as_text=True))

    def test_shared_workout_page_shows_owner_profile_photo(self):
        from itsdangerous import URLSafeSerializer

        user = self._create_logged_in_user(username="share_photo_owner")
        # The login helper leaves `user` detached, so set the photo on a fresh copy.
        self.session.get(User, user.id).profile_image = "uploads/avatars/share_photo_owner.png"
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 10, 9, 0, 0),
                workout_name="Push Day",
                exercise="Flat Dumbbell Press",
                exercise_string="Flat Dumbbell Press\n30 30, 8 8",
                sets_json={"weights": [30, 30], "reps": [8, 8]},
                bodyweight=user.bodyweight,
            )
        )
        self.session.commit()

        token = URLSafeSerializer(self.app.config.get("SECRET_KEY", "workout-share")).dumps(
            {"user_id": user.id, "date": "2026-01-10"}
        )
        page = self.app.test_client().get(f"/share/{token}").get_data(as_text=True)

        # Photo from the public avatar store, with the initial kept as a fallback.
        self.assertIn('class="sw-avatar"', page)
        self.assertRegex(page, r'<img src="[^"]*avatars/share_photo_owner\.png"')
        self.assertIn('class="sw-initial"', page)

    def test_shortcut_pick_url_is_available_to_regular_users(self):
        self._create_logged_in_user(username="shortcut_pick_user")

        response = self.client.get("/shortcut/pick")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertTrue(data.get("ok"))
        shortcut_url = data.get("url") or ""
        self.assertIn("/shortcut/pick/", shortcut_url)
        self.assertEqual(data.get("query_param"), "key")

        token_path = urlsplit(shortcut_url).path
        token_response = self.client.get(token_path)
        self.assertEqual(token_response.status_code, 400)
        self.assertIn("Missing key", token_response.get_data(as_text=True))

    def test_shortcut_replies_name_the_server_so_shortcuts_can_fall_back(self):
        self._create_logged_in_user(username="shortcut_fallback_user")
        pick_path = urlsplit(self.client.get("/shortcut/pick").get_json()["url"]).path
        log_path = urlsplit(self.client.get("/shortcut/log").get_json()["url"]).path

        # Plain text stays the default for existing Shortcuts.
        self.assertEqual(self.client.get(pick_path).mimetype, "text/plain")

        pick = self.client.get(f"{pick_path}?format=json").get_json()
        self.assertEqual(pick["server"], "Local")
        self.assertFalse(pick["ok"])
        self.assertIn("Missing key", pick["error"])

        log = self.client.post(log_path, data={"workout_text": ""}).get_json()
        self.assertEqual(log["server"], "Local")
        self.assertFalse(log["ok"])

        bad_token = self.client.post("/shortcut/log/not-a-token").get_json()
        self.assertEqual(bad_token["server"], "Local")

    def test_apple_shortcuts_page_gives_one_key_that_works_for_both_shortcuts(self):
        self._create_logged_in_user(username="shortcut_key_user")

        page = self.client.get("/shortcut/urls").get_data(as_text=True)
        self.assertIn("Apple Shortcuts", page)
        self.assertIn("shortcuts/Log%20Workout.shortcut", page)
        self.assertIn("shortcuts/Get%20Workout.shortcut", page)
        self.assertIn("Workout Logs folder", page)  # where the shortcuts keep workout notes
        key = re.search(r'value="([^"]+)"[^>]*aria-label="Shortcut key"', page).group(1)

        log = self.client.post(f"/shortcut/log/{key}", data={"workout_text": ""}).get_json()
        self.assertEqual(log["error"], "Please enter workout data.")  # key accepted, note was empty
        pick = self.client.get(f"/shortcut/pick/{key}?format=json").get_json()
        self.assertIn("Missing key", pick["error"])  # key accepted, no session named

        for name in ("Log Workout", "Get Workout"):
            download = self.client.get(f"/static/shortcuts/{name}.shortcut")
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.data[:4], b"AEA1")  # signed Shortcuts file
            download.close()

    def _plan_owner_with_plan(self):
        owner = User(username="plan_owner", email="owner@example.com", role=UserRole.ADMIN, is_verified=True)
        self.session.add(owner)
        self.session.flush()
        owner_id = int(owner.id)
        self.session.add(Plan(user_id=owner_id, text_content="Session 1 - Owner Push\nBench Press - [3, 6-8]"))
        self.session.commit()
        return owner_id

    def test_new_accounts_start_with_a_copy_of_the_admin_rep_ranges(self):
        from models import RepRange, _seed_user_data
        owner = User(username="range_owner", role=UserRole.ADMIN, is_verified=True)
        self.session.add(owner)
        self.session.flush()
        self.session.add(RepRange(user_id=owner.id, text_content="Bench Press: 5-8\nPull-Ups: 6-10"))
        self.session.commit()

        user = User(username="range_newcomer", role=UserRole.USER, is_verified=True)
        self.session.add(user)
        self.session.flush()
        _seed_user_data(self.session, user)
        self.session.commit()
        copy = self.session.query(RepRange).filter_by(user_id=user.id).one()
        self.assertEqual(copy.text_content, "Bench Press: 5-8\nPull-Ups: 6-10")

        # A copy, not a link: the admin's later changes don't rewrite it.
        self.session.query(RepRange).filter_by(user_id=owner.id).one().text_content = "Bench Press: 3-5"
        self.session.commit()
        self.assertEqual(self.session.query(RepRange).filter_by(user_id=user.id).one().text_content,
                         "Bench Press: 5-8\nPull-Ups: 6-10")

    def test_new_accounts_follow_the_admin_plan_and_rep_ranges(self):
        user = User(username="brand_new", role=UserRole.USER, is_verified=True)
        self.session.add(user)
        self.session.commit()
        self.assertTrue(user.follow_admin_plan)
        self.assertTrue(user.follow_admin_exercises)

    def test_another_admin_can_follow_the_owner_plan_everywhere(self):
        self._plan_owner_with_plan()
        friend = self._create_logged_in_user(username="friend_admin", follow_admin=True)
        friend.role = UserRole.ADMIN
        self.session.commit()

        # The switch is there for them, and it's on.
        page = self.client.get("/set_plan").get_data(as_text=True)
        self.assertIn('name="follow_admin_plan" value="0"', page)
        self.assertIn('st-switch is-on', page)
        self.assertIn('name="follow_admin_exercises"', self.client.get("/set_exercises").get_data(as_text=True))

        # And the shortcut gets the owner's sessions, not the built-in plan.
        pick_path = urlsplit(self.client.get("/shortcut/pick").get_json()["url"]).path
        self.assertEqual(self.client.get(f"{pick_path}?list=1").get_json()["sessions"], ["Session 1 - Owner Push"])

    def test_rep_ranges_save_as_clean_lines_and_stay_on_the_page(self):
        from models import RepRange

        user = self._create_logged_in_user(username="rep_editor")
        response = self.client.post("/set_exercises", data={
            "form_type": "save_exercises",
            "rep_text": "bench press 6-10\nDips: 3x6-12\nbench press: 5 - 8\nPlank",
        })
        self.assertEqual(urlsplit(response.headers["Location"]).path, "/set_exercises")
        saved = self.session.query(RepRange).filter_by(user_id=user.id).one().text_content
        # Plank has no range yet: it's kept, without one, for the page to point out.
        self.assertEqual(saved, "Bench Press: 5–8\nDips: 3, 6–12\nPlank:")

        # The page lists them as rows to edit in place, each with the muscle group the
        # Custom workout page would put it in.
        page = self.client.get("/set_exercises").get_data(as_text=True)
        self.assertIn('id="rr-data">[["Bench Press", "5\\u20138", "Chest"], ["Dips", "3, 6\\u201312", "Chest"], ["Plank", "", ', page)
        self.assertIn('id="rr-missing"', page)

    def test_rep_ranges_are_not_wiped_when_the_page_script_never_ran(self):
        from models import RepRange

        user = self._create_logged_in_user(username="rep_keeper")
        self.client.post("/set_exercises", data={"form_type": "save_exercises", "rep_text": "Bench Press: 5-8"})

        # The rows are drawn and rep_text is filled by the page's script; without it Save sends nothing.
        response = self.client.post("/set_exercises", data={"form_type": "save_exercises", "rep_text": ""})
        self.assertEqual(urlsplit(response.headers["Location"]).path, "/set_exercises")
        self.assertEqual(self.session.query(RepRange).filter_by(user_id=user.id).one().text_content, "Bench Press: 5–8")

        # Removing every range on purpose still works: the script marks the form it filled.
        self.client.post("/set_exercises", data={"form_type": "save_exercises", "rep_text": "", "rep_text_ready": "1"})
        self.session.expire_all()
        self.assertEqual(self.session.query(RepRange).filter_by(user_id=user.id).one().text_content, "")

    def test_saving_the_plan_keeps_it_and_stays_on_the_page(self):
        from models import Plan

        user = self._create_logged_in_user(username="plan_writer", follow_admin=True)
        response = self.client.post("/set_plan", data={"plan_text": "  Day 1 - Push\nBench Press - [3, 6-8]\n  "})
        self.assertEqual(urlsplit(response.headers["Location"]).path, "/set_plan")
        self.session.expire_all()
        self.assertEqual(self.session.query(Plan).filter_by(user_id=user.id).one().text_content,
                         "Day 1 - Push\nBench Press - [3, 6-8]")
        # Writing your own plan stops following the admin's.
        self.assertFalse(self.session.get(User, user.id).follow_admin_plan)
        page = self.client.get("/set_plan").get_data(as_text=True)
        self.assertIn("Workout plan saved.", page)
        self.assertIn("Bench Press - [3, 6-8]", page)

    def test_plan_owner_has_no_follow_switch(self):
        owner_id = self._plan_owner_with_plan()
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(owner_id)
            sess["_fresh"] = True
        page = self.client.get("/set_plan").get_data(as_text=True)
        self.assertNotIn('name="follow_admin_plan"', page)
        self.assertIn("Owner Push", page)

    def test_owner_plan_equal_to_the_built_in_plan_is_still_followed(self):
        from list_of_exercise import DEFAULT_PLAN
        owner = User(username="plan_owner", role=UserRole.ADMIN, is_verified=True)
        other_admin = User(username="other_admin", role=UserRole.ADMIN, is_verified=True)
        self.session.add_all([owner, other_admin])
        self.session.flush()
        self.session.add(Plan(user_id=owner.id, text_content=DEFAULT_PLAN))
        self.session.add(Plan(user_id=other_admin.id, text_content="Session 1 - Not This One\nSquat"))
        self.session.commit()
        self._create_logged_in_user(username="follower", follow_admin=True)

        pick_path = urlsplit(self.client.get("/shortcut/pick").get_json()["url"]).path
        sessions = self.client.get(f"{pick_path}?list=1").get_json()["sessions"]
        self.assertEqual(sessions[0], "Session 1 - Chest & Biceps")

    def test_not_following_without_own_plan_gets_the_built_in_plan(self):
        from list_of_exercise import DEFAULT_PLAN, PREVIOUS_DEFAULT_PLAN
        self._plan_owner_with_plan()
        user = self._create_logged_in_user(username="own_way")
        # An untouched copy of the old built-in plan counts as no plan of their own.
        self.session.add(Plan(user_id=user.id, text_content=PREVIOUS_DEFAULT_PLAN))
        self.session.commit()

        pick_path = urlsplit(self.client.get("/shortcut/pick").get_json()["url"]).path
        sessions = self.client.get(f"{pick_path}?list=1").get_json()["sessions"]
        self.assertEqual(len(sessions), 16)
        self.assertEqual(sessions[0], "Session 1 - Chest & Biceps")
        # The editor starts from the built-in plan, ready to change.
        self.assertIn("Hanging Leg Raises", self.client.get("/set_plan").get_data(as_text=True))
        self.assertIn("Session 16", DEFAULT_PLAN)

    def test_shortcut_pick_lists_the_users_own_sessions(self):
        user = self._create_logged_in_user(username="shortcut_list_user")
        self.session.add(Plan(user_id=user.id, text_content="Session 1 - Push\nBench Press - [3, 6-8]\n\nSession 2 - Pull\nPull Ups - [3, 6-8]"))
        self.session.commit()
        pick_path = urlsplit(self.client.get("/shortcut/pick").get_json()["url"]).path

        data = self.client.get(f"{pick_path}?list=1").get_json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["server"], "Local")
        self.assertEqual(data["sessions"], ["Session 1 - Push", "Session 2 - Pull"])

        # Each listed name works as the key for fetching that session.
        picked = self.client.get(pick_path, query_string={"format": "json", "key": data["sessions"][1]}).get_json()
        self.assertTrue(picked["ok"], picked)
        self.assertIn("Pull Ups", picked["text"])

    def test_retrieve_day_that_is_not_in_the_plan_says_so(self):
        # It showed "Day 'Session 999' not found in plan." as the workout, with Copy and Share.
        self._create_logged_in_user(username="stale_link")
        response = self.client.get("/retrieve/final/Session/999", follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn("Session 999 isn&#39;t in your plan any more.", page)
        self.assertNotIn("not found in plan", page)
        self.assertEqual(self.client.get("/retrieve/final/Session/1").status_code, 200)

    def test_shortcut_pick_by_number_with_ten_or_more_sessions(self):
        # "1" was ambiguous (Session 1, 10, 11...) and "0" picked Session 10.
        from list_of_exercise import DEFAULT_PLAN
        user = self._create_logged_in_user(username="numbers_user")
        self.session.add(Plan(user_id=user.id, text_content=DEFAULT_PLAN))
        self.session.commit()
        pick_path = urlsplit(self.client.get("/shortcut/pick").get_json()["url"]).path
        for key, title in (("1", "Session 1 - Chest & Biceps"), ("10", "Session 10"), ("s1", "Session 1 - Chest & Biceps")):
            picked = self.client.get(pick_path, query_string={"format": "json", "key": key}).get_json()
            self.assertTrue(picked["ok"], (key, picked))
            self.assertIn(title, picked["text"], key)
        for key in ("0", "17"):
            self.assertFalse(self.client.get(pick_path, query_string={"format": "json", "key": key}).get_json()["ok"], key)

    def test_shortcut_key_problems_explain_themselves_to_the_shortcut(self):
        # Empty key (the "paste your key" question was skipped): the app's JSON, not a
        # "not found" web page, so the shortcut shows the message instead of "not reachable".
        for path in ("/shortcut/pick/?list=1", "/shortcut/log/"):
            data = self.client.get(path).get_json()
            self.assertIsNotNone(data, path)
            self.assertEqual(data["server"], "Local")
            self.assertIn("shortcut key is missing", data["error"])
            self.assertIn("Apple Shortcuts", data["error"])

        wrong = self.client.get("/shortcut/pick/not-a-key?list=1").get_json()
        self.assertIn("shortcut key isn't valid", wrong["error"])
        self.assertIn("shortcut key isn't valid", self.client.post("/shortcut/log/not-a-key").get_json()["error"])
        # Old plain-text shortcuts keep their old reply.
        self.assertEqual(self.client.get("/shortcut/pick/not-a-key").get_data(as_text=True), "Invalid shortcut token.")
        # Other missing pages are unchanged.
        self.assertIn("text/html", self.client.get("/no-such-page").content_type)

    def test_shortcut_log_accepts_rich_text_notes(self):
        self._create_logged_in_user(username="shortcut_rich_text_user")
        log_path = urlsplit(self.client.get("/shortcut/log").get_json()["url"]).path

        # Apple Notes rich text: its own line breaks and non-breaking spaces.
        note = "12/01 Chest Day\u2028Bench Press\u00a0100x5\u2028Pec Fly 15 15"
        data = self.client.post(log_path, data={"workout_text": note}).get_json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["exercise_count"], 2)

        # The note sent as an HTML file instead of a form field.
        page = b"<div><b>13/01 Back Day</b></div><div>Pull Ups -35x5</div>"
        data = self.client.post(
            log_path,
            data={"workout_text": (io.BytesIO(page), "note.html")},
            content_type="multipart/form-data",
        ).get_json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["input_source"], "file")

    def test_custom_retrieve_uses_selected_exercises_in_selection_order(self):
        user = self._create_logged_in_user(username="custom_retrieve_user")
        self.session.add(
            Plan(
                user_id=user.id,
                text_content="Custom Focus 1\nCustom Lift - [4, 6-8]",
            )
        )
        self.session.commit()

        selection_page = self.client.get("/retrieve/custom")
        self.assertEqual(selection_page.status_code, 200)
        selection_html = selection_page.get_data(as_text=True)
        self.assertIn("Custom Lift", selection_html)
        self.assertIn('id="crGroups"', selection_html)
        self.assertIn('id="crPicked"', selection_html)
        self.assertIn('id="crGet"', selection_html)

        response = self.client.post(
            "/retrieve/custom",
            data={
                "exercise": [
                    normalize_exercise_name("Barbell Curl"),
                    normalize_exercise_name("Custom Lift"),
                ],
            },
        )

        # The plan is its own page: refreshing it doesn't resend the form or count the pick again.
        self.assertEqual(response.status_code, 302)
        plan_url = response.headers["Location"]
        self.assertEqual(urlsplit(plan_url).path, "/retrieve/custom/plan")
        response = self.client.get(plan_url)
        self.assertEqual(response.status_code, 200)
        self.client.get(plan_url)
        page = response.get_data(as_text=True)
        self.assertIn("Custom Workout", page)
        # With no sets chosen on the page, the plan's own "[4, 6-8]" stands.
        self.assertIn("Custom Lift - [4, 6-8]", page)
        self.assertIn("2 exercises", page)
        self.assertLess(page.index("Barbell Curl"), page.index("Custom Lift - [4, 6-8]"))
        self.assertEqual(
            self.session.query(CustomRetrievalEvent)
            .filter_by(user_id=user.id)
            .count(),
            2,
        )

    def test_custom_plan_address_with_unknown_exercises_goes_back_to_the_picker(self):
        self._create_logged_in_user(username="custom_plan_bad_link")
        self.session.add(Plan(user_id=self.session.query(User).filter_by(username="custom_plan_bad_link").one().id,
                              text_content="Day 1\nCustom Lift - [4, 6-8]"))
        self.session.commit()
        for query in ("", "e=not-an-exercise", f"e={normalize_exercise_name('Custom Lift')}&s=99"):
            response = self.client.get(f"/retrieve/custom/plan?{query}")
            self.assertEqual(response.status_code, 302, query)
            self.assertTrue(response.headers["Location"].endswith("/retrieve/custom"), query)

    def test_custom_retrieve_review_page_now_lives_on_the_picker(self):
        self._create_logged_in_user(username="custom_retrieve_review_user")
        for method in (self.client.get, self.client.post):
            response = method("/retrieve/custom/review")
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["Location"].endswith("/retrieve/custom"))

    def test_custom_retrieve_two_set_override_replaces_plan_set_target(self):
        user = self._create_logged_in_user(username="custom_retrieve_two_sets_user")
        self.session.add(
            Plan(
                user_id=user.id,
                text_content="Custom Focus 1\nCustom Lift - [4, 6-8]",
            )
        )
        self.session.commit()
        custom_lift_key = normalize_exercise_name("Custom Lift")

        response = self.client.post(
            "/retrieve/custom",
            data={
                "exercise": [custom_lift_key],
                "two_set_exercise": [custom_lift_key],
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Custom Lift - [2, 6-8]", response.get_data(as_text=True))

    def test_custom_retrieve_sort_preference_is_saved_per_user(self):
        user = self._create_logged_in_user(username="custom_retrieve_sort_user")

        response = self.client.post(
            "/retrieve/custom/sort-preference",
            data={"sort_mode": "alpha_desc"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "sort_mode": "alpha_desc"})
        preference = self.session.query(CustomRetrievalPreference).filter_by(user_id=user.id).one()
        self.assertEqual(preference.sort_mode, "alpha_desc")

        invalid_response = self.client.post(
            "/retrieve/custom/sort-preference",
            data={"sort_mode": "unknown"},
        )
        self.assertEqual(invalid_response.status_code, 400)

    def test_custom_retrieve_rejects_empty_selection(self):
        self._create_logged_in_user(username="custom_retrieve_empty_user")

        response = self.client.post("/retrieve/custom")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/retrieve/custom"))

    def test_settings_shows_shortcut_urls_for_regular_users(self):
        self._create_logged_in_user(username="shortcut_settings_user")

        # Settings is a hub; shortcut URLs live on the Integrations page.
        hub = self.client.get("/settings")
        self.assertEqual(hub.status_code, 200)
        self.assertIn('href="/settings/integrations"', hub.get_data(as_text=True))

        response = self.client.get("/settings/integrations")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Apple Shortcuts", page)
        self.assertNotIn("Shortcut Retrieve URL", page)

    def test_more_settings_shows_bodyweight_exercise_controls(self):
        self._create_logged_in_user(username="more_settings_user")

        response = self.client.get("/settings/more")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Bodyweight exercises", page)
        self.assertIn("Crunches A", page)

    def test_bodyweight_log_uses_offsets_for_saved_strength(self):
        user = self._create_logged_in_user(username="bw_offset_user")
        user.bodyweight = 80.0
        parsed = {
            "date": datetime(2026, 9, 6),
            "workout_name": "Core",
            "exercises": [
                {
                    "name": "Crunches A",
                    "exercise_string": "Crunches A\n2.5 1, 14 21",
                    "weights": [2.5, 1.0],
                    "reps": [14, 21],
                    "valid": True,
                }
            ],
        }

        handle_workout_log(self.session, user, parsed)
        self.session.commit()

        log = self.session.query(WorkoutLog).filter_by(user_id=user.id, exercise="Crunches A").one()
        self.assertTrue(log.uses_bodyweight)
        self.assertEqual(log.sets_json["weights"][0], 2.5)
        self.assertGreater(log.estimated_1rm, 120)

    def test_explicit_bw_token_auto_selects_bodyweight_exercise(self):
        user = self._create_logged_in_user(username="bw_auto_user")
        parsed = {
            "date": datetime(2026, 9, 6),
            "workout_name": "Core",
            "exercises": [
                {
                    "name": "Cable Core Raise",
                    "exercise_string": "Cable Core Raise\nBW+3, 10",
                    "weights": [3.0],
                    "reps": [10],
                    "valid": True,
                }
            ],
        }

        handle_workout_log(self.session, user, parsed)
        self.session.commit()

        pref = self.session.query(BodyweightExercisePreference).filter_by(
            user_id=user.id,
            exercise_key=bodyweight_exercise_key("Cable Core Raise"),
        ).one()
        self.assertTrue(pref.is_bodyweight)
        self.assertEqual(pref.source, "auto")

    def test_bodyweight_parser_accepts_uppercase_bw_and_bodyweight(self):
        bw_result = workout_parser(
            "06/09 Core\nCable Core Raise\nBW+3, 10",
            bodyweight=80,
            preserve_bodyweight_offsets=True,
        )
        bodyweight_result = workout_parser(
            "06/09 Core\nCable Core Raise\nbodyweight, 10",
            bodyweight=80,
            preserve_bodyweight_offsets=True,
        )

        self.assertEqual(bw_result["exercises"][0]["weights"], [3.0, 3.0, 3.0])
        self.assertEqual(bodyweight_result["exercises"][0]["weights"], [0.0, 0.0, 0.0])

    def test_deselect_bodyweight_exercise_requires_history_resolution(self):
        user = self._create_logged_in_user(username="bw_deselect_user")
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 9, 1),
                workout_name="Core",
                exercise="Crunches A",
                exercise_string="Crunches A\nBW+2, 15",
                sets_json={"weights": [2.0], "reps": [15]},
                bodyweight=user.bodyweight,
                uses_bodyweight=True,
                estimated_1rm=123.0,
            )
        )
        self.session.commit()

        response = self.client.post(
            "/settings/more",
            data={
                "form_type": "bodyweight_exercise",
                "exercise_name": "Crunches A",
                "is_bodyweight": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("It already has bodyweight logs", page)
        self.assertTrue(
            self.session.query(WorkoutLog).filter_by(exercise="Crunches A").one().uses_bodyweight
        )

    def test_profile_photo_upload_writes_to_r2_when_configured(self):
        user = self._create_logged_in_user(username="avatar_upload_user")
        image_bytes = BytesIO()
        Image.new("RGB", (32, 32), "red").save(image_bytes, format="PNG")
        image_bytes.seek(0)
        s3 = Mock()

        with patch("workout_tracker.routes.auth.has_r2_profile_image_storage", return_value=True), \
             patch("workout_tracker.routes.auth.get_r2_profile_image_client", return_value=s3), \
             patch("workout_tracker.routes.auth.get_r2_bucket_name", return_value="workout-tracker-avatars"):
            response = self.client.post(
                "/settings",
                data={
                    "form_type": "profile_photo",
                    "profile_image": (image_bytes, "avatar.png"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        s3.put_object.assert_called_once()
        put_kwargs = s3.put_object.call_args.kwargs
        self.assertEqual(put_kwargs["Bucket"], "workout-tracker-avatars")
        self.assertRegex(put_kwargs["Key"], rf"^avatars/user_{user.id}_[0-9a-f]{{8}}\.png$")
        self.assertEqual(put_kwargs["ContentType"], "image/png")
        stored_user = self.session.query(User).filter_by(id=user.id).one()
        self.assertEqual(stored_user.profile_image, put_kwargs["Key"])

    def test_deleting_an_account_removes_its_photo_too(self):
        # The photo lives in storage at a public address; it outlived the account.
        admin = self._create_logged_in_user(username="photo_admin")
        self.session.query(User).filter_by(id=admin.id).update({"role": UserRole.ADMIN})
        target = User(username="leaving", email="leaving@example.com", is_verified=True,
                      profile_image="avatars/user_99_abcd1234.png")
        self.session.add(target)
        self.session.commit()
        with patch("workout_tracker.routes.admin.delete_profile_image") as delete_photo, \
             patch("workout_tracker.routes.admin.email_queue"), \
             patch("services.admin.Session", self.session):
            self.client.post("/admin/delete-user", data={"user_id": target.id, "deletion_reason": "Asked to leave"})
        delete_photo.assert_called_once_with("avatars/user_99_abcd1234.png")
        self.assertIsNone(self.session.query(User).filter_by(username="leaving").first())

    def test_delete_profile_image_removes_a_local_photo(self):
        import os
        import tempfile
        from utils import profile_images

        path = os.path.join(tempfile.mkdtemp(), "user_1_abcd1234.png")
        with open(path, "wb") as f:
            f.write(b"png")
        with patch("utils.profile_images.get_local_profile_image_path", return_value=path):
            profile_images.delete_profile_image("avatars/user_1_abcd1234.png")
        self.assertFalse(os.path.exists(path))
        profile_images.delete_profile_image(None)  # nothing to do

    def test_oversized_uploads_are_refused_politely(self):
        user = self._create_logged_in_user(username="big_upload_user")
        # A small file that unpacks into a 48-megapixel image isn't decoded.
        image_bytes = BytesIO()
        Image.new("1", (8000, 6000)).save(image_bytes, format="PNG")
        image_bytes.seek(0)
        s3 = Mock()
        with patch("workout_tracker.routes.auth.has_r2_profile_image_storage", return_value=True), \
             patch("workout_tracker.routes.auth.get_r2_profile_image_client", return_value=s3):
            response = self.client.post("/settings", data={"form_type": "profile_photo",
                                                           "profile_image": (image_bytes, "huge.png")},
                                        content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("That photo is too large", response.get_data(as_text=True))
        s3.put_object.assert_not_called()
        self.assertIsNone(self.session.query(User).filter_by(id=user.id).one().profile_image)

        # A request over the limit gets a page that says so, not a bare error.
        too_big = self.client.post("/settings", data={"form_type": "profile", "full_name": "x" * (17 * 1024 * 1024)})
        self.assertEqual(too_big.status_code, 413)
        self.assertIn("That file is too large", too_big.get_data(as_text=True))

    def test_profile_photo_reupload_gets_new_url_and_deletes_old_photo(self):
        user = self._create_logged_in_user(username="avatar_reupload_user")
        self.session.get(User, user.id).profile_image = f"avatars/user_{user.id}.png"
        self.session.commit()
        image_bytes = BytesIO()
        Image.new("RGB", (32, 32), "blue").save(image_bytes, format="PNG")
        image_bytes.seek(0)
        s3 = Mock()

        with patch("workout_tracker.routes.auth.has_r2_profile_image_storage", return_value=True), \
             patch("workout_tracker.routes.auth.get_r2_profile_image_client", return_value=s3), \
             patch("workout_tracker.routes.auth.get_r2_bucket_name", return_value="workout-tracker-avatars"):
            self.client.post(
                "/settings",
                data={
                    "form_type": "profile_photo",
                    "profile_image": (image_bytes, "avatar.png"),
                },
                content_type="multipart/form-data",
            )

        new_key = s3.put_object.call_args.kwargs["Key"]
        self.assertNotEqual(new_key, f"avatars/user_{user.id}.png")
        s3.delete_object.assert_called_once_with(
            Bucket="workout-tracker-avatars",
            Key=f"avatars/user_{user.id}.png",
        )

    def test_r2_client_uses_configured_endpoint_credentials_region_and_bucket(self):
        s3 = object()

        boto3 = Mock()
        boto3.client.return_value = s3

        with patch.dict(
            os.environ,
            {
                "R2_ACCESS_KEY_ID": "test-access-key",
                "R2_SECRET_ACCESS_KEY": "test-secret-key",
                "R2_BUCKET_NAME": "workout-tracker-avatars",
                "R2_ACCOUNT_ID": "c60933f634439b0fb2e6c7762535ba6c",
            },
        ), patch.dict(sys.modules, {"boto3": boto3}):
            client = profile_images.get_r2_profile_image_client()
            bucket = profile_images.get_r2_bucket_name()

        self.assertIs(client, s3)
        self.assertEqual(bucket, "workout-tracker-avatars")
        boto3.client.assert_called_once_with(
            "s3",
            endpoint_url="https://c60933f634439b0fb2e6c7762535ba6c.r2.cloudflarestorage.com",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            region_name="auto",
        )

    def test_remote_profile_image_url_uses_public_r2_bucket(self):
        with self.app.test_request_context(), patch("utils.profile_images.os.path.exists", return_value=False):
            url = profile_images.get_profile_image_url("avatars/user_123.png")

        self.assertEqual(
            url,
            "https://pub-b7699fec85f44832bc1255cae990054b.r2.dev/avatars/user_123.png",
        )

    def test_profile_photo_removal_deletes_from_r2_when_no_local_file_exists(self):
        user = self._create_logged_in_user(username="avatar_remove_user")
        stored_user = self.session.query(User).filter_by(id=user.id).one()
        stored_user.profile_image = "avatars/remote-only.png"
        self.session.commit()
        s3 = Mock()

        with patch("workout_tracker.routes.auth.has_r2_profile_image_storage", return_value=True), \
             patch("workout_tracker.routes.auth.get_r2_profile_image_client", return_value=s3), \
             patch("workout_tracker.routes.auth.get_r2_bucket_name", return_value="workout-tracker-avatars"):
            response = self.client.post(
                "/settings",
                data={"form_type": "remove_photo"},
            )

        self.assertEqual(response.status_code, 302)
        s3.delete_object.assert_called_once_with(
            Bucket="workout-tracker-avatars",
            Key="avatars/remote-only.png",
        )
        updated_user = self.session.query(User).filter_by(id=user.id).one()
        self.assertIsNone(updated_user.profile_image)

    def test_shortcut_urls_page_groups_shortcut_links_for_regular_users(self):
        self._create_logged_in_user(username="shortcut_urls_user")

        response = self.client.get("/shortcut/urls")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Log URL", page)
        self.assertIn("Retrieve URL", page)
        self.assertIn("/shortcut/log/", page)
        self.assertIn("/shortcut/pick/", page)
        self.assertIn("Session names", page)

    def test_shortcut_urls_page_lists_every_deployment_over_https(self):
        self._create_logged_in_user(username="shortcut_hosts_user")
        self.app.config["DEPLOYMENT_URLS"] = (
            "Railway=https://workoutlogger-production-7f91.up.railway.app,"
            "Render=https://workout-logger.onrender.com"
        )

        # Behind an HTTPS-terminating proxy, like Railway and Render.
        response = self.client.get("/shortcut/urls", headers={"X-Forwarded-Proto": "https"})

        page = response.get_data(as_text=True)
        self.assertIn("https://localhost/shortcut/log/", page)
        self.assertIn("https://workoutlogger-production-7f91.up.railway.app/shortcut/log/", page)
        self.assertIn("https://workout-logger.onrender.com/shortcut/log/", page)
        self.assertIn("https://workout-logger.onrender.com/shortcut/pick/", page)
        self.assertNotIn("http://localhost/shortcut", page)
        # The site being viewed comes first, then the other deployments.
        self.assertLess(page.index(">Local<"), page.index(">Railway<"))
        self.assertLess(page.index(">Railway<"), page.index(">Render<"))

    def test_shortcut_mapping_is_available_to_regular_users(self):
        self._create_logged_in_user(username="shortcut_mapping_user")

        response = self.client.get("/shortcut/mapping")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Session names", page)
        self.assertNotIn("Access denied", page)

    def test_bulk_import_invalid_header_date_is_handled_as_failed_block(self):
        self._create_logged_in_user(username="bulk_user")

        payload = "\n".join(
            [
                "32/13 Impossible Date Day",
                "Flat Dumbbell Press - [8-12]",
                "30, 8",
                "",
                "12/01 Valid Day",
                "Flat Dumbbell Press - [8-12]",
                "25, 10",
            ]
        )

        response = self.client.post(
            "/bulk-import",
            data={
                "bulk_workouts_text": payload,
                "confirm_import": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Days that failed", page)
        self.assertIn("32/13", page)

    def test_bulk_import_exercise_names_starting_with_a_number_are_not_dates(self):
        self._create_logged_in_user(username="bulk_decline")
        payload = "\n".join([
            "12/01/26 Push",
            "Flat Dumbbell Press",
            "30, 8",
            "3 Decline Press",
            "40, 10",
            "2 Marching Lunges",
            "20, 12",
        ])
        page = self.client.post("/bulk-import", data={"bulk_workouts_text": payload, "confirm_import": "0"}).get_data(as_text=True)
        # One day, not three (it used to read "3 Dec" and "2 Mar" as new days).
        self.assertIn("12-01-2026 – 12-01-2026", page)
        self.assertNotIn("Days that failed", page)

    def test_bulk_import_reads_iso_dotted_and_weekday_dates(self):
        user = self._create_logged_in_user(username="bulk_iso")
        payload = "\n".join([
            "2026-01-10 Push", "Flat Dumbbell Press", "30, 8", "",
            "Monday 12/01/26 Pull", "Barbell Row", "12.5, 10", "",
            "14.01.2026 Legs", "Leg Press", "200, 10",
        ])
        page = self.client.post("/bulk-import", data={"bulk_workouts_text": payload, "confirm_import": "1"},
                                follow_redirects=True).get_data(as_text=True)
        self.assertNotIn("No workout days found", page)
        days = sorted({log.date.date().isoformat() for log in self.session.query(WorkoutLog).filter_by(user_id=user.id)})
        # Three days: "12.5, 10" under Barbell Row is a set, not 12 May.
        self.assertEqual(days, ["2026-01-10", "2026-01-12", "2026-01-14"])
        titles = {log.date.date().isoformat(): log.workout_name for log in self.session.query(WorkoutLog).filter_by(user_id=user.id)}
        self.assertEqual(titles["2026-01-12"], "Pull")

    def test_bulk_import_missing_year_rolls_forward_chronologically(self):
        inferred = _infer_bulk_import_dates(
            [
                {"day": 30, "month": 12, "year": 2023},
                {"day": 31, "month": 12, "year": None},
                {"day": 1, "month": 1, "year": None},
                {"day": 2, "month": 1, "year": None},
            ],
            today=date(2026, 6, 6),
        )

        self.assertEqual(
            inferred,
            [
                date(2023, 12, 30),
                date(2023, 12, 31),
                date(2024, 1, 1),
                date(2024, 1, 2),
            ],
        )

    def test_bulk_import_preview_shows_detected_date_range(self):
        self._create_logged_in_user(username="bulk_range_user")

        payload = "\n".join(
            [
                "30/12/23 Year End",
                "Flat Dumbbell Press - [8-12]",
                "30, 8",
                "",
                "01/01 New Year",
                "Flat Dumbbell Press - [8-12]",
                "35, 8",
            ]
        )

        response = self.client.post(
            "/bulk-import",
            data={
                "bulk_workouts_text": payload,
                "confirm_import": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("30-12-2023 – 01-01-2024", page)

    def test_workout_detail_best_link_uses_same_selection_as_topn_best_logic(self):
        user = self._create_logged_in_user(username="workout_user")
        exercise = "Flat Dumbbell Press"

        # Top-N best by scoring logic: this older 3-set log should win among preferred logs.
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Session 1",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [8-12]\n100 95 90, 6 6 6",
                sets_json={"weights": [100, 95, 90], "reps": [6, 6, 6]},
                bodyweight=user.bodyweight,
                estimated_1rm=120.0,
            )
        )
        # Highest estimated_1rm but only one set: should not be selected by top-N best logic.
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 5, 9, 0, 0),
                workout_name="Session 2",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [8-12]\n120, 3",
                sets_json={"weights": [120], "reps": [3]},
                bodyweight=user.bodyweight,
                estimated_1rm=132.0,
            )
        )
        # Current workout view date.
        current_log = WorkoutLog(
            user_id=user.id,
            date=datetime(2026, 1, 10, 9, 0, 0),
            workout_name="Session 3",
            exercise=exercise,
            exercise_string="Flat Dumbbell Press - [8-12]\n85 80 80, 8 8 8",
            sets_json={"weights": [85, 80, 80], "reps": [8, 8, 8]},
            bodyweight=user.bodyweight,
            estimated_1rm=107.0,
        )
        self.session.add(current_log)
        self.session.commit()

        log_index = build_name_index([exercise])
        target_sets, strict_target_sets = resolve_target_sets_for_exercise(
            exercise_name=exercise,
            exercise_string=current_log.exercise_string,
            rep_target_sets={},
            plan_target_sets={},
            inferred_set_count=comparison_set_count(current_log.sets_json, current_log.exercise_string),
            default_sets=3,
        )
        expected_best = _get_best_log(
            self.session,
            user.id,
            exercise,
            target_sets=target_sets,
            strict_target_sets=strict_target_sets,
            log_ex_index=log_index,
            is_timed=False,
        )
        self.assertIsNotNone(expected_best)
        expected_date = expected_best.date.strftime("%Y-%m-%d")

        def _fake_render(template_name, **kwargs):
            if template_name == "workout_detail.html":
                return {
                    "rows": [
                        {
                            "exercise": row["name"],
                            "best_workout_url": row.get("best_workout_url"),
                            "performance_key": row.get("performance_key"),
                        }
                        for row in kwargs.get("rows", [])
                    ]
                }
            return {"template": template_name}

        with patch("workout_tracker.routes.workouts.render_template", side_effect=_fake_render):
            response = self.client.get("/workout/2026-01-10")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertTrue(data.get("rows"))
        best_url = data["rows"][0].get("best_workout_url") or ""

        m = re.search(r"/workout/(\d{4}-\d{2}-\d{2})", best_url)
        self.assertIsNotNone(m, msg=f"best_workout_url missing date: {best_url}")
        best_link_date = m.group(1)

        self.assertEqual(best_link_date, expected_date)

    def test_workout_detail_uses_aliases_for_previous_and_best_rails(self):
        user = self._create_logged_in_user(username="row_alias_user")
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 12, 9, 0, 0),
                workout_name="Back",
                exercise="Neutral-Grip Seated Row",
                exercise_string="Neutral-Grip Seated Row - [8-12]\n50 45, 8 8",
                sets_json={"weights": [50, 45], "reps": [8, 8]},
                bodyweight=user.bodyweight,
                top_weight=50,
                top_reps=8,
                estimated_1rm=63.33,
            )
        )
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 6, 5, 9, 0, 0),
                workout_name="Back",
                exercise="Seated Neutral-Grip Row",
                exercise_string="Seated Neutral-Grip Row - [8-12]\n50 45, 8 8",
                sets_json={"weights": [50, 45], "reps": [8, 8]},
                bodyweight=user.bodyweight,
                top_weight=50,
                top_reps=8,
                estimated_1rm=63.33,
            )
        )
        self.session.commit()

        response = self.client.get("/workout/2026-06-05")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Last · best</a><span class=\"date\">12 Jan</span>", page)
        self.assertNotIn("First log", page)
        self.assertNotIn("New baseline", page)

    def test_log_summary_uses_aliases_for_reordered_saved_exercises(self):
        user = self._create_logged_in_user(username="log_summary_alias_user")
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 3, 22, 9, 0, 0),
                workout_name="Session 2",
                exercise="Rear Delt Machine Fly",
                exercise_string="Rear Delt Machine Fly - [12-20]\n60 53.5 50, 14 19 20",
                sets_json={"weights": [60, 53.5, 50], "reps": [14, 19, 20]},
                bodyweight=user.bodyweight,
                estimated_1rm=88.0,
            )
        )
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 4, 1, 9, 0, 0),
                workout_name="Session 2",
                exercise="Wrist Flexion - Dumbbell",
                exercise_string="Wrist Flexion - Dumbbell - [12-20]\n15 13.8 12.5, 14 18 21",
                sets_json={"weights": [15, 13.8, 12.5], "reps": [14, 18, 21]},
                bodyweight=user.bodyweight,
                estimated_1rm=22.0,
            )
        )
        self.session.commit()

        parsed = {
            "date": datetime(2026, 6, 10, 9, 0, 0),
            "workout_name": "Session 2 - Shoulders & Forearms",
            "exercises": [
                {
                    "name": "Machine Rear Delt Fly",
                    "exercise_string": "Machine Rear Delt Fly\n60 53.5 50, 14 19 20",
                    "weights": [60, 53.5, 50],
                    "reps": [14, 19, 20],
                    "valid": True,
                },
                {
                    "name": "Dumbbell Wrist Flexion",
                    "exercise_string": "Dumbbell Wrist Flexion\n15 12.5, 16 20",
                    "weights": [15, 12.5],
                    "reps": [16, 20],
                    "valid": True,
                },
            ],
        }

        immediate_summary = handle_workout_log(self.session, user, parsed)
        self.session.commit()

        immediate_by_name = {row["name"]: row for row in immediate_summary}
        self.assertNotEqual(immediate_by_name["Machine Rear Delt Fly"]["old"], "First Log")
        self.assertNotEqual(immediate_by_name["Dumbbell Wrist Flexion"]["old"], "First Log")

        recomputed_summary, _, _ = compute_workout_summary_for_date(
            self.session,
            user,
            datetime(2026, 6, 10),
        )
        recomputed_by_name = {row["name"]: row for row in recomputed_summary}

        self.assertNotEqual(recomputed_by_name["Machine Rear Delt Fly"]["old"], "First Log")
        self.assertNotEqual(recomputed_by_name["Dumbbell Wrist Flexion"]["old"], "First Log")
        self.assertIn("60 x 14, 53.5 x 19, 50 x 20", recomputed_by_name["Machine Rear Delt Fly"]["old"])
        self.assertIn("15 x", recomputed_by_name["Dumbbell Wrist Flexion"]["old"])

    def test_stats_query_alias_loads_specific_exercise_chart(self):
        user = self._create_logged_in_user(username="stats_alias_user")
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 12, 9, 0, 0),
                workout_name="Back",
                exercise="Neutral-Grip Seated Row",
                exercise_string="Neutral-Grip Seated Row - [8-12]\n50 45, 8 8",
                sets_json={"weights": [50, 45], "reps": [8, 8]},
                bodyweight=user.bodyweight,
                estimated_1rm=63.33,
            )
        )
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 6, 5, 9, 0, 0),
                workout_name="Back",
                exercise="Seated Neutral-Grip Row",
                exercise_string="Seated Neutral-Grip Row - [8-12]\n50 45, 8 8",
                sets_json={"weights": [50, 45], "reps": [8, 8]},
                bodyweight=user.bodyweight,
                estimated_1rm=63.33,
            )
        )
        self.session.commit()

        response = self.client.get("/stats?exercise=Seated%20Neutral-Grip%20Row")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('"value": "Neutral-Grip Seated Row"', page)
        self.assertIn('"label": "Neutral-Grip Seated Row"', page)

    def test_stats_sort_and_range_preferences_are_saved_and_rendered(self):
        user = self._create_logged_in_user(username="stats_sort_user")
        prefs_tag = '<script type="application/json" id="statsPreferencesData">'

        page = self.client.get("/stats").get_data(as_text=True)
        self.assertIn(prefs_tag + '{"range": "all", "sort_mode": "most_viewed"}</script>', page)

        response = self.client.post("/stats/preferences", data={"sort_mode": "alpha_desc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "sort_mode": "alpha_desc", "range": "all"})

        # Saving the range keeps the sort mode.
        response = self.client.post("/stats/preferences", data={"range": "365"})
        self.assertEqual(response.get_json(), {"ok": True, "sort_mode": "alpha_desc", "range": "365"})
        preference = self.session.query(StatsPreference).filter_by(user_id=user.id).one()
        self.assertEqual((preference.sort_mode, preference.time_range), ("alpha_desc", "365"))

        page = self.client.get("/stats").get_data(as_text=True)
        self.assertIn(prefs_tag + '{"range": "365", "sort_mode": "alpha_desc"}</script>', page)

        self.assertEqual(self.client.post("/stats/preferences", data={"sort_mode": "unknown"}).status_code, 400)
        self.assertEqual(self.client.post("/stats/preferences", data={"range": "7"}).status_code, 400)
        self.assertEqual(self.client.post("/stats/preferences", data={}).status_code, 400)

    def test_stats_exercise_views_are_counted_once_per_visit(self):
        user = self._create_logged_in_user(username="stats_views_user")
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 2, 3, 9, 0, 0),
                workout_name="Legs",
                exercise="Deadlift",
                exercise_string="Deadlift - [5]\n100, 5",
                sets_json={"weights": [100], "reps": [5]},
                bodyweight=user.bodyweight,
                estimated_1rm=116.67,
            )
        )
        self.session.commit()

        self.client.get("/stats/data/Deadlift")
        self.client.get("/stats/data/Deadlift")  # same visit: not counted again
        view = self.session.query(StatsExerciseView).filter_by(user_id=user.id).one()
        self.assertEqual(view.view_count, 1)

        view.last_viewed_at = datetime.now() - timedelta(hours=1)
        self.session.commit()
        self.client.get("/stats/data/Deadlift")
        view = self.session.query(StatsExerciseView).filter_by(user_id=user.id).one()
        self.assertEqual(view.view_count, 2)

        page = self.client.get("/stats").get_data(as_text=True)
        self.assertIn('"views": 2', page)

    def test_stats_exercise_options_include_session_counts(self):
        user = self._create_logged_in_user(username="stats_sessions_user")
        for day in (3, 3, 10):
            self.session.add(
                WorkoutLog(
                    user_id=user.id,
                    date=datetime(2026, 2, day, 9, 0, 0),
                    workout_name="Back",
                    exercise="Barbell Row",
                    exercise_string="Barbell Row - [8-12]\n50, 8",
                    sets_json={"weights": [50], "reps": [8]},
                    bodyweight=user.bodyweight,
                    estimated_1rm=63.33,
                )
            )
        self.session.commit()

        page = self.client.get("/stats").get_data(as_text=True)

        # Two logs on the same day count as one session.
        self.assertIn('"last": "2026-02-10"', page)
        self.assertIn('"sessions": 2', page)

    def test_workout_detail_vs_best_ignores_future_logs(self):
        user = self._create_logged_in_user(username="workout_user_future_best")
        exercise = "Flat Dumbbell Press"

        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Session 1",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [8-12]\n80 80 80, 8 8 8",
                sets_json={"weights": [80, 80, 80], "reps": [8, 8, 8]},
                bodyweight=user.bodyweight,
                estimated_1rm=101.33,
            )
        )
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 10, 9, 0, 0),
                workout_name="Session 2",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [8-12]\n90 90 90, 8 8 8",
                sets_json={"weights": [90, 90, 90], "reps": [8, 8, 8]},
                bodyweight=user.bodyweight,
                estimated_1rm=114.0,
            )
        )
        # This future log should not affect the /workout/2026-01-10 "Vs Best" rail.
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 20, 9, 0, 0),
                workout_name="Session 3",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [8-12]\n130 130 130, 5 5 5",
                sets_json={"weights": [130, 130, 130], "reps": [5, 5, 5]},
                bodyweight=user.bodyweight,
                estimated_1rm=151.67,
            )
        )
        self.session.commit()

        def _fake_render(template_name, **kwargs):
            if template_name == "workout_detail.html":
                return {
                    "rows": [
                        {
                            "exercise": row["name"],
                            "best_workout_url": row.get("best_workout_url"),
                            "performance_key": row.get("performance_key"),
                        }
                        for row in kwargs.get("rows", [])
                    ]
                }
            return {"template": template_name}

        with patch("workout_tracker.routes.workouts.render_template", side_effect=_fake_render):
            response = self.client.get("/workout/2026-01-10")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertTrue(data.get("rows"))

        row = data["rows"][0]
        best_url = row.get("best_workout_url") or ""
        m = re.search(r"/workout/(\d{4}-\d{2}-\d{2})", best_url)
        self.assertIsNotNone(m, msg=f"best_workout_url missing date: {best_url}")
        best_link_date = m.group(1)

        self.assertEqual(best_link_date, "2026-01-01")
        self.assertEqual(row.get("performance_key"), "gold_strength")

    def test_classifier_awards_gold_load_only_when_top_weight_beats_reference(self):
        user = self._create_logged_in_user(username="gold_load_user")
        exercise = "Tie Lift"
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Baseline",
                exercise=exercise,
                exercise_string="Tie Lift\n22.5 18 15, 10 20 30",
                sets_json={"weights": [22.5, 18, 15], "reps": [10, 20, 30]},
                bodyweight=user.bodyweight,
                estimated_1rm=30.0,
            )
        )
        current = WorkoutLog(
            user_id=user.id,
            date=datetime(2026, 1, 10, 9, 0, 0),
            workout_name="Current",
            exercise=exercise,
            exercise_string="Tie Lift\n25 22.5 18, 6 10 20",
            sets_json={"weights": [25, 22.5, 18], "reps": [6, 10, 20]},
            bodyweight=user.bodyweight,
            estimated_1rm=30.0,
        )
        self.session.add(current)
        self.session.commit()

        perf = classify_exercise_performance(
            self.session,
            user.id,
            exercise,
            current.sets_json,
            current_log_id=current.id,
            current_exercise_string=current.exercise_string,
        )

        self.assertEqual(perf["key"], "gold_load")

    def test_classifier_awards_silver_load_when_second_weight_beats_reference(self):
        user = self._create_logged_in_user(username="silver_load_user")
        exercise = "Tie Lift"
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Baseline",
                exercise=exercise,
                exercise_string="Tie Lift\n25 18 15, 6 20 30",
                sets_json={"weights": [25, 18, 15], "reps": [6, 20, 30]},
                bodyweight=user.bodyweight,
                estimated_1rm=30.0,
            )
        )
        current = WorkoutLog(
            user_id=user.id,
            date=datetime(2026, 1, 10, 9, 0, 0),
            workout_name="Current",
            exercise=exercise,
            exercise_string="Tie Lift\n25 22.5 18, 6 10 20",
            sets_json={"weights": [25, 22.5, 18], "reps": [6, 10, 20]},
            bodyweight=user.bodyweight,
            estimated_1rm=30.0,
        )
        self.session.add(current)
        self.session.commit()

        perf = classify_exercise_performance(
            self.session,
            user.id,
            exercise,
            current.sets_json,
            current_log_id=current.id,
            current_exercise_string=current.exercise_string,
        )

        self.assertEqual(perf["key"], "silver_load")

    def test_classifier_is_consistent_when_tied_scores_and_loads_do_not_beat_reference(self):
        user = self._create_logged_in_user(username="consistent_load_user")
        exercise = "Tie Lift"
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Baseline",
                exercise=exercise,
                exercise_string="Tie Lift\n25 22.5 18, 6 10 20",
                sets_json={"weights": [25, 22.5, 18], "reps": [6, 10, 20]},
                bodyweight=user.bodyweight,
                estimated_1rm=30.0,
            )
        )
        current = WorkoutLog(
            user_id=user.id,
            date=datetime(2026, 1, 10, 9, 0, 0),
            workout_name="Current",
            exercise=exercise,
            exercise_string="Tie Lift\n25 18 15, 6 20 30",
            sets_json={"weights": [25, 18, 15], "reps": [6, 20, 30]},
            bodyweight=user.bodyweight,
            estimated_1rm=30.0,
        )
        self.session.add(current)
        self.session.commit()

        perf = classify_exercise_performance(
            self.session,
            user.id,
            exercise,
            current.sets_json,
            current_log_id=current.id,
            current_exercise_string=current.exercise_string,
        )

        self.assertEqual(perf["key"], "consistent")

    def test_classifier_reference_prefers_full_set_logs_like_best_log_lookup(self):
        user = self._create_logged_in_user(username="full_set_reference_user")
        exercise = "Reference Lift"
        short_day = WorkoutLog(
            user_id=user.id,
            date=datetime(2026, 1, 1, 9, 0, 0),
            workout_name="Short",
            exercise=exercise,
            exercise_string="Reference Lift\n40 40 40 40, 10 10 10 10",
            sets_json={"weights": [40, 40, 40, 40], "reps": [10, 10, 10, 10]},
            bodyweight=user.bodyweight,
        )
        full_day = WorkoutLog(
            user_id=user.id,
            date=datetime(2026, 1, 5, 9, 0, 0),
            workout_name="Full",
            exercise=exercise,
            exercise_string="Reference Lift\n30 30 30 30 30, 10 10 10 10 10",
            sets_json={"weights": [30, 30, 30, 30, 30], "reps": [10, 10, 10, 10, 10]},
            bodyweight=user.bodyweight,
        )
        current = WorkoutLog(
            user_id=user.id,
            date=datetime(2026, 1, 10, 9, 0, 0),
            workout_name="Current",
            exercise=exercise,
            exercise_string="Reference Lift\n35 35 35 35 35, 10 10 10 10 10",
            sets_json={"weights": [35, 35, 35, 35, 35], "reps": [10, 10, 10, 10, 10]},
            bodyweight=user.bodyweight,
        )
        self.session.add_all([short_day, full_day, current])
        self.session.commit()

        day_start = datetime(2026, 1, 10)
        perf = classify_exercise_performance(
            self.session,
            user.id,
            exercise,
            current.sets_json,
            target_sets=5,
            current_log_id=current.id,
            current_exercise_string=current.exercise_string,
            historical_before_dt=day_start,
        )
        best_log = get_best_log_for_exercise_before_date(
            self.session,
            user.id,
            exercise,
            target_sets=5,
            workout_day_start_dt=day_start,
        )

        # The 4-set day must not become the medal baseline while "Vs Best" links the 5-set day.
        self.assertEqual(best_log.id, full_day.id)
        self.assertEqual(perf["reference_log_id"], full_day.id)
        self.assertEqual(perf["key"], "gold_strength")

    def test_incomplete_strict_session_gets_compared_badge_not_consistent_short_circuit(self):
        user = self._create_logged_in_user(username="incomplete_badge_user")
        exercise = "Flat Dumbbell Press"

        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Session 1",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [3, 6-8]\n100 100 100, 5 5 5",
                sets_json={"weights": [100, 100, 100], "reps": [5, 5, 5]},
                bodyweight=user.bodyweight,
                estimated_1rm=116.67,
            )
        )
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 10, 9, 0, 0),
                workout_name="Session 2",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [3, 6-8]\n90 90, 5 5",
                sets_json={"weights": [90, 90], "reps": [5, 5]},
                bodyweight=user.bodyweight,
                estimated_1rm=105.0,
            )
        )
        self.session.commit()

        def _fake_render(template_name, **kwargs):
            if template_name == "workout_detail.html":
                return {
                    "rows": [
                        {
                            "exercise": row["name"],
                            "performance_key": row.get("performance_key"),
                        }
                        for row in kwargs.get("rows", [])
                    ]
                }
            return {"template": template_name}

        with patch("workout_tracker.routes.workouts.render_template", side_effect=_fake_render):
            response = self.client.get("/workout/2026-01-10")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("rows"))
        key = data["rows"][0].get("performance_key")
        self.assertIsNotNone(key)
        self.assertNotEqual(key, "consistent")

    def test_declared_set_count_expands_shorthand_before_pr_update(self):
        user = self._create_logged_in_user(username="declared_set_pr_user")
        exercise = "Flat Dumbbell Press"
        baseline_date = datetime(2026, 1, 1, 9, 0, 0)
        baseline_sets = {"weights": [100, 95, 90], "reps": [5, 5, 5]}
        baseline_best_string = "Flat Dumbbell Press - [3, 6-8]\n100 95 90, 5 5 5"

        baseline_log = WorkoutLog(
            user_id=user.id,
            date=baseline_date,
            workout_name="Session 1",
            exercise=exercise,
            exercise_string=baseline_best_string,
            sets_json=baseline_sets,
            bodyweight=user.bodyweight,
            estimated_1rm=116.67,
        )
        self.session.add(baseline_log)
        self.session.flush()
        self.session.add(
            Lift(
                user_id=user.id,
                exercise=exercise,
                best_log_id=baseline_log.id,
            )
        )
        self.session.commit()

        parsed = {
            "date": datetime(2026, 1, 10, 9, 0, 0),
            "workout_name": "Session 2",
            "exercises": [
                {
                    "name": exercise,
                    "weights": [130, 130],
                    "reps": [5, 5],
                    "exercise_string": "Flat Dumbbell Press - [3, 6-8]\n130 130, 5 5",
                    "valid": True,
                }
            ],
        }

        handle_workout_log(self.session, user, parsed)
        self.session.commit()

        lift = (
            self.session.query(Lift)
            .filter(Lift.user_id == user.id, Lift.exercise == exercise)
            .one()
        )
        self.assertIsNotNone(lift.best_log)
        self.assertEqual(lift.best_log.sets_json, {"weights": [130.0, 130.0, 130.0], "reps": [5, 5, 5]})
        self.assertEqual(lift.best_log.exercise_string, "Flat Dumbbell Press - [3, 6-8]\n130 130, 5 5")
        self.assertEqual(lift.best_log.date, datetime(2026, 1, 10, 9, 0, 0))

    def test_declared_set_count_expands_smaller_history_for_comparison(self):
        user = self._create_logged_in_user(username="expanded_baseline_user")
        exercise = "Flat Dumbbell Press"

        # Historical shorthand expands to three sets, so it remains comparable.
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 1, 9, 0, 0),
                workout_name="Session 1",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [3, 6-8]\n100, 5",
                sets_json={"weights": [100], "reps": [5]},
                bodyweight=user.bodyweight,
                estimated_1rm=116.67,
            )
        )
        self.session.add(
            WorkoutLog(
                user_id=user.id,
                date=datetime(2026, 1, 10, 9, 0, 0),
                workout_name="Session 2",
                exercise=exercise,
                exercise_string="Flat Dumbbell Press - [3, 6-8]\n95 95, 5 5",
                sets_json={"weights": [95, 95], "reps": [5, 5]},
                bodyweight=user.bodyweight,
                estimated_1rm=110.83,
            )
        )
        self.session.commit()

        def _fake_render(template_name, **kwargs):
            if template_name == "workout_detail.html":
                return {
                    "rows": [
                        {
                            "exercise": row["name"],
                            "performance_key": row.get("performance_key"),
                            "performance_label": row.get("performance_label"),
                        }
                        for row in kwargs.get("rows", [])
                    ]
                }
            return {"template": template_name}

        with patch("workout_tracker.routes.workouts.render_template", side_effect=_fake_render):
            response = self.client.get("/workout/2026-01-10")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("rows"))
        row = data["rows"][0]
        self.assertEqual(row.get("performance_key"), "significantly_off")
        self.assertEqual(row.get("performance_label"), "Below best")


if __name__ == "__main__":
    unittest.main()
