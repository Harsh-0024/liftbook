from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from services.feedback import FEEDBACK_KINDS, MAX_MESSAGE_LENGTH, FeedbackError, FeedbackService
from utils.logger import logger

from .decorators import require_admin


def register_feedback_routes(app):
    @login_required
    def feedback():
        if request.method == 'POST':
            kind = request.form.get('kind', '')
            message = request.form.get('message', '')
            try:
                FeedbackService.submit(current_user.id, kind, message, request.form.get('page', ''))
                flash("Thank you. Your feedback went straight to the developer.", "success")
                return redirect(url_for('feedback'))
            except FeedbackError as e:
                flash(str(e), "error")
            except Exception as e:
                logger.error(f"Feedback submit error: {e}", exc_info=True)
                flash("Couldn't send that. Please try again.", "error")
            # Keep what they wrote.
            return render_template(
                'feedback.html',
                kinds=FEEDBACK_KINDS,
                max_length=MAX_MESSAGE_LENGTH,
                sent=FeedbackService.for_user(current_user.id),
                draft_kind=kind,
                draft_message=message,
                from_page=request.form.get('page', ''),
            )

        return render_template(
            'feedback.html',
            kinds=FEEDBACK_KINDS,
            max_length=MAX_MESSAGE_LENGTH,
            sent=FeedbackService.for_user(current_user.id),
            draft_kind=request.args.get('kind', 'idea'),
            draft_message='',
            from_page=request.args.get('from', ''),
        )

    @require_admin
    def admin_feedback():
        try:
            items = FeedbackService.all_with_users()
            counts = FeedbackService.counts()
        except Exception as e:
            logger.error(f"Admin feedback error: {e}", exc_info=True)
            flash("Error loading feedback.", "error")
            return redirect(url_for('admin_dashboard'))

        page = render_template('admin_feedback.html', items=items, counts=counts, kinds=FEEDBACK_KINDS)
        # Shown once as new; from now on the sender sees it was read.
        try:
            FeedbackService.mark_seen([item['id'] for item in items if item['status'] == 'new'])
        except Exception as e:
            logger.warning(f"Could not mark feedback as seen: {e}")
        return page

    @require_admin
    def admin_feedback_status(feedback_id):
        try:
            FeedbackService.set_status(feedback_id, request.form.get('status', ''))
        except FeedbackError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Feedback status error: {e}", exc_info=True)
            flash("Couldn't update that feedback.", "error")
        return redirect(url_for('admin_feedback', _anchor=f'fb-{feedback_id}'))

    @require_admin
    def admin_feedback_delete(feedback_id):
        try:
            FeedbackService.delete(feedback_id)
            flash("Feedback deleted.", "success")
        except FeedbackError as e:
            flash(str(e), "error")
        except Exception as e:
            logger.error(f"Feedback delete error: {e}", exc_info=True)
            flash("Couldn't delete that feedback.", "error")
        return redirect(url_for('admin_feedback'))

    app.add_url_rule('/feedback', endpoint='feedback', view_func=feedback, methods=['GET', 'POST'])
    app.add_url_rule('/admin/feedback', endpoint='admin_feedback', view_func=admin_feedback, methods=['GET'])
    app.add_url_rule(
        '/admin/feedback/<int:feedback_id>/status',
        endpoint='admin_feedback_status',
        view_func=admin_feedback_status,
        methods=['POST'],
    )
    app.add_url_rule(
        '/admin/feedback/<int:feedback_id>/delete',
        endpoint='admin_feedback_delete',
        view_func=admin_feedback_delete,
        methods=['POST'],
    )
