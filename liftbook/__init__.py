import gzip
import os
import secrets
import urllib.parse
import threading
import time
from datetime import date, datetime

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from models import Session, User, initialize_database
from services.email_service import EmailService
from services.email_queue import email_queue
from utils.logger import logger

from .app_icons import IPHONE_SCREENS, splash_filename
from .routes.admin import register_admin_routes
from .routes.app_icon import register_app_icon_routes
from .routes.auth import register_auth_routes
from .routes.feedback import register_feedback_routes
from .routes.plans import register_plan_routes
from .routes.stats import register_stats_routes
from .routes.workouts import SHORTCUT_KEY_MISSING, deployment_name, register_workout_routes


def create_app(config_object=Config, init_db: bool = True):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, 'templates'),
        static_folder=os.path.join(base_dir, 'static'),
    )
    app.config.from_object(config_object)
    # Railway and Render terminate HTTPS at their proxy; trust its forwarded
    # scheme so external URLs (share and shortcut links) come out as https.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

    if not app.config.get('SECRET_KEY'):
        if app.config.get('TESTING') or app.config.get('DEBUG'):
            app.config['SECRET_KEY'] = secrets.token_urlsafe(32)
        else:
            raise RuntimeError('SECRET_KEY must be set in the environment for production')
    app.secret_key = app.config['SECRET_KEY']

    app.config.setdefault('WTF_CSRF_ENABLED', bool(getattr(config_object, 'ENABLE_CSRF', False)))
    csrf = None
    if app.config.get('WTF_CSRF_ENABLED'):
        csrf = CSRFProtect(app)

    # Pages carry ~120-200 KB of inline styles; gzipped they are ~20-40 KB, which matters on a
    # weak gym signal. Only text, only when the browser asks, never files or streams (and a proxy
    # that compresses too leaves an already-compressed response alone).
    compressible = ('text/', 'application/json', 'application/javascript', 'application/manifest+json', 'image/svg+xml')

    @app.after_request
    def gzip_response(response):
        if (
            response.direct_passthrough
            or response.is_streamed
            or response.status_code < 200
            or response.status_code in (204, 304)
            or 'Content-Encoding' in response.headers
            or 'gzip' not in (request.headers.get('Accept-Encoding') or '').lower()
            or not (response.mimetype or '').startswith(compressible)
        ):
            return response
        body = response.get_data()
        if len(body) < 1024:
            return response
        response.set_data(gzip.compress(body, compresslevel=6))
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Content-Length'] = str(len(response.get_data()))
        response.vary.add('Accept-Encoding')
        return response

    @app.after_request
    def security_headers(response):
        # Browsers take files only as the type they're sent as, and no other site can
        # show these pages inside a frame (a disguised "Delete" button, say).
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        return response

    @app.context_processor
    def inject_feature_flags():
        return {
            'ENABLE_CSRF': bool(app.config.get('WTF_CSRF_ENABLED')),
            'current_year': datetime.now().year,
        }

    app.jinja_env.globals['iphone_launch_screens'] = [
        (css_w, css_h, ratio, splash_filename(css_w, css_h, ratio))
        for css_w, css_h, ratio in IPHONE_SCREENS
    ]

    if init_db:
        try:
            initialize_database()
        except Exception as exc:
            logger.critical(f"Database initialization failed: {exc}", exc_info=True)
            raise

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = None

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return Session.get(User, int(user_id))
        except Exception:
            return None

    mail = Mail(app)
    email_service = EmailService(mail)

    # Start email queue processor in background
    def process_email_queue():
        while True:
            try:
                with app.app_context():
                    email_queue.process_queue(email_service)
                    email_queue.cleanup_old_files()
            except Exception as e:
                logger.error(f"Email queue processing error: {e}", exc_info=True)
            time.sleep(30)  # Process queue every 30 seconds

    if not app.config.get('TESTING'):  # Don't start background thread in tests
        threading.Thread(target=process_email_queue, daemon=True).start()

    # The service worker has to be served from the site root (its scope is '/')
    # and without a redirect, so it gets its own public route; otherwise
    # '/<username>' catches it and sends it to the login page.
    def service_worker():
        response = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
        response.headers['Cache-Control'] = 'no-cache'
        return response

    app.add_url_rule('/sw.js', endpoint='service_worker', view_func=service_worker)

    register_auth_routes(app, email_service)
    register_app_icon_routes(app)
    register_admin_routes(app)
    register_feedback_routes(app)
    register_workout_routes(app)
    register_stats_routes(app)
    register_plan_routes(app)

    if csrf is not None:
        try:
            shortcut_log_view = app.view_functions.get('shortcut_log')
            if shortcut_log_view is not None:
                csrf.exempt(shortcut_log_view)
        except Exception:
            logger.error("Failed to exempt shortcut_log from CSRF", exc_info=True)

    @app.template_filter('url_encode')
    def url_encode_filter(s):
        return urllib.parse.quote(str(s))

    @app.template_filter('format_date')
    def format_date_filter(date_obj):
        """Display dates as dd-mm-yyyy (day first). Accepts datetime, date, or YYYY-MM-DD string."""
        d = None
        if isinstance(date_obj, datetime):
            d = date_obj.date()
        elif isinstance(date_obj, date):
            d = date_obj
        elif isinstance(date_obj, str):
            s = date_obj.strip()
            if len(s) >= 10:
                try:
                    d = datetime.strptime(s[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass
        if d is not None:
            return d.strftime('%d-%m-%Y')
        return str(date_obj)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        Session.remove()

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/shortcut/log/') or request.path.startswith('/shortcut/pick/'):
            # A shortcut link without its key. Answer in the shortcut's own format, so the
            # shortcut shows this message instead of treating the site as unreachable.
            return jsonify({
                'ok': False,
                'error': SHORTCUT_KEY_MISSING,
                'server': deployment_name(request.host),
            }), 404
        return render_template(
            'error.html',
            error_code=404,
            error_message="Page not found",
            error_detail="That page doesn't exist, or it has moved.",
        ), 404

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        try:
            if request.path.startswith('/api/'):
                return (
                    jsonify({
                        'ok': False,
                        'error': 'CSRF token missing or invalid. Refresh the page and try again.',
                    }),
                    400,
                )
        except Exception:
            pass
        return render_template(
            'error.html',
            error_code=400,
            error_message="This page is out of date",
            error_detail="Nothing was saved. Go back, refresh the page and try again.",
        ), 400

    @app.errorhandler(413)
    def too_large(error):
        limit_mb = int((app.config.get('MAX_CONTENT_LENGTH') or 0) / (1024 * 1024))
        message = f"That's more than {limit_mb} MB. Please pick a smaller file."
        if request.path.startswith('/api/') or request.path.startswith('/shortcut/'):
            return jsonify({'ok': False, 'error': message}), 413
        return render_template(
            'error.html',
            error_code=413,
            error_message="That file is too large",
            error_detail=message,
        ), 413

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}", exc_info=True)
        Session.rollback()
        return (
            render_template(
                'error.html',
                error_code=500,
                error_message="Something went wrong",
                error_detail="That didn't work on our side. Please try again in a moment.",
            ),
            500,
        )

    return app
