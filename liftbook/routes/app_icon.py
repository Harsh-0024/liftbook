"""Serve the app icon in every size, from the shared database.

An admin upload is stored in the `app_icon` table, which every host reads, so a
new icon shows up everywhere without a deploy. Until one is uploaded, the icon
committed at static/icons/app-icon-source.png is used. Icon URLs carry the
icon's version, so browsers and phones fetch a new icon instead of a cached one.
"""
import hashlib
import io
import threading
import time
from pathlib import Path

from flask import Response, abort, jsonify, request, url_for
from PIL import Image

from models import AppIcon, Session
from utils.logger import logger

from ..app_icons import FILENAMES, MASKABLE_SIZES, PLAIN_SIZES, background_color, prepare_source, render

# How long a host trusts its cached icon version before asking the database
# again; an upload on one host reaches the others within this time.
VERSION_TTL_SECONDS = 30


def _version_of(png_bytes):
    return hashlib.sha256(png_bytes).hexdigest()[:12]


class AppIconStore:
    def __init__(self, default_path):
        self._default_png = Path(default_path).read_bytes()
        self._default_version = _version_of(self._default_png)
        self._lock = threading.Lock()
        self._version = None
        self._checked_at = 0.0
        self._source = None
        self._files = {}

    def version(self):
        now = time.monotonic()
        if self._version is not None and now - self._checked_at < VERSION_TTL_SECONDS:
            return self._version
        try:
            stored = Session.query(AppIcon.version).filter_by(id=1).scalar()
        except Exception as exc:
            # Database not reachable (e.g. still starting): keep what we have.
            Session.rollback()
            logger.warning(f"App icon version check failed: {exc}")
            return self._version or self._default_version
        self._use(stored or self._default_version)
        self._checked_at = now
        return self._version

    def _use(self, version):
        with self._lock:
            if version != self._version:
                self._version = version
                self._source = None
                self._files = {}

    def source(self):
        version = self.version()
        with self._lock:
            if self._source is None:
                png = self._default_png
                if version != self._default_version:
                    row = Session.query(AppIcon.image, AppIcon.version).filter_by(id=1).first()
                    if row is not None:
                        png, self._version = row.image, row.version
                self._source = Image.open(io.BytesIO(png)).convert('RGB')
            return self._source

    def file(self, filename):
        source = self.source()
        with self._lock:
            data = self._files.get(filename)
        if data is None:
            data = render(source, filename)
            with self._lock:
                self._files[filename] = data
        return data

    def save(self, image):
        """Store an uploaded icon (sized and centered first) for every host."""
        buf = io.BytesIO()
        prepare_source(image).save(buf, format='PNG', optimize=True)
        png = buf.getvalue()
        version = _version_of(png)
        try:
            row = Session.query(AppIcon).filter_by(id=1).first()
            if row is None:
                Session.add(AppIcon(id=1, image=png, version=version))
            else:
                row.image, row.version = png, version
            Session.commit()
        except Exception:
            Session.rollback()
            raise
        self._use(version)
        self._checked_at = time.monotonic()


def register_app_icon_routes(app):
    store = AppIconStore(Path(app.static_folder) / 'icons' / 'app-icon-source.png')
    app.extensions['app_icon_store'] = store

    def app_icon_url(filename, external=False):
        return url_for('app_icon_file', version=store.version(), filename=filename, _external=external)

    app.jinja_env.globals['app_icon_url'] = app_icon_url

    def _icon_response(filename, cache_control):
        data = store.file(filename)
        mimetype = 'image/x-icon' if filename.endswith('.ico') else 'image/png'
        response = Response(data, mimetype=mimetype)
        response.headers['Cache-Control'] = cache_control
        return response

    def app_icon_file(version, filename):
        if filename not in FILENAMES:
            abort(404)
        # A versioned URL never changes content, so it can be cached for good;
        # an old version's URL gets the current icon, uncached.
        if version == store.version():
            return _icon_response(filename, 'public, max-age=31536000, immutable')
        return _icon_response(filename, 'no-cache')

    def favicon():
        response = _icon_response('favicon.ico', 'no-cache')
        response.set_etag(store.version())
        return response.make_conditional(request)

    def manifest():
        bg = '#%02x%02x%02x' % background_color(store.source())
        icons = [
            {'src': app_icon_url(name), 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'any'}
            for name, size in PLAIN_SIZES.items() if size >= 192
        ] + [
            {'src': app_icon_url(name), 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'maskable'}
            for name, size in MASKABLE_SIZES.items()
        ]
        response = jsonify({
            'id': '/',
            'name': 'Liftbook',
            'short_name': 'Liftbook',
            'start_url': '/',
            'display': 'standalone',
            'background_color': bg,
            'theme_color': '#000000',
            'icons': icons,
        })
        response.mimetype = 'application/manifest+json'
        response.headers['Cache-Control'] = 'no-cache'
        response.set_etag(store.version())
        return response.make_conditional(request)

    app.add_url_rule('/app-icon/<version>/<path:filename>', endpoint='app_icon_file', view_func=app_icon_file)
    app.add_url_rule('/favicon.ico', endpoint='favicon', view_func=favicon)
    # Same address the static file had: installed apps look for updates there.
    app.add_url_rule('/static/manifest.json', endpoint='manifest', view_func=manifest)
