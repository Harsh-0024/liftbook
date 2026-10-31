import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import Config
from models import Base, Feedback, User, UserRole
from liftbook import create_app


class _TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    ENABLE_CSRF = False
    WTF_CSRF_ENABLED = False


class TestFeedback(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.session = scoped_session(sessionmaker(bind=self.engine))
        Base.metadata.create_all(self.engine)
        self._patchers = [
            patch("models.Session", self.session),
            patch("liftbook.Session", self.session),
            patch("services.feedback.Session", self.session),
            patch("services.admin.Session", self.session),
        ]
        for p in self._patchers:
            p.start()
        self.app = create_app(config_object=_TestConfig, init_db=False)
        self.client = self.app.test_client()

    def tearDown(self):
        for p in reversed(self._patchers):
            p.stop()
        self.session.remove()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _user(self, name, role=UserRole.USER, full_name=None):
        user = User(username=name, email=f"{name}@example.com", full_name=full_name, role=role, is_verified=True)
        self.session.add(user)
        self.session.commit()
        return int(user.id)

    def _log_in(self, user_id):
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True

    def test_user_sends_feedback_and_sees_it(self):
        self._log_in(self._user("lifter"))
        response = self.client.post(
            "/feedback",
            data={"kind": "idea", "message": "Rest timer between sets, please", "page": "/log"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("went straight to the developer", body)
        self.assertIn("Rest timer between sets, please", body)
        item = self.session.query(Feedback).one()
        self.assertEqual((item.kind, item.status, item.page), ("idea", "new", "/log"))

    def test_empty_or_unknown_feedback_is_refused_and_kept(self):
        self._log_in(self._user("lifter"))
        response = self.client.post("/feedback", data={"kind": "idea", "message": "   "})
        self.assertIn("Write a few words first", response.get_data(as_text=True))
        response = self.client.post("/feedback", data={"kind": "rant", "message": "keep me"})
        body = response.get_data(as_text=True)
        self.assertIn("Choose what kind", body)
        self.assertIn("keep me", body)
        self.assertEqual(self.session.query(Feedback).count(), 0)

    def test_outside_address_is_not_stored_as_page(self):
        self._log_in(self._user("lifter"))
        self.client.post("/feedback", data={"kind": "like", "message": "Nice", "page": "https://evil.example/x"})
        self.assertIsNone(self.session.query(Feedback).one().page)

    def test_admin_sees_who_sent_it_and_the_sender_sees_it_was_read(self):
        user_id = self._user("lifter", full_name="Asha Rao")
        self._log_in(user_id)
        self.client.post("/feedback", data={"kind": "dislike", "message": "Stats page is slow"})

        admin_id = self._user("boss", role=UserRole.ADMIN)
        self._log_in(admin_id)
        dashboard = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("1 new", dashboard)

        page = self.client.get("/admin/feedback").get_data(as_text=True)
        self.assertIn("Stats page is slow", page)
        self.assertIn("Asha Rao", page)
        self.assertIn("@lifter", page)
        self.assertIn("lifter@example.com", page)
        self.assertIn(">New<", page)
        self.session.expire_all()
        item = self.session.query(Feedback).one()
        self.assertEqual(item.status, "seen")
        item_id = item.id

        self.client.post(f"/admin/feedback/{item_id}/status", data={"status": "done"})
        self.session.expire_all()
        self.assertEqual(self.session.query(Feedback).one().status, "done")

        self._log_in(user_id)
        self.assertIn("Done", self.client.get("/feedback").get_data(as_text=True))

        self._log_in(admin_id)
        self.client.post(f"/admin/feedback/{item_id}/delete")
        self.assertEqual(self.session.query(Feedback).count(), 0)

    def test_people_who_are_not_admins_cannot_read_feedback(self):
        self._log_in(self._user("lifter"))
        response = self.client.get("/admin/feedback")
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/admin/feedback/1/status", data={"status": "done"})
        self.assertEqual(response.status_code, 302)

    def test_signed_out_people_are_sent_to_log_in(self):
        response = self.client.get("/feedback")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_settings_links_to_feedback(self):
        self._log_in(self._user("lifter"))
        self.assertIn('href="/feedback"', self.client.get("/settings").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
