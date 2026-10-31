import time

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from PIL import Image

from services.admin import AdminError, AdminService
from services.email_queue import email_queue
from services.feedback import FeedbackService
from utils.profile_images import delete_profile_image
from utils.logger import logger

from .decorators import require_admin


def register_admin_routes(app):
    def _is_allowed_icon(filename):
        if not filename or '.' not in filename:
            return False
        ext = filename.rsplit('.', 1)[1].lower()
        return ext in {'png', 'jpg', 'jpeg', 'webp'}

    def _validate_image_file(file_storage):
        """Validate image file content and size, not just extension."""
        try:
            # Check file size (limit to 10MB)
            file_storage.seek(0, 2)  # Seek to end
            file_size = file_storage.tell()
            file_storage.seek(0)  # Reset to beginning
            
            if file_size > 10 * 1024 * 1024:  # 10MB limit
                raise ValueError("File size exceeds 10MB limit")
            
            # Validate actual image content using PIL
            image = Image.open(file_storage.stream)
            
            # Verify it's actually an image by trying to load it
            image.verify()
            
            # Reset stream for further processing
            file_storage.seek(0)
            
            # Check image dimensions (reasonable limits)
            image = Image.open(file_storage.stream)
            width, height = image.size
            
            if width > 4096 or height > 4096:
                raise ValueError("Image dimensions too large (max 4096x4096)")
            
            if width < 16 or height < 16:
                raise ValueError("Image dimensions too small (min 16x16)")
            
            # Reset stream again
            file_storage.seek(0)
            
            return True
            
        except Exception as e:
            logger.warning(f"Image validation failed: {e}")
            return False

    def _save_app_icon(file_storage):
        # Validate the image file first
        if not _validate_image_file(file_storage):
            raise ValueError("Invalid image file")

        app.extensions['app_icon_store'].save(Image.open(file_storage.stream))

    def send_deletion_email_async(user_info):
        """Queue deletion email for reliable delivery."""
        if not user_info.get('email'):
            return
        
        try:
            email_queue.enqueue(
                'account_deletion',
                email=user_info['email'],
                username=user_info['username'],
                admin_message=user_info['deletion_reason'],
                admin_username=user_info['admin_username']
            )
        except Exception as exc:
            logger.error(f"Failed to queue deletion email: {exc}", exc_info=True)

    @require_admin
    def admin_dashboard():
        try:
            users = AdminService.get_all_users()
            stats = AdminService.get_user_count()
            try:
                feedback_counts = FeedbackService.counts()
            except Exception as e:
                logger.warning(f"Could not count feedback: {e}")
                feedback_counts = {'total': 0, 'new': 0}

            return render_template(
                'admin_dashboard.html',
                users=users,
                stats=stats,
                feedback_counts=feedback_counts,
            )
        except Exception as e:
            logger.error(f"Admin dashboard error: {e}", exc_info=True)
            flash("Error loading admin dashboard.", "error")
            return redirect(url_for('user_dashboard', username=current_user.username))

    @require_admin
    def admin_coach():
        from models import CoachAnswer, Session
        from services import coach_answers

        show = request.args.get('show', 'all')
        if show not in ('all', 'down', 'up', 'unrated'):
            show = 'all'
        limit = 100
        ratings = [r for (r,) in Session.query(CoachAnswer.rating).all()]
        sources = [s for (s,) in Session.query(CoachAnswer.source).all()]
        totals = {
            'answers': len(ratings),
            'up': ratings.count(1),
            'down': ratings.count(-1),
            'rules': sources.count('rules'),
        }
        return render_template(
            'admin_coach.html',
            totals=totals,
            models=coach_answers.model_summary(Session),
            answers=coach_answers.recent(Session, show=show, limit=limit),
            show=show,
            limit=limit,
        )

    @require_admin
    def admin_delete_user():
        try:
            start = time.perf_counter()
            user_id = int(request.form.get('user_id'))
            deletion_reason = request.form.get('deletion_reason', '').strip()

            logger.info(
                f"Admin delete requested: admin_user_id={current_user.id} target_user_id={user_id}"
            )

            if not deletion_reason:
                flash("Deletion reason is required.", "error")
                return redirect(url_for('admin_dashboard'))

            delete_start = time.perf_counter()
            user_info = AdminService.delete_user(
                admin_user_id=current_user.id,
                target_user_id=user_id,
                deletion_reason=deletion_reason,
            )
            logger.info(
                f"Admin delete DB step completed in {time.perf_counter() - delete_start:.3f}s"
            )

            send_deletion_email_async(user_info)
            # Their photo sits in storage at a public address: remove it with the account.
            try:
                delete_profile_image(user_info.get('profile_image'))
            except Exception as exc:
                logger.warning(f"Could not delete profile photo of deleted user: {exc}")

            logger.info(f"Admin delete request finished in {time.perf_counter() - start:.3f}s")

            flash(f"Deleted {user_info['username']}.", "success")

        except AdminError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Delete user error: {e}", exc_info=True)
            flash("An error occurred while deleting the user.", "error")

        return redirect(url_for('admin_dashboard'))

    @require_admin
    def admin_cleanup_duplicates():
        try:
            summary = AdminService.cleanup_duplicate_users(current_user.id)
            if summary['groups'] == 0:
                flash("No duplicate accounts found to clean up.", "info")
            else:
                flash(
                    (
                        "Cleanup complete: "
                        f"{summary['groups']} group(s) processed, "
                        f"{summary['deleted']} duplicate(s) removed, "
                        f"{summary['logs_moved']} log(s) merged."
                    ),
                    "success",
                )
        except AdminError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Duplicate cleanup error: {e}", exc_info=True)
            flash("Failed to clean up duplicate accounts.", "error")

        return redirect(url_for('admin_dashboard'))

    @require_admin
    def admin_update_app_icon():
        icon_file = request.files.get('app_icon')

        if not icon_file or not icon_file.filename:
            flash("Please choose an image file to upload.", "error")
            return redirect(url_for('admin_dashboard'))

        if not _is_allowed_icon(icon_file.filename):
            flash("Unsupported file type. Use PNG, JPG, JPEG, or WebP.", "error")
            return redirect(url_for('admin_dashboard'))

        try:
            _save_app_icon(icon_file)
            flash(
                "App icon updated everywhere. Phones keep the old one until the app is removed and added to the Home Screen again.",
                "success",
            )
        except ValueError as e:
            flash(f"Invalid image file: {str(e)}", "error")
        except Exception as e:
            logger.error(f"App icon update failed: {e}", exc_info=True)
            flash("Failed to update app icon. Please try again.", "error")

        return redirect(url_for('admin_dashboard'))

    app.add_url_rule('/admin', endpoint='admin_dashboard', view_func=admin_dashboard, methods=['GET'])
    app.add_url_rule('/admin/coach', endpoint='admin_coach', view_func=admin_coach, methods=['GET'])
    app.add_url_rule(
        '/admin/delete-user',
        endpoint='admin_delete_user',
        view_func=admin_delete_user,
        methods=['POST'],
    )
    app.add_url_rule(
        '/admin/cleanup-duplicates',
        endpoint='admin_cleanup_duplicates',
        view_func=admin_cleanup_duplicates,
        methods=['POST'],
    )
    app.add_url_rule(
        '/admin/app-icon',
        endpoint='admin_update_app_icon',
        view_func=admin_update_app_icon,
        methods=['POST'],
    )
