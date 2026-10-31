import io
import re
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import Config
from models import Base, User, UserRole
from liftbook import create_app
from liftbook.app_icons import FILENAMES, prepare_source


class _TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    ENABLE_CSRF = False
    WTF_CSRF_ENABLED = False


def _off_center_upload():
    """A gold blob in the top-left corner of a black square, as a PNG upload."""
    image = Image.new("RGB", (800, 800), (0, 0, 0))
    ImageDraw.Draw(image).rectangle([40, 60, 340, 300], fill=(220, 180, 90))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return buf


class TestAppIcon(unittest.TestCase):
    """Two app instances sharing one database stand in for Railway and Render."""

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.session = scoped_session(sessionmaker(bind=self.engine))
        Base.metadata.create_all(self.engine)
        self._patchers = [
            patch("models.Session", self.session),
            patch("liftbook.Session", self.session),
            patch("liftbook.routes.app_icon.Session", self.session),
            patch("liftbook.routes.app_icon.VERSION_TTL_SECONDS", 0),
        ]
        for p in self._patchers:
            p.start()
        self.host_a = create_app(config_object=_TestConfig, init_db=False).test_client()
        self.host_b = create_app(config_object=_TestConfig, init_db=False).test_client()

    def tearDown(self):
        for p in reversed(self._patchers):
            p.stop()
        self.session.remove()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _log_in(self, client, role):
        user = User(username=f"icon_{role.name.lower()}", role=role, is_verified=True)
        self.session.add(user)
        self.session.commit()
        user_id = int(user.id)
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True

    def _manifest_icon_urls(self, client):
        response = client.get("/static/manifest.json")
        self.assertEqual(response.status_code, 200)
        return [icon["src"] for icon in response.get_json()["icons"]]

    def test_default_icon_is_served_in_every_size(self):
        urls = self._manifest_icon_urls(self.host_a)
        self.assertEqual(len(urls), 4)
        version = urls[0].split("/")[2]
        for filename in FILENAMES:
            response = self.host_a.get(f"/app-icon/{version}/{filename}")
            self.assertEqual(response.status_code, 200, filename)
            self.assertIn("immutable", response.headers["Cache-Control"])
        self.assertEqual(self.host_a.get("/favicon.ico").status_code, 200)
        self.assertEqual(self.host_a.get(f"/app-icon/{version}/nope.png").status_code, 404)

    def test_upload_on_one_host_shows_on_the_other(self):
        old_urls = self._manifest_icon_urls(self.host_b)

        self._log_in(self.host_a, UserRole.ADMIN)
        response = self.host_a.post(
            "/admin/app-icon",
            data={"app_icon": (_off_center_upload(), "icon.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        new_urls = self._manifest_icon_urls(self.host_b)
        self.assertNotEqual(old_urls, new_urls)
        new_icon = Image.open(io.BytesIO(self.host_b.get(new_urls[0]).data))
        self.assertEqual(new_icon.size, (512, 512))

        # An old icon URL (e.g. cached in a page) gets the new icon, uncached.
        stale = self.host_b.get(old_urls[0])
        self.assertEqual(stale.data, self.host_b.get(new_urls[0]).data)
        self.assertEqual(stale.headers["Cache-Control"], "no-cache")

        # Pages on the other host link the new icon and launch screens too.
        page = self.host_b.get("/login").get_data(as_text=True)
        version = new_urls[0].split("/")[2]
        self.assertIn(f"/app-icon/{version}/apple-touch-icon.png", page)
        self.assertEqual(len(re.findall(rf"/app-icon/{version}/splash/", page)), 13)

    def test_regular_users_cannot_change_the_icon(self):
        before = self._manifest_icon_urls(self.host_a)
        self._log_in(self.host_a, UserRole.USER)
        self.host_a.post(
            "/admin/app-icon",
            data={"app_icon": (_off_center_upload(), "icon.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(self._manifest_icon_urls(self.host_a), before)

    def test_uploads_are_sized_and_optically_centered(self):
        prepared = prepare_source(Image.open(_off_center_upload()))
        figure = np.asarray(prepared).max(axis=2) > 60
        ys, xs = np.nonzero(figure)
        size = prepared.width
        self.assertAlmostEqual((xs.max() - xs.min() + 1) / size, 0.78, delta=0.01)
        self.assertAlmostEqual(xs.min(), size - 1 - xs.max(), delta=2)
        self.assertAlmostEqual((ys.mean() - (size - 1) / 2) / size, -0.03, delta=0.005)


if __name__ == "__main__":
    unittest.main()
