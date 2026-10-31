from datetime import datetime
import html
import re
import csv
import io
import json

from flask import Response, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc

from models import Session, WorkoutLog
from services.stats import (
    _normalize_exercise_name,
    stats_vocabulary,
    backfill_log_bodyweight,
    get_average_growth_data,
    get_chart_data,
    get_csv_export,
    get_export_log_count,
    get_overall_progress_data,
    get_json_export,
    get_stats_exercise_view_counts,
    get_stats_preferences,
    record_stats_exercise_view,
    set_stats_preferences,
)
from services.bodyweight import backfill_bodyweight_log_flags
from utils.dates import local_date
from utils.logger import logger
from utils.validators import sanitize_text_input


def register_stats_routes(app):
    def _parse_export_date_range():
        start_raw = (request.args.get('start_date') or '').strip()
        end_raw = (request.args.get('end_date') or '').strip()

        if not start_raw and not end_raw:
            return None, None

        if not start_raw or not end_raw:
            raise ValueError("Please provide both start and end dates.")

        try:
            start_date = datetime.strptime(start_raw, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_raw, '%Y-%m-%d').date()
        except ValueError as exc:
            raise ValueError("Invalid date format. Use YYYY-MM-DD.") from exc

        if end_date < start_date:
            raise ValueError("End date cannot be earlier than start date.")

        return start_date, end_date

    @login_required
    def stats_index():
        user = current_user

        try:
            updated = backfill_log_bodyweight(Session, user)
            updated += backfill_bodyweight_log_flags(Session, user.id)
            if updated:
                Session.commit()
            logs = (
                Session.query(WorkoutLog)
                .filter_by(user_id=user.id)
                .order_by(desc(WorkoutLog.date))
                .all()
            )

            # Sessions (distinct days) and last trained day per exercise, for sorting.
            usage_by_key = {}
            key_by_name = {}
            vocabulary = stats_vocabulary({log.exercise for log in logs})
            for log in logs:
                if log.exercise not in key_by_name:
                    key_by_name[log.exercise] = _normalize_exercise_name(log.exercise, vocabulary)
                key = key_by_name[log.exercise]
                if not key or not log.date:
                    continue
                usage_by_key.setdefault(key, set()).add(local_date(log.date))

            views_by_key = get_stats_exercise_view_counts(Session, user)
            exercises = sorted({log.exercise for log in logs if log.exercise})
            exercise_options = []
            seen_keys = set()
            for ex in exercises:
                cleaned = re.sub(r'^\s*\d+\s*[\.)]\s*', '', ex).strip()
                label = cleaned or ex
                key = _normalize_exercise_name(label, vocabulary)
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                days = usage_by_key.get(key) or set()
                exercise_options.append({
                    'value': label,
                    'label': label,
                    'sessions': len(days),
                    'views': views_by_key.get(key, 0),
                    'last': max(days).isoformat() if days else '',
                })

            initial_exercise = ""
            initial_exercise_label = ""
            requested_exercise = (request.args.get("exercise") or "").strip()
            if requested_exercise:
                requested_exercise = html.unescape(sanitize_text_input(
                    requested_exercise,
                    max_length=100,
                ))
                requested_key = _normalize_exercise_name(requested_exercise, vocabulary)
                for option in exercise_options:
                    if _normalize_exercise_name(option.get("value") or "", vocabulary) == requested_key:
                        initial_exercise = option.get("value") or requested_exercise
                        initial_exercise_label = option.get("label") or initial_exercise
                        break
                if not initial_exercise:
                    initial_exercise = requested_exercise
                    initial_exercise_label = requested_exercise

            bw_exercises = []
            if user.bodyweight is None and logs:
                bw_exercises = sorted({
                    log.exercise
                    for log in logs
                    if 'bw' in (getattr(log, 'exercise_string', '') or '').lower()
                    or 'bw' in (log.sets_display or '').lower()
                })

            # (The export sizes are shown on Settings > Your data, which works them out itself;
            # building both exports here on every visit was wasted work.)
            return render_template(
                'stats.html',
                exercise_options=exercise_options,
                initial_exercise=initial_exercise,
                initial_exercise_label=initial_exercise_label,
                bw_exercises=bw_exercises,
                bw_warning_enabled=user.bodyweight is None,
                stats_preferences=get_stats_preferences(Session, user),
            )
        except Exception as e:
            logger.error(f"Error in stats_index: {e}", exc_info=True)
            flash("Error loading statistics.", "error")
            return redirect(url_for('user_dashboard', username=user.username))

    @login_required
    def stats_data(exercise):
        user = current_user

        try:
            exercise = sanitize_text_input(exercise, max_length=100, allow_html=True)
            exercise = html.unescape(exercise)
            updated = backfill_log_bodyweight(Session, user)
            updated += backfill_bodyweight_log_flags(Session, user.id)
            if updated:
                Session.commit()
            try:
                record_stats_exercise_view(Session, user, exercise)
            except Exception as view_error:
                Session.rollback()
                logger.warning(f"Could not record stats exercise view: {view_error}")
            return jsonify(get_chart_data(Session, user, exercise))
        except Exception as e:
            logger.error(f"Error getting stats data: {e}", exc_info=True)
            return jsonify({'error': 'Failed to load data'}), 500

    @login_required
    def stats_average_data():
        user = current_user

        try:
            updated = backfill_log_bodyweight(Session, user)
            updated += backfill_bodyweight_log_flags(Session, user.id)
            if updated:
                Session.commit()

            mode = (request.args.get('mode') or '').strip().lower()
            if mode in {'index', 'rate'}:
                baseline_sessions = request.args.get('baseline_sessions', type=int)
                if baseline_sessions is None:
                    baseline_sessions = request.args.get('baseline_days', type=int) or 5
                min_sessions = request.args.get('min_sessions', type=int) or 3
                fade_start_days = request.args.get('fade_start_days', type=int) or 60
                fade_end_days = request.args.get('fade_end_days', type=int) or 90
                return jsonify(
                    get_overall_progress_data(
                        Session,
                        user,
                        mode=mode,
                        baseline_sessions_target=baseline_sessions,
                        min_sessions=min_sessions,
                        fade_start_days=fade_start_days,
                        fade_end_days=fade_end_days,
                    )
                )

            return jsonify(get_average_growth_data(Session, user))
        except Exception as e:
            logger.error(f"Error getting average stats data: {e}", exc_info=True)
            return jsonify({'error': 'Failed to load data'}), 500

    @login_required
    def save_stats_preferences():
        sort_mode = request.form.get('sort_mode')
        time_range = request.form.get('range')
        sort_mode = sort_mode.strip() if sort_mode is not None else None
        time_range = time_range.strip() if time_range is not None else None
        if sort_mode is None and time_range is None:
            return jsonify({'ok': False, 'error': 'Nothing to save.'}), 400

        try:
            saved = set_stats_preferences(Session, current_user, sort_mode=sort_mode, time_range=time_range)
            return jsonify({'ok': True, **saved})
        except ValueError as e:
            Session.rollback()
            return jsonify({'ok': False, 'error': str(e)}), 400
        except Exception as e:
            Session.rollback()
            logger.error(f"Error saving stats preferences: {e}", exc_info=True)
            return jsonify({'ok': False, 'error': 'Unable to save preferences.'}), 500

    @login_required
    def export_csv():
        user = current_user

        try:
            start_date, end_date = _parse_export_date_range()
            log_count = get_export_log_count(Session, user, start_date=start_date, end_date=end_date)
            if log_count == 0:
                flash("No workouts found in that date range.", "warning")
                return redirect(url_for('data_settings'))
            csv_data = get_csv_export(Session, user, start_date=start_date, end_date=end_date)
            date_suffix = datetime.now().strftime('%Y%m%d')
            if start_date and end_date:
                date_suffix = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
            filename = f"workout_history_{user.username}_{date_suffix}.csv"

            return Response(
                csv_data,
                mimetype='text/csv',
                headers={'Content-disposition': f"attachment; filename={filename}"},
            )
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for('data_settings'))
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}", exc_info=True)
            flash("Couldn't make the export. Please try again.", "error")
            return redirect(url_for('data_settings'))

    @login_required
    def export_json():
        user = current_user

        try:
            start_date, end_date = _parse_export_date_range()
            log_count = get_export_log_count(Session, user, start_date=start_date, end_date=end_date)
            if log_count == 0:
                flash("No workouts found in that date range.", "warning")
                return redirect(url_for('data_settings'))
            data = get_json_export(Session, user, start_date=start_date, end_date=end_date)
            date_suffix = datetime.now().strftime('%Y%m%d')
            if start_date and end_date:
                date_suffix = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
            filename = f"workout_history_{user.username}_{date_suffix}.json"

            return Response(
                json.dumps(data, ensure_ascii=False, indent=2),
                mimetype='application/json',
                headers={'Content-disposition': f"attachment; filename={filename}"},
            )
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for('data_settings'))
        except Exception as e:
            logger.error(f"Error exporting JSON: {e}", exc_info=True)
            flash("Couldn't make the export. Please try again.", "error")
            return redirect(url_for('data_settings'))

    app.add_url_rule('/stats', endpoint='stats_index', view_func=stats_index, methods=['GET'])
    app.add_url_rule(
        '/stats/data/<exercise>',
        endpoint='stats_data',
        view_func=stats_data,
        methods=['GET'],
    )
    app.add_url_rule(
        '/stats/data/average',
        endpoint='stats_average_data',
        view_func=stats_average_data,
        methods=['GET'],
    )
    app.add_url_rule(
        '/stats/preferences',
        endpoint='save_stats_preferences',
        view_func=save_stats_preferences,
        methods=['POST'],
    )
    app.add_url_rule('/export_csv', endpoint='export_csv', view_func=export_csv, methods=['GET'])
    app.add_url_rule('/export_json', endpoint='export_json', view_func=export_json, methods=['GET'])
