import os
import hashlib
import threading
import time
from flask import jsonify, request
from sqlalchemy.exc import OperationalError
from config import Config
from models import initialize_database
from utils.logger import logger
from wait_for_db import wait_for_db
from workout_tracker import create_app


logger.info("Importing app module (Flask app factory).")
app = create_app(init_db=False)

@app.route('/health')
def health_check():
    git_env_keys = (
        "RAILWAY_GIT_COMMIT_SHA",
        "RAILWAY_GIT_COMMIT",
        "GIT_COMMIT_SHA",
        "GIT_COMMIT",
        "COMMIT_SHA",
        "SOURCE_VERSION",
        "VERCEL_GIT_COMMIT_SHA",
    )
    git_sha = None
    for k in git_env_keys:
        v = os.environ.get(k)
        if v:
            git_sha = v
            break


    def _sha256_file(path: str) -> str | None:
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    base_dir = os.path.dirname(os.path.abspath(__file__))
    app_py_hash = _sha256_file(os.path.join(base_dir, "app.py"))
    gemini_py_hash = _sha256_file(os.path.join(base_dir, "services", "gemini.py"))

    return (
        jsonify(
            {
                "status": "ok",
                "db_ready": bool(app.config.get("DB_READY")),
                # Only the kind of error: the full text (in the log) can name the database host,
                # its address and user, and this answer is public.
                "db_init_last_error": (app.config.get("DB_INIT_LAST_ERROR") or "").split(":", 1)[0] or None,
                "git_sha": git_sha,
                "app_py_sha256": app_py_hash,
                "services_gemini_py_sha256": gemini_py_hash,
            }
        ),
        200,
    )


@app.before_request
def require_db_ready_for_requests():
    if request.path == '/health':
        return None
    if request.path.startswith(('/static/', '/app-icon/')) or request.path in ('/favicon.ico', '/sw.js'):
        return None
    if app.config.get("DB_READY", False):
        return None
    # After a cold start the database is usually ready within seconds, so hold
    # the request instead of answering "warming up" (a Shortcut would save that
    # text, and a browser would need a manual refresh).
    deadline = time.monotonic() + float(os.environ.get("WARMUP_WAIT_SECONDS", "20"))
    while time.monotonic() < deadline:
        time.sleep(0.25)
        if app.config.get("DB_READY", False):
            return None
    status = 200 if request.path in ('/', '/favicon.ico') else 503
    if request.method == 'GET' and request.accept_mimetypes.accept_html:
        page = (
            '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="refresh" content="3"><title>Starting up</title>'
            '<p style="font-family:system-ui;text-align:center;margin-top:40vh">'
            'Starting up, this page will reload by itself…</p>'
        )
        return page, status, {"Retry-After": "3"}
    return "Service warming up", status, {"Retry-After": "3"}


# Application entry point
if __name__ == '__main__':
    try:
        logger.info("Starting app.py __main__ boot sequence.")
        app.config["DB_READY"] = False
        init_retries = int(os.environ.get("DB_INIT_RETRIES", "5"))
        init_delay = float(os.environ.get("DB_INIT_DELAY", "3"))
        wait_timeout = int(os.environ.get("DB_WAIT_TIMEOUT", "120"))
        wait_interval = float(os.environ.get("DB_WAIT_INTERVAL", "2"))

        def _init_db_in_background():
            attempt = 0
            while True:
                attempt += 1
                if init_retries > 0 and attempt > init_retries:
                    logger.critical("Database initialization failed after all retries")
                    return
                try:
                    wait_for_db(wait_timeout, wait_interval)
                    initialize_database()
                    app.config["DB_READY"] = True
                    app.config.pop("DB_INIT_LAST_ERROR", None)
                    logger.info("Database initialized successfully")
                    return
                except OperationalError as exc:
                    app.config["DB_INIT_LAST_ERROR"] = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Database not ready (attempt %s/%s): %s",
                        attempt,
                        init_retries,
                        exc,
                        exc_info=True,
                    )
                    time.sleep(init_delay)
                except Exception as exc:
                    app.config["DB_INIT_LAST_ERROR"] = f"{type(exc).__name__}: {exc}"
                    logger.critical(
                        "Database initialization failed (attempt %s/%s): %s",
                        attempt,
                        init_retries,
                        exc,
                        exc_info=True,
                    )
                    time.sleep(init_delay)

        threading.Thread(target=_init_db_in_background, daemon=True).start()

        port = Config.PORT
        host = Config.HOST
        debug = Config.DEBUG

        logger.info(f"Starting Liftbook on {host}:{port} (debug={debug})")
        app.run(host=host, port=port, debug=debug, threaded=True)
    except Exception as e:
        logger.critical(f"Failed to start application: {e}", exc_info=True)
        raise
