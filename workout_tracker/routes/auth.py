from datetime import date, datetime, timedelta
import re
import json
import secrets
from pathlib import Path

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user, current_user
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

from parsers.workout import _WEEKDAY_BEFORE_DATE, workout_parser
from services.logging import handle_workout_log

from config import Config
from models import ExerciseRename, Session, User, UserRole, UserApiKey, WorkoutLog
from services.exercise_rename import (
    exercise_names_for_rename,
    rename_exercise,
    rename_preview,
    validate_rename,
)
from services.bodyweight import (
    backfill_bodyweight_log_flags,
    build_bodyweight_settings_rows,
    bodyweight_exercise_key,
    get_bodyweight_conflict_info,
    matching_logs_for_exercise,
    recalculate_log_metrics,
    set_bodyweight_preference,
)
from services.logging import refresh_best_lift_pointers
from services.stats import get_csv_export, get_json_export, timed_checker
from sqlalchemy import desc
from services.auth import AuthService, AuthenticationError, EmailNotVerifiedError
from utils.errors import ValidationError
from utils.logger import logger
from utils.profile_images import (
    get_local_profile_image_path,
    get_profile_image_url,
    get_r2_bucket_name,
    get_r2_profile_image_client,
    has_r2_profile_image_storage,
    normalize_profile_image_key,
)
from utils.validators import (
    USERNAME_NOT_AVAILABLE, is_reserved_username, is_safe_redirect_url, parse_bodyweight, sanitize_text_input,
    validate_email, validate_username,
)

from .decorators import dev_only, require_admin

import threading
import time
from collections import deque

_RATE_LIMIT_BUCKETS = {}
_RATE_LIMIT_LOCK = threading.Lock()


def _infer_bulk_import_dates(headers, today: date | None = None):
    """
    Assign dates to parsed bulk-import headers.
    Missing years are inferred in pasted order. If a missing-year block would
    land before the previous block, the year rolls forward.
    """
    today = today or datetime.now().date()
    resolved = []

    for idx, header in enumerate(headers or []):
        if not header:
            resolved.append(None)
            continue

        day = int(header["day"])
        month = int(header["month"])

        if header.get("year") is not None:
            try:
                resolved.append(date(int(header["year"]), month, day))
            except ValueError:
                resolved.append(None)
            continue

        prev_date = next((d for d in reversed(resolved) if d is not None), None)
        if prev_date is not None:
            year = prev_date.year
            while True:
                try:
                    candidate = date(year, month, day)
                except ValueError:
                    candidate = None
                    break
                if candidate >= prev_date:
                    break
                year += 1
            resolved.append(candidate)
            continue

        next_explicit = None
        for future in headers[idx + 1:]:
            if future and future.get("year") is not None:
                next_explicit = future
                break

        year = today.year
        if next_explicit is not None:
            next_year = int(next_explicit["year"])
            next_month = int(next_explicit["month"])
            next_day = int(next_explicit["day"])
            year = next_year
            try:
                next_date = date(next_year, next_month, next_day)
                candidate = date(year, month, day)
                if candidate > next_date:
                    year -= 1
            except ValueError:
                pass

        try:
            resolved.append(date(year, month, day))
        except ValueError:
            resolved.append(None)

    return resolved


# set_password reports failure by returning False; the page used to say "updated" regardless.
PASSWORD_NOT_CHANGED = "Your password wasn't changed. Please try again."


def register_auth_routes(app, email_service):
    def _is_safe_redirect_url(target: str) -> bool:
        return is_safe_redirect_url(target, request.host_url)

    def _get_client_ip() -> str:
        forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        if forwarded:
            return forwarded
        return request.remote_addr or 'unknown'

    def _allow_rate_limit(bucket: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with _RATE_LIMIT_LOCK:
            dq = _RATE_LIMIT_BUCKETS.get(bucket)
            if dq is None:
                dq = deque()
                _RATE_LIMIT_BUCKETS[bucket] = dq

            cutoff = now - float(window_seconds)
            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) >= int(limit):
                return False

            dq.append(now)
            return True

    def _is_allowed_profile_image(filename: str) -> bool:
        if not filename or '.' not in filename:
            return False
        ext = filename.rsplit('.', 1)[1].lower()
        return ext in {'png', 'jpg', 'jpeg', 'webp'}

    def _save_profile_image(user_id: int, file_storage) -> str:
        import os
        from io import BytesIO

        filename = secure_filename(file_storage.filename or '')
        if not _is_allowed_profile_image(filename):
            raise AuthenticationError("Unsupported profile image type.")

        image = Image.open(file_storage.stream)
        # Sized before it's decoded: a small file can still unpack into an enormous image.
        width, height = image.size
        if width * height > 40_000_000:
            raise AuthenticationError("That photo is too large. Please pick a smaller one.")
        image = ImageOps.exif_transpose(image)
        image = image.convert('RGB')
        size = 320
        image = ImageOps.fit(image, (size, size), Image.LANCZOS)

        # A fresh name per upload, so the URL changes and no cache (browser,
        # service worker, CDN) can keep showing the previous photo.
        output_name = f"avatars/user_{user_id}_{secrets.token_hex(4)}.png"
        buffer = BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        buffer.seek(0)

        if has_r2_profile_image_storage():
            s3 = get_r2_profile_image_client()
            bucket = get_r2_bucket_name()
            s3.put_object(
                Bucket=bucket,
                Key=output_name,
                Body=buffer,
                ContentType='image/png',
            )
        else:
            local_path = get_local_profile_image_path(output_name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(buffer.getvalue())

        return output_name

    def _delete_profile_image(profile_image: str | None) -> None:
        import os

        if not profile_image:
            return
        key = normalize_profile_image_key(profile_image)
        local_path = get_local_profile_image_path(key)
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
        elif has_r2_profile_image_storage():
            s3 = get_r2_profile_image_client()
            s3.delete_object(Bucket=get_r2_bucket_name(), Key=key)

    def _enforce_rate_limit(action: str, identifier: str | None, limit: int, window_seconds: int) -> None:
        if not app.config.get('ENABLE_RATE_LIMITING', False):
            return

        ip = _get_client_ip()
        buckets = [f"{action}:ip:{ip}"]
        if identifier:
            buckets.append(f"{action}:id:{identifier.strip().lower()}")

        for bucket in buckets:
            if not _allow_rate_limit(bucket, limit=limit, window_seconds=window_seconds):
                raise AuthenticationError("Too many attempts. Please wait and try again.")

    def register():
        if current_user.is_authenticated:
            return redirect(url_for('user_dashboard', username=current_user.username))

        if request.method == 'POST':
            try:
                name = request.form.get('name', '').strip()
                username = request.form.get('username', '').strip()
                email = request.form.get('email', '').strip()
                password = request.form.get('password', '')
                # Each sign-up emails a code to the address given: not a way to fill an inbox.
                _enforce_rate_limit('register', email, limit=10, window_seconds=3600)
                # The page checks this too, but only when its script runs.
                confirm_password = request.form.get('confirm_password')
                if confirm_password is not None and confirm_password != password:
                    raise AuthenticationError("Passwords don't match.")

                user, verification_code = AuthService.register_user(
                    username=username,
                    email=email,
                    password=password,
                    name=name,
                )

                email_sent = email_service.send_otp_email(
                    email=user.email,
                    username=user.username,
                    otp_code=verification_code,
                    purpose='verify_email',
                )

                if not email_sent:
                    logger.warning(f"Failed to send verification email to {email}")
                    flash(
                        "Account created but verification email could not be sent. Please contact support.",
                        "warning",
                    )
                else:
                    flash("Account created. Your code is on its way.", "success")

                session['pending_verification_user_id'] = user.id
                return redirect(url_for('verify_email'))

            except AuthenticationError as e:
                flash(str(e), "error")
                return render_template('register.html', prefill_name=name, prefill_username=username, prefill_email=email)
            except Exception as e:
                logger.error(f"Registration error: {e}", exc_info=True)
                flash("An error occurred during registration. Please try again.", "error")
                return render_template('register.html', prefill_name=name, prefill_username=username, prefill_email=email)

        return render_template('register.html')

    def login():
        if current_user.is_authenticated:
            return redirect(url_for('user_dashboard', username=current_user.username))

        if request.method == 'POST':
            try:
                username_or_email = request.form.get('username_or_email', '').strip()
                password = request.form.get('password', '')
                remember_me = request.form.get('remember_me') == 'on'

                _enforce_rate_limit('login', username_or_email, limit=10, window_seconds=600)

                user = AuthService.authenticate_user(username_or_email, password)

                if not user:
                    flash("Invalid username/email or password.", "error")
                    return render_template('login.html')

                if user.email and user.email.lower() in Config.ADMIN_EMAIL_ALLOWLIST and not user.is_admin():
                    db_user = Session.get(User, user.id)
                    if db_user and not db_user.is_admin():
                        db_user.role = UserRole.ADMIN
                        db_user.updated_at = datetime.now()
                        Session.commit()
                    user.role = UserRole.ADMIN

                login_user(user, remember=remember_me, duration=timedelta(days=Config.REMEMBER_COOKIE_DURATION))

                flash(f"Welcome back, {user.username.title()}!", "success")

                next_page = request.args.get('next')
                if next_page and _is_safe_redirect_url(next_page):
                    return redirect(next_page)
                return redirect(url_for('user_dashboard', username=user.username))

            except EmailNotVerifiedError as e:
                # Signing up on another device (or before the code came) left no way to confirm
                # from here: send a fresh code and go to the page that takes it.
                session['pending_verification_user_id'] = e.user_id
                try:
                    _enforce_rate_limit('email_codes', str(e.user_id), limit=10, window_seconds=600)
                    pending = Session.get(User, e.user_id)
                    # Read before the service runs: it closes the shared session.
                    pending_email, pending_username = pending.email, pending.username
                    code = AuthService.resend_verification_code(e.user_id)
                    sent = email_service.send_otp_email(
                        email=pending_email, username=pending_username, otp_code=code, purpose='verify_email',
                    )
                except AuthenticationError:
                    sent = False
                except Exception as exc:
                    logger.error(f"Sending a confirmation code at sign-in failed: {exc}", exc_info=True)
                    sent = False
                flash("Confirm your email first: we've sent you a new code." if sent
                      else "Confirm your email first with the code we sent you.", "info")
                return redirect(url_for('verify_email'))
            except AuthenticationError as e:
                flash(str(e), "error")
                return render_template('login.html')
            except Exception as e:
                logger.error(f"Login error: {e}", exc_info=True)
                flash("An error occurred during login. Please try again.", "error")
                return render_template('login.html')

        return render_template('login.html')

    def login_otp_request():
        if current_user.is_authenticated:
            return redirect(url_for('user_dashboard', username=current_user.username))

        identifier = ''
        if request.method == 'POST':
            identifier = request.form.get('username_or_email', '').strip()
            try:
                identifier_type = 'email' if '@' in (identifier or '') else 'username'
                logger.info(
                    "Login OTP request received",
                    extra={"identifier_type": identifier_type, "has_identifier": bool(identifier)},
                )
                _enforce_rate_limit('login_otp_request', identifier, limit=5, window_seconds=600)
                otp_payload = AuthService.request_login_otp(identifier)

                email_sent = email_service.send_otp_email(
                    email=otp_payload['email'],
                    username=otp_payload['username'],
                    otp_code=otp_payload['otp_code'],
                    purpose='login_otp',
                )

                if not email_sent:
                    flash("Unable to send login code. Please try again later.", "error")
                    return render_template('request_otp.html', identifier=identifier)

                logger.info(
                    "Login OTP email sent",
                    extra={"user_id": otp_payload.get('id')},
                )

                session['pending_otp_user_id'] = otp_payload['id']
                session['pending_otp_identifier'] = identifier
                session['pending_otp_purpose'] = 'login_otp'

                flash("Login code sent! Check your email.", "success")
                return redirect(url_for('verify_login_otp'))

            except AuthenticationError as e:
                logger.info(
                    "Login OTP request rejected",
                    extra={"reason": str(e)[:120]},
                )
                flash(str(e), "error")
            except Exception as e:
                logger.error(f"OTP login request error: {e}", exc_info=True)
                flash("An error occurred. Please try again.", "error")

        if request.method != 'POST':
            identifier = request.args.get('identifier', '').strip()
            if not identifier:
                session.pop('pending_otp_identifier', None)

        return render_template('request_otp.html', identifier=identifier)

    def verify_login_otp():
        if current_user.is_authenticated:
            return redirect(url_for('user_dashboard', username=current_user.username))

        user_id = session.get('pending_otp_user_id')
        if not user_id:
            flash("No login code requested. Please request a new code.", "error")
            return redirect(url_for('login_otp_request'))

        user = Session.get(User, user_id)
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('login'))

        user_email = user.email

        if request.method == 'POST':
            try:
                otp_code = request.form.get('otp_code', '').strip()

                _enforce_rate_limit('login_otp_verify', str(user_id), limit=15, window_seconds=600)

                if AuthService.verify_otp(user_id, otp_code, 'login_otp', mark_verified=True):
                    session.pop('pending_otp_user_id', None)
                    session.pop('pending_otp_identifier', None)
                    session.pop('pending_otp_purpose', None)

                    verified_user = Session.get(User, user_id)
                    if verified_user and verified_user.email:
                        if verified_user.email.lower() in Config.ADMIN_EMAIL_ALLOWLIST and not verified_user.is_admin():
                            verified_user.role = UserRole.ADMIN
                            verified_user.updated_at = datetime.now()
                            Session.commit()

                    if verified_user:
                        login_user(
                            verified_user,
                            remember=True,
                            duration=timedelta(days=Config.REMEMBER_COOKIE_DURATION),
                        )
                        session['otp_login_verified'] = True
                        session['otp_login_user_id'] = verified_user.id
                        flash("Signed in with a one-time code. Please set a new password.", "success")
                        return redirect(url_for('account_settings') + '#change-password')

                    flash("Login successful. Please sign in again.", "success")
                    return redirect(url_for('login'))

                flash("Invalid code. Please try again.", "error")
            except AuthenticationError as e:
                flash(str(e), "error")
            except Exception as e:
                logger.error(f"OTP login verification error: {e}", exc_info=True)
                flash("An error occurred. Please try again.", "error")

        return render_template(
            'verify_otp.html',
            email=user_email,
            purpose_label='Login',
            resend_url=url_for('resend_login_otp'),
            action_url=url_for('verify_login_otp'),
            expiry_minutes=Config.OTP_TOKEN_EXPIRY_MINUTES,
            back_url=url_for('login_otp_request'),
            back_label='Use a different account',
        )

    def resend_login_otp():
        identifier = session.get('pending_otp_identifier')
        if not identifier:
            flash("Please request a new login code.", "error")
            return redirect(url_for('login_otp_request'))

        try:
            _enforce_rate_limit('login_otp_resend', identifier, limit=5, window_seconds=600)
            otp_payload = AuthService.request_login_otp(identifier)
            email_sent = email_service.send_otp_email(
                email=otp_payload['email'],
                username=otp_payload['username'],
                otp_code=otp_payload['otp_code'],
                purpose='login_otp',
            )

            if not email_sent:
                flash("Unable to resend code. Please try again.", "error")
                return redirect(url_for('verify_login_otp'))

            session['pending_otp_user_id'] = otp_payload['id']
            session['pending_otp_purpose'] = 'login_otp'
            flash("A new login code has been sent.", "success")
        except AuthenticationError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"OTP resend error: {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")

        return redirect(url_for('verify_login_otp'))

    def verify_email():
        redirect_username = None
        if current_user.is_authenticated:
            user_id = current_user.id
            redirect_username = current_user.username
        else:
            user_id = session.get('pending_verification_user_id')
            if not user_id:
                flash("No pending verification found.", "error")
                return redirect(url_for('login'))

        user = Session.get(User, user_id)
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('register'))

        user_email = user.email
        user_username = user.username

        if user.is_verified:
            flash("Email already verified.", "info")
            if current_user.is_authenticated:
                return redirect(url_for('user_dashboard', username=current_user.username))
            return redirect(url_for('login'))

        if request.method == 'POST':
            try:
                verification_code = request.form.get('verification_code', '').strip()
                # Codes are six digits: without a limit they could simply be tried in turn.
                _enforce_rate_limit('verify_email', str(user_id), limit=15, window_seconds=600)

                if AuthService.verify_email(user_id, verification_code):
                    if not current_user.is_authenticated:
                        try:
                            email_service.send_welcome_email(user_email, user_username)
                        except Exception as exc:
                            logger.error(f"Welcome email failed: {exc}", exc_info=True)

                    session.pop('pending_verification_user_id', None)

                    if current_user.is_authenticated:
                        flash("Email confirmed.", "success")
                        return redirect(url_for('user_dashboard', username=redirect_username))

                    verified_user = Session.get(User, user_id)
                    if verified_user:
                        login_user(
                            verified_user,
                            remember=True,
                            duration=timedelta(days=Config.REMEMBER_COOKIE_DURATION),
                        )
                        flash("Email confirmed. You're signed in.", "success")
                        return redirect(url_for('user_dashboard', username=verified_user.username))

                    flash("Email confirmed. Please sign in.", "success")
                    return redirect(url_for('login'))

                flash("Invalid verification code. Please try again.", "error")

            except AuthenticationError as e:
                flash(str(e), "error")
            except Exception as e:
                logger.error(f"Verification error: {e}", exc_info=True)
                flash("An error occurred. Please try again.", "error")

        return render_template(
            'verify_email.html',
            email=user_email,
            expiry_hours=Config.VERIFICATION_TOKEN_EXPIRY,
        )

    def resend_verification():
        if current_user.is_authenticated:
            user_id = current_user.id
        else:
            user_id = session.get('pending_verification_user_id')
            if not user_id:
                flash("No pending verification found.", "error")
                return redirect(url_for('login'))

        try:
            user = Session.get(User, user_id)
            if not user:
                flash("User not found.", "error")
                return redirect(url_for('register'))

            user_email = user.email
            user_username = user.username

            _enforce_rate_limit('email_codes', str(user_id), limit=10, window_seconds=600)
            verification_code = AuthService.resend_verification_code(user_id)

            email_sent = email_service.send_otp_email(
                email=user_email,
                username=user_username,
                otp_code=verification_code,
                purpose='verify_email',
            )

            if email_sent:
                flash("Verification code resent! Please check your email.", "success")
            else:
                flash("Failed to send verification email. Please try again later.", "error")

        except AuthenticationError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Resend verification error: {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")

        return redirect(url_for('verify_email'))

    @login_required
    def logout():
        # Everything this browser held for the account goes: a code sign-in's "no current
        # password needed" pass, pending email or password changes, save notes. Cleared before
        # logout_user(), which then marks the remember-me cookie for removal (clearing after it
        # would drop that mark and the cookie would sign them straight back in).
        session.clear()
        logout_user()
        flash("Logged out.", "info")
        return redirect(url_for('login'))

    @login_required
    def user_settings():
        user = current_user
        user_id = user.id
        user_email = user.email
        otp_login_verified = (
            session.get('otp_login_verified')
            and session.get('otp_login_user_id') == user.id
        )
        password_change_verified = (
            session.get('password_change_verified')
            and session.get('password_change_user_id') == user.id
        )
        pending_password_change = (
            session.get('pending_password_change')
            and session.get('password_change_user_id') == user.id
        )
        allow_otp_profile = otp_login_verified or password_change_verified

        if request.method == 'POST':
            form_type = request.form.get('form_type') or 'profile'

            try:
                if form_type == 'add_api_key':
                    account_label = request.form.get('account_label', '').strip()
                    api_key = request.form.get('api_key', '').strip()
                    if not api_key:
                        flash("Please enter an API key.", "error")
                        return redirect(url_for('integrations_settings'))

                    if account_label and len(account_label) > 100:
                        flash("Account label is too long.", "error")
                        return redirect(url_for('integrations_settings'))

                    existing_key = (
                        Session.query(UserApiKey)
                        .filter_by(user_id=user_id, api_key=api_key)
                        .first()
                    )
                    if existing_key:
                        flash("That API key is already saved.", "info")
                        return redirect(url_for('integrations_settings'))

                    Session.add(
                        UserApiKey(
                            user_id=user_id,
                            api_key=api_key,
                            account_label=account_label or None,
                        )
                    )
                    Session.commit()
                    flash("Key added.", "success")
                    return redirect(url_for('integrations_settings'))

                if form_type == 'delete_api_key':
                    key_id = request.form.get('key_id')
                    key = (
                        Session.query(UserApiKey)
                        .filter_by(id=key_id, user_id=user_id)
                        .first()
                    )
                    if not key:
                        flash("API key not found.", "error")
                        return redirect(url_for('integrations_settings'))

                    Session.delete(key)
                    Session.commit()
                    flash("API key removed.", "success")
                    return redirect(url_for('integrations_settings'))

                if form_type == 'profile_photo':
                    image_file = request.files.get('profile_image')
                    if not image_file or not image_file.filename:
                        flash("Please choose a profile photo to upload.", "error")
                        return redirect(url_for('account_settings'))

                    if not _is_allowed_profile_image(image_file.filename):
                        flash("Unsupported file type. Use PNG, JPG, or WEBP.", "error")
                        return redirect(url_for('account_settings'))

                    try:
                        old_image = user.profile_image
                        user.profile_image = _save_profile_image(user.id, image_file)
                        user.updated_at = datetime.now()
                        Session.commit()
                        if old_image and old_image != user.profile_image:
                            try:
                                _delete_profile_image(old_image)
                            except Exception as e:
                                logger.warning(f"Could not delete old profile photo {old_image}: {e}")
                        flash("Photo updated.", "success")
                    except AuthenticationError as e:
                        Session.rollback()
                        flash(str(e), "error")
                    except Exception as e:
                        Session.rollback()
                        logger.error(f"Profile photo update failed: {e}", exc_info=True)
                        flash("Failed to update profile photo. Please try again.", "error")
                    return redirect(url_for('account_settings'))

                if form_type == 'remove_photo':
                    try:
                        _delete_profile_image(user.profile_image)
                        user.profile_image = None
                        user.updated_at = datetime.now()
                        Session.commit()
                        flash("Photo removed.", "success")
                    except Exception as e:
                        Session.rollback()
                        logger.error(f"Profile photo removal failed: {e}", exc_info=True)
                        flash("Failed to remove profile photo. Please try again.", "error")
                    return redirect(url_for('account_settings'))

                if form_type == 'bodyweight':
                    try:
                        user.bodyweight = parse_bodyweight(request.form.get('bodyweight', ''))
                        user.updated_at = datetime.now()
                        Session.commit()
                        flash("Bodyweight updated.", "success")
                    except ValidationError as e:
                        flash(str(e), "error")
                    except Exception as e:
                        Session.rollback()
                        logger.error(f"Bodyweight update failed: {e}", exc_info=True)
                        flash("Failed to update bodyweight. Please try again.", "error")
                    return redirect(url_for('user_settings'))

                if form_type == 'bulk_workouts':
                    raw_text = request.form.get('bulk_workouts_text', '') or ''
                    raw_text = raw_text.strip()

                    if not raw_text:
                        flash('Paste your bulk workout text first.', 'error')
                        return redirect(url_for('data_settings'))

                    lines = [ln.rstrip() for ln in raw_text.splitlines()]

                    header_re = re.compile(r'^\s*(\d{1,2})\s*/\s*(\d{1,2})\b')
                    blocks = []
                    current = []
                    for line in lines:
                        if header_re.match(line) and current:
                            blocks.append("\n".join(current).strip())
                            current = [line]
                        else:
                            current.append(line)
                    if current:
                        blocks.append("\n".join(current).strip())

                    blocks = [b for b in blocks if b.strip()]
                    if not blocks:
                        flash('No workout days found. Make sure each day starts with a date like 03/02.', 'error')
                        return redirect(url_for('data_settings'))

                    successes = []
                    skipped = []
                    failures = []

                    for block in blocks:
                        parsed = None
                        try:
                            parsed = workout_parser(block, bodyweight=user.bodyweight, preserve_bodyweight_offsets=True)
                        except Exception as e:
                            parsed = None

                        if not parsed or not parsed.get('date'):
                            first_line = (block.splitlines()[0] if block.splitlines() else '').strip()
                            failures.append(f"{first_line or 'Unknown day'}: could not parse")
                            continue

                        workout_dt = parsed['date']
                        workout_date = workout_dt.date()
                        start_dt = datetime.combine(workout_date, datetime.min.time())
                        end_dt = start_dt + timedelta(days=1)

                        conflict = (
                            Session.query(WorkoutLog)
                            .filter_by(user_id=user.id)
                            .filter(WorkoutLog.date >= start_dt)
                            .filter(WorkoutLog.date < end_dt)
                            .first()
                        )
                        if conflict:
                            skipped.append(workout_date.strftime('%Y-%m-%d'))
                            continue

                        parsed['date'] = start_dt

                        try:
                            handle_workout_log(Session, user, parsed)
                            Session.commit()
                            successes.append(workout_date.strftime('%Y-%m-%d'))
                        except Exception as e:
                            Session.rollback()
                            failures.append(f"{workout_date.strftime('%Y-%m-%d')}: {str(e)}")

                    if successes:
                        flash(f"Imported {len(successes)} workout day(s).", 'success')
                    if skipped:
                        flash(
                            f"Skipped {len(skipped)} day(s) because they already exist: {', '.join(skipped[:6])}{'…' if len(skipped) > 6 else ''}",
                            'info',
                        )
                    if failures:
                        flash(
                            f"Failed to import {len(failures)} day(s): {failures[0]}",
                            'error',
                        )

                    return redirect(url_for('data_settings'))

                if form_type in {'profile', 'profile_otp'}:
                    full_name = sanitize_text_input(request.form.get('full_name', ''), max_length=100)
                    username = sanitize_text_input(request.form.get('username', ''), max_length=30)
                    email = sanitize_text_input(request.form.get('email', ''), max_length=255)
                    current_password = request.form.get('current_password', '')
                    bodyweight = user.bodyweight
                    try:
                        typed_bodyweight = parse_bodyweight(request.form.get('bodyweight', ''))
                    except ValidationError as e:
                        flash(str(e), "error")
                        return redirect(url_for('account_settings'))
                    if typed_bodyweight is not None:
                        bodyweight = typed_bodyweight

                    if not username or not email:
                        flash("Username and email are required.", "error")
                        return redirect(url_for('account_settings'))

                    if form_type == 'profile':
                        if not current_password and not allow_otp_profile:
                            flash("Please enter your current password to update profile details.", "error")
                            return redirect(url_for('account_settings'))

                        if current_password and not AuthService.verify_password(current_password, user.password_hash):
                            raise AuthenticationError("Current password is incorrect")

                    username = validate_username(username)
                    if username != (user.username or '').lower() and (
                            is_reserved_username(username)
                            or Session.query(User).filter(User.email == username, User.id != user_id).first()):
                        flash(USERNAME_NOT_AVAILABLE, "error")
                        return redirect(url_for('account_settings'))
                    # As at sign-up: a typo like "alice@@example" is caught here, not when the
                    # codes can't be sent.
                    email = validate_email(email)

                    existing_username = (
                        Session.query(User)
                        .filter(User.username == username, User.id != user_id)
                        .first()
                    )
                    if existing_username:
                        flash("That username is already taken.", "error")
                        return redirect(url_for('account_settings'))

                    existing_email = (
                        Session.query(User)
                        .filter(User.email == email.lower(), User.id != user_id)
                        .first()
                    )
                    if existing_email:
                        flash("That email is already in use.", "error")
                        return redirect(url_for('account_settings'))

                    email = email.lower()
                    email_changed = email != (user_email or '').lower()
                    username_changed = username != user.username

                    if (
                        form_type == 'profile'
                        and not current_password
                        and allow_otp_profile
                        and (username_changed or email_changed)
                    ):
                        flash("Please enter your current password to update your username or email.", "error")
                        return redirect(url_for('account_settings'))

                    if email_changed:
                        session['pending_email_change'] = {
                            'full_name': full_name,
                            'username': username,
                            'email': email,
                            'current_email': user_email,
                            'bodyweight': bodyweight,
                        }
                        session['pending_email_change_user_id'] = user_id

                        _enforce_rate_limit('email_codes', str(user_id), limit=10, window_seconds=600)
                        otp_payload = AuthService.request_email_change_otps(
                            user_id,
                            current_email=user_email,
                            new_email=email,
                        )
                        old_email_sent = email_service.send_otp_email(
                            email=otp_payload['current_email'],
                            username=otp_payload['username'],
                            otp_code=otp_payload['otp_old'],
                            purpose='change_email_old',
                        )
                        new_email_sent = email_service.send_otp_email(
                            email=otp_payload['new_email'],
                            username=otp_payload['username'],
                            otp_code=otp_payload['otp_new'],
                            purpose='change_email_new',
                        )

                        if old_email_sent and new_email_sent:
                            flash("Two verification codes were sent to your old and new emails.", "info")
                            return redirect(url_for('verify_email_change_otp'))

                        flash("Unable to send email change codes. Please try again.", "error")
                        return redirect(url_for('account_settings'))

                    if form_type == 'profile_otp':
                        session['pending_profile_update'] = {
                            'full_name': full_name,
                            'username': username,
                            'email': email,
                            'bodyweight': bodyweight,
                        }
                        _enforce_rate_limit('email_codes', str(user.id), limit=10, window_seconds=600)
                        otp_payload = AuthService.request_profile_update_otp(user.id)
                        email_sent = email_service.send_otp_email(
                            email=otp_payload['email'],
                            username=otp_payload['username'],
                            otp_code=otp_payload['otp_code'],
                            purpose='profile_update',
                        )
                        if email_sent:
                            flash("One-time code sent to your email.", "info")
                            return redirect(url_for('verify_profile_update_otp'))
                        flash("Couldn't send the code. Please try again.", "error")
                        return redirect(url_for('account_settings'))

                    user.full_name = full_name if full_name else None
                    user.username = username
                    user.email = email
                    if bodyweight is not None:
                        user.bodyweight = bodyweight
                    user.updated_at = datetime.now()
                    if email in Config.ADMIN_EMAIL_ALLOWLIST and not user.is_admin():
                        user.role = UserRole.ADMIN

                    Session.commit()

                    flash("Profile updated.", "success")
                    return redirect(url_for('account_settings'))

                if form_type == 'password':
                    current_password = request.form.get('current_password', '')
                    new_password = request.form.get('new_password', '')
                    confirm_password = request.form.get('confirm_password', '')

                    if new_password != confirm_password:
                        flash("New password and confirmation do not match.", "error")
                        return redirect(url_for('account_settings') + '#change-password')

                    if otp_login_verified or password_change_verified:
                        if not AuthService.set_password(user.id, new_password):
                            raise AuthenticationError(PASSWORD_NOT_CHANGED)
                        session.pop('otp_login_verified', None)
                        session.pop('otp_login_user_id', None)
                        session.pop('password_change_verified', None)
                        session.pop('password_change_user_id', None)
                        flash("Password updated.", "success")
                        return redirect(url_for('account_settings'))

                    if not current_password:
                        flash("Enter your current password, or sign in with a code instead.", "error")
                        return redirect(url_for('account_settings') + '#change-password')

                    if not AuthService.verify_password(current_password, user.password_hash):
                        raise AuthenticationError("Current password is incorrect")

                    if not AuthService.set_password(user.id, new_password):
                        raise AuthenticationError(PASSWORD_NOT_CHANGED)
                    flash("Password updated.", "success")
                    return redirect(url_for('account_settings'))

                if form_type == 'delete_account':
                    # Confirmed with the username typed out and the password (or a
                    # code sign-in, for someone who forgot it).
                    _enforce_rate_limit('delete_account', str(user.id), limit=10, window_seconds=600)
                    if (request.form.get('confirm_username') or '').strip().lower() != (user.username or '').lower():
                        flash("Type your username exactly as shown to confirm.", "error")
                        return redirect(url_for('account_settings') + '#delete-account')
                    if not (otp_login_verified or password_change_verified) and not AuthService.verify_password(
                            request.form.get('current_password', ''), user.password_hash):
                        flash("That password isn't right.", "error")
                        return redirect(url_for('account_settings') + '#delete-account')
                    photo = getattr(user, 'profile_image', None)
                    username = user.username
                    AuthService.delete_account(user.id)
                    try:
                        _delete_profile_image(photo)  # in storage, not the database
                    except Exception as exc:
                        logger.warning(f"Could not delete the profile photo of a deleted account: {exc}")
                    logger.info(f"User {username} deleted their own account")
                    session.clear()
                    logout_user()
                    flash("Your account and all your workouts were deleted.", "info")
                    return redirect(url_for('login'))

                if form_type == 'password_otp_request':
                    _enforce_rate_limit('email_codes', str(user.id), limit=10, window_seconds=600)
                    otp_payload = AuthService.request_password_change_otp(user.id)
                    email_sent = email_service.send_otp_email(
                        email=otp_payload['email'],
                        username=otp_payload['username'],
                        otp_code=otp_payload['otp_code'],
                        purpose='change_password',
                    )

                    if email_sent:
                        session['pending_password_change'] = True
                        session['password_change_user_id'] = user.id
                        flash("A verification code was sent to your email.", "info")
                        return redirect(url_for('account_settings') + '#change-password')

                    flash("Unable to send a verification code. Please try again.", "error")
                    return redirect(url_for('account_settings') + '#change-password')

                if form_type == 'password_otp':
                    otp_code = request.form.get('otp_code', '').strip()
                    new_password = request.form.get('new_password', '')
                    confirm_password = request.form.get('confirm_password', '')

                    if not pending_password_change:
                        flash("Ask for a code first, then enter it here.", "error")
                        return redirect(url_for('account_settings') + '#change-password')

                    if not otp_code:
                        flash("Please enter the one-time code.", "error")
                        return redirect(url_for('account_settings') + '#change-password')

                    if new_password != confirm_password:
                        flash("New password and confirmation do not match.", "error")
                        return redirect(url_for('account_settings') + '#change-password')

                    _enforce_rate_limit('change_password_verify', str(user.id), limit=15, window_seconds=600)
                    if AuthService.verify_otp(user.id, otp_code, 'change_password'):
                        if not AuthService.set_password(user.id, new_password):
                            raise AuthenticationError(PASSWORD_NOT_CHANGED)
                        session.pop('pending_password_change', None)
                        session.pop('password_change_user_id', None)
                        session.pop('otp_login_verified', None)
                        session.pop('otp_login_user_id', None)
                        session.pop('password_change_verified', None)
                        session.pop('password_change_user_id', None)
                        flash("Password updated.", "success")
                        return redirect(url_for('account_settings'))

                    flash("Invalid code. Please try again.", "error")
                    return redirect(url_for('account_settings') + '#change-password')

                if form_type == 'password_otp_cancel':
                    session.pop('pending_password_change', None)
                    session.pop('password_change_user_id', None)
                    flash("OTP password change cancelled.", "info")
                    return redirect(url_for('account_settings') + '#change-password')

                flash("Invalid settings request.", "error")
                return redirect(url_for('user_settings'))
            except (AuthenticationError, ValidationError) as e:
                Session.rollback()
                flash(str(e), "error")
                return redirect(url_for('user_settings'))
            except Exception as e:
                Session.rollback()
                logger.error(f"Settings update error: {e}", exc_info=True)
                flash("Failed to update settings. Please try again.", "error")
                return redirect(url_for('user_settings'))

        profile_image_url = get_profile_image_url(getattr(user, 'profile_image', None))
        try:
            if backfill_bodyweight_log_flags(Session, user.id):
                Session.commit()
        except Exception as e:
            Session.rollback()
            logger.error(f"Bodyweight log backfill failed: {e}", exc_info=True)

        return render_template(
            'settings.html',
            user=user,
            profile_image_url=profile_image_url,
        )

    @login_required
    def account_settings():
        user = current_user
        user_id = user.id
        otp_login_verified = session.get('otp_login_verified') and session.get('otp_login_user_id') == user_id
        password_change_verified = session.get('password_change_verified') and session.get('password_change_user_id') == user_id
        pending_password_change = session.get('pending_password_change') and session.get('password_change_user_id') == user_id
        profile_image_url = get_profile_image_url(getattr(user, 'profile_image', None))
        return render_template(
            'settings_account.html',
            user=user,
            profile_image_url=profile_image_url,
            otp_login_verified=otp_login_verified,
            password_change_verified=password_change_verified,
            pending_password_change=pending_password_change,
        )

    @login_required
    def data_settings():
        user = current_user
        csv_size_kb = 0
        json_size_kb = 0
        try:
            logs = (
                Session.query(WorkoutLog)
                .filter_by(user_id=user.id)
                .order_by(desc(WorkoutLog.date))
                .all()
            )
            if logs:
                # Both exports ask "is this exercise timed?" once per name between them.
                is_timed = timed_checker(Session, user)
                csv_data = get_csv_export(Session, user, is_timed=is_timed)
                csv_bytes = csv_data.encode('utf-8')
                csv_size_kb = (len(csv_bytes) + 1023) // 1024

                json_payload = get_json_export(Session, user, is_timed=is_timed)
                json_bytes = json.dumps(json_payload, ensure_ascii=False, indent=2).encode('utf-8')
                json_size_kb = (len(json_bytes) + 1023) // 1024
        except Exception as e:
            logger.error(f"Error computing export sizes: {e}", exc_info=True)

        return render_template(
            'settings_data.html',
            user=user,
            csv_size_kb=csv_size_kb,
            json_size_kb=json_size_kb,
        )

    @login_required
    def integrations_settings():
        user = current_user
        user_api_keys = (
            Session.query(UserApiKey)
            .filter_by(user_id=user.id)
            .order_by(UserApiKey.created_at.desc())
            .all()
        )
        from services.ai_coach import key_provider

        return render_template(
            'settings_integrations.html',
            user=user,
            user_api_keys=user_api_keys,
            key_providers={k.id: ("Groq" if key_provider(k.api_key) == "groq" else "Gemini") for k in user_api_keys},
        )

    @login_required
    def more_settings():
        user = current_user
        pending_bodyweight = None

        try:
            if backfill_bodyweight_log_flags(Session, user.id):
                Session.commit()
        except Exception as e:
            Session.rollback()
            logger.error(f"Bodyweight log backfill failed: {e}", exc_info=True)

        if request.method == 'POST':
            form_type = request.form.get('form_type') or ''
            try:
                if form_type == 'bodyweight_exercise':
                    exercise_name = sanitize_text_input(
                        request.form.get('exercise_name', ''),
                        max_length=160,
                    )
                    enabled_raw = (request.form.get('is_bodyweight') or '').strip().lower()
                    is_enabled = enabled_raw in {'1', 'true', 'yes', 'on'}
                    resolution = (request.form.get('history_resolution') or '').strip()

                    if not exercise_name or not bodyweight_exercise_key(exercise_name):
                        flash("Choose a valid exercise.", "error")
                        return redirect(url_for('more_settings') + '#bodyweight-exercises')

                    if not is_enabled:
                        conflict = get_bodyweight_conflict_info(Session, user.id, exercise_name)
                        if conflict.get("has_conflict") and resolution not in {'future_only', 'keep_offsets', 'literal'}:
                            pending_bodyweight = {
                                "exercise": exercise_name,
                                "conflict": conflict,
                            }
                        else:
                            logs_to_refresh = matching_logs_for_exercise(Session, user.id, exercise_name)
                            if resolution in {'keep_offsets', 'literal'}:
                                for log in logs_to_refresh:
                                    log.uses_bodyweight = (resolution == 'keep_offsets')
                                    recalculate_log_metrics(Session, log)
                            set_bodyweight_preference(
                                Session,
                                user.id,
                                exercise_name,
                                False,
                                source="manual",
                            )
                            refresh_best_lift_pointers(Session, user, [exercise_name])
                            Session.commit()
                            flash("Bodyweight exercise setting updated.", "success")
                            return redirect(url_for('more_settings') + '#bodyweight-exercises')
                    else:
                        set_bodyweight_preference(
                            Session,
                            user.id,
                            exercise_name,
                            True,
                            source="manual",
                        )
                        Session.commit()
                        flash("Bodyweight exercise setting updated.", "success")
                        return redirect(url_for('more_settings') + '#bodyweight-exercises')
                else:
                    flash("Invalid settings request.", "error")
                    return redirect(url_for('more_settings'))
            except Exception as e:
                Session.rollback()
                logger.error(f"More settings update error: {e}", exc_info=True)
                flash("Failed to update more settings. Please try again.", "error")
                return redirect(url_for('more_settings'))

        bodyweight_rows = build_bodyweight_settings_rows(Session, user.id)
        return render_template(
            'more_settings.html',
            user=user,
            bodyweight_rows=bodyweight_rows,
            pending_bodyweight=pending_bodyweight,
        )

    @login_required
    def exercise_names_settings():
        """Rename an exercise and keep its history: pick it, type the new name, confirm."""
        user = current_user
        if request.method == 'POST':
            old_name = sanitize_text_input(request.form.get('old_name', ''), max_length=160)
            new_name = sanitize_text_input(request.form.get('new_name', ''), max_length=160)
            try:
                rename_exercise(Session, user, old_name, new_name)
            except ValueError as e:
                flash(str(e), "error")
                return redirect(url_for('exercise_names_settings'))
            except Exception as e:
                Session.rollback()
                logger.error(f"Exercise rename failed: {e}", exc_info=True)
                flash("Couldn't rename that right now. Please try again.", "error")
                return redirect(url_for('exercise_names_settings'))
            flash(f"Renamed to {new_name.strip()}. Its history came along.", "success")
            return redirect(url_for('exercise_names_settings'))

        old_name = (request.args.get('from') or '').strip()
        new_name = (request.args.get('to') or '').strip()
        preview = None
        error = None
        if old_name or new_name:
            error = validate_rename(old_name, new_name)
            if not error:
                preview = rename_preview(Session, user, old_name, new_name)
        renames = (
            Session.query(ExerciseRename)
            .filter(ExerciseRename.user_id == user.id)
            .order_by(ExerciseRename.created_at.desc())
            .all()
        )
        return render_template(
            'settings_exercise_names.html',
            exercise_names=exercise_names_for_rename(Session, user),
            old_name=old_name,
            new_name=new_name,
            preview=preview,
            error=error,
            renames=renames,
        )

    @login_required
    def verify_profile_update_otp():
        pending_update = session.get('pending_profile_update')
        if not pending_update:
            flash("No pending profile update found.", "error")
            return redirect(url_for('user_settings'))

        user_id = current_user.id
        user = Session.get(User, user_id)
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('login'))

        user_email = user.email

        if request.method == 'POST':
            try:
                otp_code = request.form.get('otp_code', '').strip()
                _enforce_rate_limit('profile_update_verify', str(user_id), limit=15, window_seconds=600)

                if AuthService.verify_otp(user_id, otp_code, 'profile_update'):
                    full_name = pending_update.get('full_name')
                    username = pending_update.get('username')
                    email = pending_update.get('email')
                    bodyweight = pending_update.get('bodyweight')

                    if not username or not email:
                        flash("Missing profile update details.", "error")
                        return redirect(url_for('user_settings'))

                    username = validate_username(username)
                    if username != (user.username or '').lower() and (
                            is_reserved_username(username)
                            or Session.query(User).filter(User.email == username, User.id != user_id).first()):
                        flash(USERNAME_NOT_AVAILABLE, "error")
                        return redirect(url_for('user_settings'))
                    existing_username = (
                        Session.query(User)
                        .filter(User.username == username, User.id != user_id)
                        .first()
                    )
                    if existing_username:
                        flash("That username is already taken.", "error")
                        return redirect(url_for('user_settings'))

                    existing_email = (
                        Session.query(User)
                        .filter(User.email == email.lower(), User.id != user_id)
                        .first()
                    )
                    if existing_email:
                        flash("That email is already in use.", "error")
                        return redirect(url_for('user_settings'))

                    email = email.lower()
                    email_changed = email != (user_email or '').lower()

                    if email_changed:
                        session['pending_profile_update'] = {
                            'full_name': full_name,
                            'username': username,
                            'email': email,
                            'bodyweight': bodyweight,
                        }
                        session['pending_email_change'] = {
                            'full_name': full_name,
                            'username': username,
                            'email': email,
                            'current_email': user_email,
                            'bodyweight': bodyweight,
                        }
                        session['pending_email_change_user_id'] = user_id

                        _enforce_rate_limit('email_codes', str(user_id), limit=10, window_seconds=600)
                        otp_payload = AuthService.request_email_change_otps(
                            user_id,
                            current_email=user_email,
                            new_email=email,
                        )
                        old_email_sent = email_service.send_otp_email(
                            email=otp_payload['current_email'],
                            username=otp_payload['username'],
                            otp_code=otp_payload['otp_old'],
                            purpose='change_email_old',
                        )
                        new_email_sent = email_service.send_otp_email(
                            email=otp_payload['new_email'],
                            username=otp_payload['username'],
                            otp_code=otp_payload['otp_new'],
                            purpose='change_email_new',
                        )

                        session.pop('pending_profile_update', None)

                        if old_email_sent and new_email_sent:
                            flash("Two verification codes were sent to your old and new emails.", "info")
                            return redirect(url_for('verify_email_change_otp'))

                        flash("Unable to send email change codes. Please try again.", "error")
                        return redirect(url_for('user_settings'))

                    user = Session.get(User, user_id)
                    if not user:
                        flash("User not found.", "error")
                        return redirect(url_for('login'))

                    user.full_name = full_name if full_name else None
                    user.username = username
                    user.email = email
                    if bodyweight is not None:
                        user.bodyweight = bodyweight
                    user.updated_at = datetime.now()
                    if email in Config.ADMIN_EMAIL_ALLOWLIST and not user.is_admin():
                        user.role = UserRole.ADMIN

                    Session.commit()
                    session.pop('pending_profile_update', None)
                    session.pop('pending_profile_update_user_id', None)

                    flash("Profile updated.", "success")
                    return redirect(url_for('user_settings'))

                flash("Invalid code. Please try again.", "error")
            except AuthenticationError as e:
                flash(str(e), "error")
            except Exception as e:
                Session.rollback()
                logger.error(f"Profile OTP verification error: {e}", exc_info=True)
                flash("Failed to verify code. Please try again.", "error")

        return render_template(
            'verify_otp.html',
            email=user_email,
            purpose_label='Profile Update',
            resend_url=url_for('resend_profile_update_otp'),
            action_url=url_for('verify_profile_update_otp'),
            expiry_minutes=Config.OTP_TOKEN_EXPIRY_MINUTES,
            back_url=url_for('user_settings'),
            back_label='Back to settings',
        )

    @login_required
    def verify_password_change_otp():
        if not session.get('pending_password_change'):
            flash("No password change requested.", "error")
            return redirect(url_for('user_settings'))

        if session.get('password_change_user_id') != current_user.id:
            flash("Password change verification mismatch.", "error")
            return redirect(url_for('user_settings'))

        user = Session.get(User, current_user.id)
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('login'))

        user_email = user.email

        if request.method == 'POST':
            try:
                otp_code = request.form.get('otp_code', '').strip()
                _enforce_rate_limit('change_password_verify', str(user.id), limit=15, window_seconds=600)

                if AuthService.verify_otp(user.id, otp_code, 'change_password'):
                    session['password_change_verified'] = True
                    session['password_change_user_id'] = user.id
                    session.pop('pending_password_change', None)
                    flash("Code verified. Please enter your new password.", "success")
                    return redirect(url_for('account_settings') + '#change-password')

                flash("Invalid code. Please try again.", "error")
            except AuthenticationError as e:
                flash(str(e), "error")
            except Exception as e:
                logger.error(f"Password change OTP verification error: {e}", exc_info=True)
                flash("Failed to verify code. Please try again.", "error")

        return render_template(
            'verify_otp.html',
            email=user_email,
            purpose_label='Change Password',
            resend_url=url_for('resend_password_change_otp'),
            action_url=url_for('verify_password_change_otp'),
            expiry_minutes=Config.OTP_TOKEN_EXPIRY_MINUTES,
            back_url=url_for('account_settings'),
            back_label='Back to account',
        )

    @login_required
    def resend_password_change_otp():
        try:
            _enforce_rate_limit('email_codes', str(current_user.id), limit=10, window_seconds=600)
            otp_payload = AuthService.request_password_change_otp(current_user.id)
            email_sent = email_service.send_otp_email(
                email=otp_payload['email'],
                username=otp_payload['username'],
                otp_code=otp_payload['otp_code'],
                purpose='change_password',
            )

            if email_sent:
                session['pending_password_change'] = True
                session['password_change_user_id'] = current_user.id
                flash("A new code has been sent to your email.", "success")
            else:
                flash("Unable to resend code. Please try again.", "error")
        except AuthenticationError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Password change OTP resend error: {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")

        return redirect(url_for('verify_password_change_otp'))

    @login_required
    def verify_email_change_otp():
        pending_change = session.get('pending_email_change')
        if not pending_change:
            flash("No pending email change found.", "error")
            return redirect(url_for('user_settings'))

        if session.get('pending_email_change_user_id') != current_user.id:
            flash("Email change verification mismatch.", "error")
            return redirect(url_for('user_settings'))

        user = Session.get(User, current_user.id)
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('login'))

        user_email = user.email
        current_email = pending_change.get('current_email') or user_email
        new_email = pending_change.get('email') or ''

        if request.method == 'POST':
            try:
                otp_old = request.form.get('otp_code_old', '').strip()
                otp_new = request.form.get('otp_code_new', '').strip()

                if not otp_old or not otp_new:
                    flash("Please enter both codes.", "error")
                    return redirect(url_for('verify_email_change_otp'))

                _enforce_rate_limit('change_email_verify', str(user.id), limit=15, window_seconds=600)
                # Check both before spending either: a typo in one code used to spend the other,
                # so the retry with both right was refused until new codes were sent.
                old_valid = AuthService.verify_otp(user.id, otp_old, 'change_email_old', use=False)
                new_valid = AuthService.verify_otp(user.id, otp_new, 'change_email_new', use=False)
                if old_valid and new_valid:
                    old_valid = AuthService.verify_otp(user.id, otp_old, 'change_email_old')
                    new_valid = AuthService.verify_otp(user.id, otp_new, 'change_email_new')

                if old_valid and new_valid:
                    full_name = pending_change.get('full_name')
                    username = pending_change.get('username')
                    email = pending_change.get('email')

                    if not username or not email:
                        flash("Missing email change details.", "error")
                        return redirect(url_for('user_settings'))

                    user = Session.get(User, current_user.id)
                    if not user:
                        flash("User not found.", "error")
                        return redirect(url_for('login'))

                    user.full_name = full_name if full_name else None
                    user.username = username
                    user.email = email.lower()
                    bodyweight = pending_change.get('bodyweight')
                    if bodyweight is not None:
                        user.bodyweight = bodyweight
                    user.is_verified = True
                    user.updated_at = datetime.now()
                    if user.email in Config.ADMIN_EMAIL_ALLOWLIST and not user.is_admin():
                        user.role = UserRole.ADMIN

                    Session.commit()

                    session.pop('pending_email_change', None)
                    session.pop('pending_email_change_user_id', None)

                    flash("Email updated.", "success")
                    return redirect(url_for('user_settings'))

                flash("Invalid codes. Please try again.", "error")
            except AuthenticationError as e:
                flash(str(e), "error")
            except Exception as e:
                Session.rollback()
                logger.error(f"Email change OTP verification error: {e}", exc_info=True)
                flash("Failed to verify codes. Please try again.", "error")

        return render_template(
            'verify_email_change_otp.html',
            current_email=current_email,
            new_email=new_email,
            resend_url=url_for('resend_email_change_otp'),
            action_url=url_for('verify_email_change_otp'),
            expiry_minutes=Config.OTP_TOKEN_EXPIRY_MINUTES,
        )

    @login_required
    def resend_email_change_otp():
        pending_change = session.get('pending_email_change')
        if not pending_change:
            flash("No pending email change found.", "error")
            return redirect(url_for('user_settings'))

        try:
            _enforce_rate_limit('email_codes', str(current_user.id), limit=10, window_seconds=600)
            otp_payload = AuthService.request_email_change_otps(
                current_user.id,
                current_email=pending_change.get('current_email'),
                new_email=pending_change.get('email'),
            )

            old_email_sent = email_service.send_otp_email(
                email=otp_payload['current_email'],
                username=otp_payload['username'],
                otp_code=otp_payload['otp_old'],
                purpose='change_email_old',
            )
            new_email_sent = email_service.send_otp_email(
                email=otp_payload['new_email'],
                username=otp_payload['username'],
                otp_code=otp_payload['otp_new'],
                purpose='change_email_new',
            )

            if old_email_sent and new_email_sent:
                flash("New codes have been sent to both email addresses.", "success")
            else:
                flash("Unable to resend codes. Please try again.", "error")
        except AuthenticationError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Email change OTP resend error: {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")

        return redirect(url_for('verify_email_change_otp'))

    @login_required
    def resend_profile_update_otp():
        pending_update = session.get('pending_profile_update')
        if not pending_update:
            flash("No pending profile update found.", "error")
            return redirect(url_for('user_settings'))

        try:
            _enforce_rate_limit('email_codes', str(current_user.id), limit=10, window_seconds=600)
            otp_payload = AuthService.request_profile_update_otp(current_user.id)
            email_sent = email_service.send_otp_email(
                email=otp_payload['email'],
                username=otp_payload['username'],
                otp_code=otp_payload['otp_code'],
                purpose='profile_update',
            )

            if email_sent:
                flash("A new code has been sent to your email.", "success")
            else:
                flash("Unable to resend code. Please try again.", "error")
        except AuthenticationError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Profile OTP resend error: {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")

        return redirect(url_for('verify_profile_update_otp'))

    @login_required
    def bulk_import():
        user = current_user

        if request.method == 'POST':
            raw_text = request.form.get('bulk_workouts_text', '') or ''
            raw_text = raw_text.strip()
            confirm_import = (request.form.get('confirm_import') or '').strip() == '1'

            if not raw_text:
                flash('Paste your bulk workout text first.', 'error')
                return render_template('bulk_import.html', prefill='')

            lines = [ln.rstrip() for ln in raw_text.splitlines()]

            month_map = {
                "jan": 1, "january": 1,
                "feb": 2, "february": 2,
                "mar": 3, "march": 3,
                "apr": 4, "april": 4,
                "may": 5,
                "jun": 6, "june": 6,
                "jul": 7, "july": 7,
                "aug": 8, "august": 8,
                "sep": 9, "sept": 9, "september": 9,
                "oct": 10, "october": 10,
                "nov": 11, "november": 11,
                "dec": 12, "december": 12,
            }

            def _parse_year(y_str: str | None):
                if not y_str:
                    return None
                try:
                    y = int(y_str)
                except Exception:
                    return None
                return 2000 + y if y < 100 else y

            def _try_parse_date_header(line: str):
                s = (line or "").strip()
                if not s or s.startswith("#"):
                    return None
                # "Monday 28/9 ...", "Tue, 29 Sep ...": the weekday in front of a date.
                weekday = _WEEKDAY_BEFORE_DATE.match(s)
                if weekday:
                    s = s[weekday.end():]

                # yyyy-mm-dd, as exports from other apps write it
                m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?=\s|$|[-–—:,])", s)
                if m:
                    return {"day": int(m.group(3)), "month": int(m.group(2)), "year": int(m.group(1)),
                            "year_str": m.group(1)}

                # dd.mm.yy / dd-mm-yyyy: only with a year, so a weight like "12.5" isn't 12 May
                m = re.match(r"^(\d{1,2})[.\-](\d{1,2})[.\-](\d{2}|\d{4})(?=\s|$|[-–—:,])", s)
                if m:
                    return {"day": int(m.group(1)), "month": int(m.group(2)), "year": _parse_year(m.group(3)),
                            "year_str": m.group(3)}

                # dd/mm[/yy]
                m = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?", s)
                if m:
                    day = int(m.group(1))
                    month = int(m.group(2))
                    year = _parse_year(m.group(3))
                    return {"day": day, "month": month, "year": year, "year_str": m.group(3)}

                # dd Mon [yy] e.g. "20 nov - ..." / "11 Jan 24 - ..."
                m = re.match(
                    r"^\s*(\d{1,2})\s*([A-Za-z]{3,9})\b(?:\.|)?\s*(\d{2,4})?",
                    s,
                    flags=re.IGNORECASE,
                )
                if m:
                    day = int(m.group(1))
                    # A month's name or its short form only: "3 Decline Press" isn't 3 December.
                    mo = month_map.get((m.group(2) or "").lower())
                    if not mo:
                        return None
                    year = _parse_year(m.group(3))
                    return {"day": day, "month": mo, "year": year, "year_str": m.group(3)}

                return None

            # Build (block_text, start_line_no, end_line_no, header_components).
            blocks = []
            current = []
            current_start = None
            current_header = None
            for idx, line in enumerate(lines, start=1):
                header = _try_parse_date_header(line)
                if header is not None:
                    if current:
                        blocks.append(("\n".join(current).strip(), current_start, idx - 1, current_header))
                    current = [line]
                    current_start = idx
                    current_header = header
                else:
                    if current:
                        current.append(line)

            if current:
                blocks.append(("\n".join(current).strip(), current_start, len(lines), current_header))

            blocks = [(b, s, e, h) for (b, s, e, h) in blocks if b and b.strip() and h]
            if not blocks:
                flash('No workout days found. Make sure each day starts with a date like 03/02.', 'error')
                return render_template('bulk_import.html', prefill=raw_text)

            from datetime import timedelta
            successes = []
            skipped = []
            skipped_details: list[str] = []
            failures = []
            invalid_exercise_count = 0
            invalid_details: list[str] = []
            date_assumptions: list[str] = []
            ignored_section_details: list[str] = []

            inferred_dates = _infer_bulk_import_dates([block[3] for block in blocks])
            valid_inferred_dates = [d for d in inferred_dates if d is not None]
            detected_date_range = ""
            if valid_inferred_dates:
                first_detected = min(valid_inferred_dates)
                last_detected = max(valid_inferred_dates)
                detected_date_range = (
                    f"{first_detected.strftime('%d-%m-%Y')} to {last_detected.strftime('%d-%m-%Y')}"
                )

            for block_idx, (block, block_start_line, block_end_line, header) in enumerate(blocks):
                parsed = None
                try:
                    parsed = workout_parser(block, bodyweight=user.bodyweight, preserve_bodyweight_offsets=True)
                except Exception:
                    parsed = None

                if not parsed:
                    first_line = (block.splitlines()[0] if block.splitlines() else '').strip()
                    failures.append(
                        f"{first_line or 'Unknown day'} (lines {block_start_line}-{block_end_line}): could not parse"
                    )
                    continue

                workout_date = inferred_dates[block_idx] if block_idx < len(inferred_dates) else None
                if workout_date is None:
                    first_line = (block.splitlines()[0] if block.splitlines() else '').strip()
                    failures.append(
                        f"{first_line or 'Unknown day'} (lines {block_start_line}-{block_end_line}): invalid date header"
                    )
                    continue
                if header.get("year") is None:
                    month_abbr = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
                    in_dd = int(header["day"])
                    in_mm = int(header["month"])
                    assumed_yy = str(workout_date.year)[-2:]
                    date_assumptions.append(
                        f"{in_dd:02d} {month_abbr[in_mm-1]} -> {in_dd:02d}/{in_mm:02d}/{assumed_yy} (lines {block_start_line}-{block_end_line})."
                    )

                # Explicitly report section/comment lines that we ignore (e.g., "#Gym")
                # so you understand why they don't show up as parse issues.
                local_lines = block.splitlines()
                for local_i, raw in enumerate(local_lines):
                    t = (raw or "").strip()
                    if t.startswith("#"):
                        abs_line = block_start_line + local_i
                        snippet = t[:60]
                        ignored_section_details.append(
                            f"{workout_date.strftime('%d-%m-%Y')} (pasted line {abs_line}): ignored section '{snippet}'"
                        )

                start_dt = datetime.combine(workout_date, datetime.min.time())
                end_dt = start_dt + timedelta(days=1)

                conflict = (
                    Session.query(WorkoutLog)
                    .filter_by(user_id=user.id)
                    .filter(WorkoutLog.date >= start_dt)
                    .filter(WorkoutLog.date < end_dt)
                    .first()
                )
                if conflict:
                    skipped.append(workout_date.strftime('%Y-%m-%d'))
                    skipped_details.append(
                        f"{workout_date.strftime('%d-%m-%Y')} (lines {block_start_line}-{block_end_line}): already exists in DB (conflict)."
                    )
                    continue

                parsed['date'] = start_dt

                # Collect per-exercise parse failures (workout-day can still be partially imported).
                invalid_exercises = [
                    ex
                    for ex in (parsed.get("exercises") or [])
                    if not ex.get("valid", True)
                ]

                def _preview(s: str, head_words: int = 4, tail_words: int = 4) -> str:
                    text = re.sub(r"\s+", " ", (s or "").strip())
                    if not text:
                        return ""
                    words = text.split(" ")
                    if len(words) <= (head_words + tail_words):
                        return " ".join(words)
                    head = words[:head_words]
                    tail = words[-tail_words:]
                    return f"{' '.join(head)} … {' '.join(tail)}"

                try:
                    successes.append(workout_date.strftime('%Y-%m-%d'))
                    if confirm_import:
                        handle_workout_log(Session, user, parsed)
                        Session.commit()
                    if invalid_exercises:
                        invalid_exercise_count += len(invalid_exercises)
                        for ex in invalid_exercises:
                            ex_name = (ex.get("name") or "Unknown Exercise").strip()
                            ex_src = ex.get("exercise_string") or ex.get("name") or ""
                            detail = (
                                f"{workout_date.strftime('%Y-%m-%d')}: could not parse "
                                f"\"{ex_name}\" near: \"{_preview(ex_src)}\" "
                                f"(lines {block_start_line}-{block_end_line})"
                            )
                            invalid_details.append(detail)
                except Exception as e:
                    if confirm_import:
                        Session.rollback()
                    failures.append(f"{workout_date.strftime('%Y-%m-%d')}: {str(e)}")

            if confirm_import:
                if successes:
                    flash(f"Imported {len(successes)} workout day(s).", 'success')
                if skipped:
                    flash(
                        f"Skipped {len(skipped)} day(s) (already exist): {', '.join(skipped[:6])}{'…' if len(skipped) > 6 else ''}",
                        'info',
                    )
                if failures:
                    flash(
                        f"Failed to import {len(failures)} day(s): {failures[0]}",
                        'error',
                    )
                if invalid_exercise_count:
                    # Keep flash concise; full details are shown on the page below.
                    flash(
                        f"Note: {invalid_exercise_count} exercise line(s) couldn't be parsed. See details below.",
                        'info',
                    )
                return redirect(url_for('user_dashboard', username=user.username))

            import_feedback = {
                "success_day_count": len(successes),
                "skipped_day_count": len(skipped),
                "failed_day_count": len(failures),
                "invalid_exercise_count": invalid_exercise_count,
                "invalid_details": invalid_details[:20],  # avoid giant pages
                "failed_details": failures[:10],
                "skipped_details": skipped_details[:10],
                "date_assumptions": date_assumptions[:20],
                "detected_date_range": detected_date_range,
                "total_blocks": len(blocks),
                "ignored_section_count": len(ignored_section_details),
                "ignored_section_details": ignored_section_details[:20],
                "preview_mode": not confirm_import,
            }

            return render_template('bulk_import.html', prefill=raw_text, import_feedback=import_feedback)

        return render_template('bulk_import.html', prefill='', import_feedback=None)

    @dev_only
    @require_admin
    def internal_db_fix():
        return (
            "<pre>This endpoint is deprecated. Database schema migrations are now managed by Alembic.\n"
            "Run: alembic upgrade head\n"
            "For an existing database created before Alembic, you may need: alembic stamp head</pre>",
            410,
        )

    app.add_url_rule('/register', endpoint='register', view_func=register, methods=['GET', 'POST'])
    app.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    app.add_url_rule('/login/otp', endpoint='login_otp_request', view_func=login_otp_request, methods=['GET', 'POST'])
    app.add_url_rule('/login/otp/verify', endpoint='verify_login_otp', view_func=verify_login_otp, methods=['GET', 'POST'])
    app.add_url_rule('/login/otp/resend', endpoint='resend_login_otp', view_func=resend_login_otp, methods=['POST'])
    app.add_url_rule('/verify-email', endpoint='verify_email', view_func=verify_email, methods=['GET', 'POST'])
    app.add_url_rule('/resend-verification', endpoint='resend_verification', view_func=resend_verification, methods=['POST'])
    app.add_url_rule('/logout', endpoint='logout', view_func=logout, methods=['GET'])
    app.add_url_rule('/settings', endpoint='user_settings', view_func=user_settings, methods=['GET', 'POST'])
    app.add_url_rule('/settings/account', endpoint='account_settings', view_func=account_settings, methods=['GET'])
    app.add_url_rule('/settings/data', endpoint='data_settings', view_func=data_settings, methods=['GET'])
    app.add_url_rule('/settings/integrations', endpoint='integrations_settings', view_func=integrations_settings, methods=['GET'])
    app.add_url_rule('/settings/more', endpoint='more_settings', view_func=more_settings, methods=['GET', 'POST'])
    app.add_url_rule(
        '/settings/exercise-names',
        endpoint='exercise_names_settings',
        view_func=exercise_names_settings,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/settings/verify-otp',
        endpoint='verify_profile_update_otp',
        view_func=verify_profile_update_otp,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/settings/otp/resend',
        endpoint='resend_profile_update_otp',
        view_func=resend_profile_update_otp,
        methods=['POST'],
    )
    app.add_url_rule(
        '/settings/password/verify-otp',
        endpoint='verify_password_change_otp',
        view_func=verify_password_change_otp,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/settings/password/resend-otp',
        endpoint='resend_password_change_otp',
        view_func=resend_password_change_otp,
        methods=['POST'],
    )
    app.add_url_rule(
        '/settings/email/verify-otp',
        endpoint='verify_email_change_otp',
        view_func=verify_email_change_otp,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/settings/email/resend-otp',
        endpoint='resend_email_change_otp',
        view_func=resend_email_change_otp,
        methods=['POST'],
    )
    app.add_url_rule('/bulk-import', endpoint='bulk_import', view_func=bulk_import, methods=['GET', 'POST'])
    app.add_url_rule('/internal_db_fix', endpoint='internal_db_fix', view_func=internal_db_fix, methods=['GET'])
