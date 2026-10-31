import os

from flask import abort, flash, redirect, url_for
from flask_login import current_user

from config import Config


def require_admin(f):
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to continue.", "info")
            return redirect(url_for('login'))
        if not current_user.is_admin():
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for('user_dashboard', username=current_user.username))
        return f(*args, **kwargs)

    return decorated_function


def dev_only(f):
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not Config.DEBUG and os.environ.get('ALLOW_INTERNAL_DB_FIX', '').lower() != 'true':
            abort(404)
        return f(*args, **kwargs)

    return decorated_function
