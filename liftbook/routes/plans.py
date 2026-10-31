from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import login_required, current_user

from list_of_exercise import get_workout_days
from models import Plan, RepRange, Session
from services.retrieve import (
    CUSTOM_PICKER_GROUPS,
    CUSTOM_RETRIEVAL_SORT_MODES,
    exercise_groups_for,
    generate_custom_retrieve_output,
    describe_retrieve_output,
    generate_retrieve_output,
    DEFAULT_CUSTOM_WORKOUT_TITLE,
    get_custom_retrieval_exercise_catalog,
    infer_custom_workout_title,
    get_admin_display_name,
    get_effective_plan_text,
    _build_default_rep_text,
    _get_admin_plan_text,
    _get_admin_rep_ranges_text,
    _own_plan_text,
    _own_rep_ranges_text,
    is_plan_owner,
    picks_for_plan_lines,
    clean_custom_workout_title,
    record_custom_retrieval,
    set_custom_retrieval_sort_preference,
    set_exercise_group_choice,
)
from list_of_exercise import DEFAULT_PLAN, DEFAULT_REP_RANGES
from parsers.workout import _parse_plan_exercise_line
from services.exercise_matching import normalize_exercise_name
from services.exercise_rename import (
    catch_up_with_followed_renames,
    detect_renames,
    plan_exercise_names,
    rename_exercise,
    rename_questions,
    rep_exercise_names,
)
from services.rep_ranges import canonical_rep_text, merge_rep_entries, parse_rep_entries
from utils.logger import logger
from utils.validators import is_safe_redirect_url, sanitize_text_input




def _resolve_custom_retrieval_selection(catalog, selected_keys, two_set_keys):
    """Validate a custom selection against the current catalog and preserve its order."""
    selected_keys = [str(key or '').strip() for key in selected_keys if str(key or '').strip()]
    if not selected_keys:
        raise ValueError('Select at least one exercise.')
    if len(selected_keys) > 30:
        raise ValueError('Select up to 30 exercises at a time.')

    catalog_by_key = {item['key']: item for item in catalog}
    selected_exercises = []
    seen_keys = set()
    for key in selected_keys:
        exercise = catalog_by_key.get(key)
        if not exercise or key in seen_keys:
            raise ValueError('One or more selected exercises are no longer available.')
        seen_keys.add(key)
        selected_exercises.append(exercise['name'])

    two_set_keys = [str(key or '').strip() for key in two_set_keys if str(key or '').strip()]
    if len(set(two_set_keys)) != len(two_set_keys) or any(key not in seen_keys for key in two_set_keys):
        raise ValueError('Invalid set selection.')

    return selected_keys, selected_exercises, two_set_keys


def register_plan_routes(app):
    def _grid_columns(count):
        """Columns for a group on wide screens: whole rows where the count allows it."""
        if count <= 5:
            return max(count, 1)
        for cols in (4, 3, 5):
            if count % cols == 0:
                return cols
        return 4

    def _lay_out_groups(groups):
        """Merge lone single-session groups, then size each grid so no row ends in a gap."""
        singles = [g for g in groups if len(g['items']) == 1]
        if len(singles) > 1:
            merged = {'title': 'Other' if len(singles) < len(groups) else 'Workouts', 'items': [
                {**g['items'][0], 'number': g['title']} for g in singles
            ]}
            first = groups.index(singles[0])
            groups = [g for g in groups if g not in singles]
            groups.insert(first, merged)
        for group in groups:
            count = len(group['items'])
            wide = _grid_columns(count)
            narrow = 1 if count == 1 else 2
            group['wide'], group['narrow'] = wide, narrow
            # The last cell stretches over whatever the last row leaves empty.
            for item in group['items']:
                item['span_wide'] = item['span_narrow'] = 1
            left_wide, left_narrow = count % wide, count % narrow
            if left_wide:
                group['items'][-1]['span_wide'] = wide - left_wide + 1
            if left_narrow:
                group['items'][-1]['span_narrow'] = narrow - left_narrow + 1
        return groups

    def _retrieve_groups(data):
        """Every session in the plan, grouped the way the plan groups them (cycles, or categories)."""
        workout = data.get('workout') if isinstance(data, dict) else None
        workout = workout if isinstance(workout, dict) else {}
        titles = data.get('session_titles') if isinstance(data, dict) else None
        titles = titles if isinstance(titles, dict) else {}
        headings = data.get('headings') if isinstance(data, dict) else None
        heading_sessions = data.get('heading_sessions') if isinstance(data, dict) else None

        def session_item(sid):
            return {
                'number': f"Session {sid}",
                'name': titles.get(str(sid)) or f"Session {sid}",
                'url': url_for('retrieve_final', category='Session', day_id=sid),
            }

        groups = []
        if isinstance(headings, list) and headings and isinstance(heading_sessions, dict) and heading_sessions:
            for heading in headings:
                ids = sorted(int(x) for x in (heading_sessions.get(heading) or []) if str(x).isdigit())
                if ids:
                    groups.append({'title': heading, 'items': [session_item(sid) for sid in ids]})
            return groups

        for category, days in workout.items():
            day_names = list((days or {}).keys())
            items = []
            for index, day_name in enumerate(day_names, start=1):
                if str(category).strip().lower() == 'session':
                    items.append(session_item(index))
                    continue
                exercises = [
                    str(line).split(' - [', 1)[0].strip()
                    for line in ((days or {}).get(day_name) or [])[:2]
                ]
                items.append({
                    'number': f"Day {index}",
                    'name': ', '.join(e for e in exercises if e) or day_name,
                    'url': url_for('retrieve_final', category=category, day_id=index),
                })
            if items:
                title = 'Sessions' if str(category).strip().lower() == 'session' else category
                groups.append({'title': title, 'items': items})
        return groups

    @login_required
    def retrieve_categories():
        user = current_user

        try:
            raw_text = get_effective_plan_text(Session, user)
            groups = _lay_out_groups(_retrieve_groups(get_workout_days(raw_text or "")))
            if not groups:
                flash("No workout plan found. Please set up your plan first.", "info")
                return redirect(url_for('set_plan'))
            return render_template('retrieve.html', groups=groups)
        except Exception as e:
            logger.error(f"Error in retrieve_categories: {e}", exc_info=True)
            flash("Error loading workout categories.", "error")
            return redirect(url_for('user_dashboard', username=user.username))

    @login_required
    def retrieve_heading_days(heading_id: int):
        # Old two-step links: every session is on one page now.
        return redirect(url_for('retrieve_categories'))

    @login_required
    def retrieve_days(category):
        return redirect(url_for('retrieve_categories'))

    def _session_place(data, category, day_id):
        """("Session 9 · Cycle 3", "Chest & Biceps") for the plan page header."""
        titles = data.get('session_titles') if isinstance(data, dict) else None
        if str(category).strip().lower() == 'session':
            name = (titles or {}).get(str(day_id)) if isinstance(titles, dict) else None
            kicker = f"Session {day_id}"
            heading_sessions = data.get('heading_sessions') if isinstance(data, dict) else None
            for heading, ids in (heading_sessions or {}).items():
                if day_id in [int(x) for x in ids if str(x).isdigit()]:
                    kicker += f" · {heading}"
                    break
            return kicker, name or f"Session {day_id}"
        return f"Day {day_id}", category

    def _session_for_edit(plan_days, category, day_id):
        """A plan day being edited as a custom pick, or None if it isn't in the plan (any more)."""
        category = str(category or '').strip()
        try:
            day_id = int(day_id)
        except (TypeError, ValueError):
            return None
        lines = ((plan_days.get('workout') or {}).get(category) or {}).get(f"{category} {day_id}")
        if not category or not lines:
            return None
        kicker, name = _session_place(plan_days, category, day_id)
        number = f"Session {day_id}" if category.lower() == 'session' else ''
        return {
            'category': category, 'day': day_id, 'kicker': kicker, 'lines': list(lines),
            # The part of the title that stays put ("Session 6") and the name after it.
            'number': number, 'name': '' if name == number else name,
        }

    def _session_title(session, name):
        """The title in the copied text: a session keeps its number ("Session 6 - Back & Biceps")."""
        if session['number']:
            return f"{session['number']} - {name}" if name else session['number']
        return name or f"{session['category']} {session['day']}"

    def _edit_url(keys, sets, *, session=None, name=None):
        """The Custom workout page holding this workout, for its Edit button."""
        return url_for(
            'retrieve_custom', e=list(keys), s=[str(n) for n in sets],
            c=session['category'] if session else None, d=session['day'] if session else None,
            n=name or None,
        )

    @login_required
    def retrieve_final(category, day_id):
        user = current_user

        try:
            # Decode HTML entities first, then sanitize
            import html
            category = html.unescape(category)
            category = sanitize_text_input(category, max_length=100)
            category = html.unescape(category)
            
            plan_days = get_workout_days(get_effective_plan_text(Session, user) or "")
            if f"{category} {day_id}" not in ((plan_days.get("workout") or {}).get(category) or {}):
                # An old link after the plan changed: say so, rather than offering to copy an error.
                flash(f"{category} {day_id} isn't in your plan any more.", "error")
                return redirect(url_for('retrieve_categories'))
            output, exercise_count, set_count = generate_retrieve_output(Session, user, category, day_id)
            kicker, title = _session_place(plan_days, category, day_id)
            session = _session_for_edit(plan_days, category, day_id)
            picks = picks_for_plan_lines(Session, user, session['lines']) if session else []
            return render_template(
                'retrieve_plan.html',
                output=output,
                plan=describe_retrieve_output(output),
                exercise_count=exercise_count,
                set_count=set_count,
                kicker=kicker,
                title=title,
                back_url=url_for('retrieve_categories'),
                title_value=session['name'] if session else title,
                title_number=session['number'] if session else '',
                title_fallback='',
                edit_url=_edit_url([k for k, _ in picks], [n for _, n in picks], session=session) if picks else None,
            )
        except Exception as e:
            logger.error(f"Error in retrieve_final: {e}", exc_info=True)
            flash("Couldn't make that workout. Please try again.", "error")
            return redirect(url_for('retrieve_categories'))

    def _custom_picker_groups(catalog):
        """The picker's muscle groups, each in two parts: what you train often (A-Z), then
        "Less often": your other exercises, then the rest (each A-Z)."""
        groups = {name: [] for name in CUSTOM_PICKER_GROUPS}
        for item in catalog:
            groups.setdefault(item.get('group') or 'Other', []).append(item)
        # Empty groups are kept (hidden) so an exercise can be moved into them.
        laid_out = []
        for name, items in groups.items():
            items = sorted(items, key=lambda i: (not i.get('yours'), i['name'].casefold()))
            laid_out.append({
                'name': name,
                'items': items,
                'often': [i for i in items if i.get('often')],
                'rest': [i for i in items if not i.get('often')],
            })
        return laid_out

    def _custom_set_overrides(selected_keys, two_set_keys, set_counts):
        """The sets shown on the page for each exercise, so the plan says exactly what the picker did."""
        overrides = {}
        if set_counts and len(set_counts) == len(selected_keys):
            for key, raw in zip(selected_keys, set_counts):
                try:
                    count = int(raw)
                except (TypeError, ValueError):
                    raise ValueError('Invalid set selection.')
                if not 1 <= count <= 10:
                    raise ValueError('Invalid set selection.')
                overrides[key] = count
            return overrides
        # Older pages sent only the exercises switched to two sets.
        for key in two_set_keys:
            overrides[key] = 2
        return overrides

    @login_required
    def retrieve_custom():
        user = current_user

        try:
            catalog = get_custom_retrieval_exercise_catalog(Session, user, sort_mode='alpha_asc')
            if not catalog:
                flash("No exercises are available to retrieve yet.", "info")
                return redirect(url_for('set_plan'))

            if request.method == 'GET':
                # From a workout's Edit button: its exercises and sets, and for a plan
                # session which one it is and its name.
                by_key = {item['key']: item for item in catalog}
                keys, counts = request.args.getlist('e'), request.args.getlist('s')
                preset, seen = [], set()
                for i, key in enumerate(keys):
                    if key not in by_key or key in seen or len(preset) >= 30:
                        continue
                    seen.add(key)
                    try:
                        count = int(counts[i])
                    except (IndexError, ValueError):
                        count = by_key[key]['default_sets']
                    preset.append({'key': key, 'sets': min(10, max(1, count))})
                session = None
                if request.args.get('c') and request.args.get('d'):
                    plan_days = get_workout_days(get_effective_plan_text(Session, user) or "")
                    session = _session_for_edit(plan_days, request.args.get('c'), request.args.get('d'))
                # Back returns to the workout this came from.
                back_url = url_for('retrieve_categories')
                referrer = request.referrer or ''
                if preset and is_safe_redirect_url(referrer, request.host_url) and '/retrieve/' in referrer:
                    back_url = referrer
                elif session:
                    back_url = url_for('retrieve_final', category=session['category'], day_id=session['day'])
                return render_template(
                    'retrieve_custom.html',
                    groups=_custom_picker_groups(catalog),
                    exercises=catalog,
                    preset=preset,
                    edit_session=session,
                    workout_name=clean_custom_workout_title(request.args.get('n')),
                    back_url=back_url,
                )

            try:
                selected_keys, _, two_set_keys = _resolve_custom_retrieval_selection(
                    catalog,
                    request.form.getlist('exercise'),
                    request.form.getlist('two_set_exercise'),
                )
                set_counts = request.form.getlist('set_count')
                _custom_set_overrides(selected_keys, two_set_keys, set_counts)
            except ValueError as error:
                flash(str(error), 'error')
                return redirect(url_for('retrieve_custom'))

            from_session = bool(request.form.get('c') and request.form.get('d'))
            if not from_session:
                try:
                    record_custom_retrieval(Session, user, selected_keys)
                except Exception as e:
                    Session.rollback()
                    logger.warning(f"Unable to record custom retrieval history: {e}", exc_info=True)

            # The plan is its own page, so refreshing or coming back to it doesn't ask to
            # send the form again (or count the pick twice).
            return redirect(url_for(
                'retrieve_custom_plan',
                e=selected_keys,
                s=set_counts or None,
                t=two_set_keys or None,
                c=request.form.get('c') if from_session else None,
                d=request.form.get('d') if from_session else None,
                n=clean_custom_workout_title(request.form.get('n')) or None,
            ))
        except Exception as e:
            logger.error(f"Error generating custom workout: {e}", exc_info=True)
            flash("Couldn't make that workout. Please try again.", "error")
            return redirect(url_for('retrieve_custom'))

    @login_required
    def retrieve_custom_plan():
        """The plan for a custom pick: exercises (e), their sets (s) or, from older pages, the
        ones switched to two sets (t), in the address."""
        user = current_user
        try:
            catalog = get_custom_retrieval_exercise_catalog(Session, user, sort_mode='alpha_asc')
            try:
                selected_keys, selected_exercises, two_set_keys = _resolve_custom_retrieval_selection(
                    catalog, request.args.getlist('e'), request.args.getlist('t'),
                )
                set_overrides = _custom_set_overrides(selected_keys, two_set_keys, request.args.getlist('s'))
            except ValueError as error:
                flash(str(error), 'error')
                return redirect(url_for('retrieve_custom'))

            catalog_by_key = {item['key']: item for item in catalog}
            set_counts = [set_overrides.get(key) or catalog_by_key[key]['default_sets'] for key in selected_keys]
            name = clean_custom_workout_title(request.args.get('n'))
            session = None
            if request.args.get('c') and request.args.get('d'):
                plan_days = get_workout_days(get_effective_plan_text(Session, user) or "")
                session = _session_for_edit(plan_days, request.args.get('c'), request.args.get('d'))

            # Give retrieve the full plan line so a plan-only rep range (e.g. "[4, 6-8]")
            # still guides the output; set_overrides carries the sets chosen on the page.
            # An edited session uses its own lines for the exercises it has.
            session_lines = {}
            if session:
                for line in session['lines']:
                    parsed = _parse_plan_exercise_line(str(line or ''))
                    session_lines.setdefault(normalize_exercise_name(str(parsed.get('name') or line)), line)
            selected_lines = [
                session_lines.get(key) or catalog_by_key[key].get('exercise_line') or catalog_by_key[key]['name']
                for key in selected_keys
            ]

            if session:
                # An edited session keeps its number, place and name (unless renamed).
                name = name or session['name']
                header_title, kicker, shown_title = _session_title(session, name), session['kicker'], name
                title_fallback = ''
            else:
                if not name:
                    try:
                        name = infer_custom_workout_title(Session, user, selected_exercises)
                    except Exception as e:
                        logger.warning(f"Unable to infer custom workout title: {e}", exc_info=True)
                name = name or DEFAULT_CUSTOM_WORKOUT_TITLE
                header_title, kicker, shown_title = name, 'Custom workout', name
                title_fallback = DEFAULT_CUSTOM_WORKOUT_TITLE

            output, exercise_count, set_count = generate_custom_retrieve_output(
                Session,
                user,
                selected_lines,
                set_overrides=set_overrides,
                title=header_title,
            )
            return render_template(
                'retrieve_plan.html',
                output=output,
                plan=describe_retrieve_output(output),
                exercise_count=exercise_count,
                set_count=set_count,
                kicker=kicker,
                title=shown_title or kicker,
                back_url=url_for('retrieve_categories') if session else url_for('retrieve_custom'),
                title_value=shown_title,
                title_number=session['number'] if session else '',
                title_fallback=title_fallback,
                edit_url=_edit_url(selected_keys, set_counts, session=session, name=request.args.get('n')),
            )
        except Exception as e:
            logger.error(f"Error generating custom workout: {e}", exc_info=True)
            flash("Couldn't make that workout. Please try again.", "error")
            return redirect(url_for('retrieve_custom'))

    @login_required
    def retrieve_custom_review():
        # Picking, sets and order all happen on the one Custom workout page now.
        return redirect(url_for('retrieve_custom'))

    @login_required
    def save_exercise_group():
        """Long-press "Move to…" on the Custom workout page."""
        key = str(request.form.get('exercise') or '').strip()
        group = str(request.form.get('group') or '').strip()
        catalog = get_custom_retrieval_exercise_catalog(Session, current_user, sort_mode='alpha_asc')
        item = next((i for i in catalog if i['key'] == key), None)
        if item is None or group not in CUSTOM_PICKER_GROUPS:
            return jsonify({'ok': False, 'error': 'Unknown exercise or group.'}), 400
        try:
            set_exercise_group_choice(Session, current_user, key, group, item['auto_group'])
        except Exception as e:
            Session.rollback()
            logger.error(f"Error saving exercise group: {e}", exc_info=True)
            return jsonify({'ok': False, 'error': 'Could not save that right now.'}), 500
        return jsonify({'ok': True, 'group': group, 'auto_group': item['auto_group']})

    @login_required
    def save_custom_retrieval_sort_preference():
        sort_mode = str(request.form.get('sort_mode') or '').strip()
        if sort_mode not in CUSTOM_RETRIEVAL_SORT_MODES:
            return jsonify({'ok': False, 'error': 'Invalid sort mode.'}), 400

        try:
            saved_mode = set_custom_retrieval_sort_preference(Session, current_user, sort_mode)
            return jsonify({'ok': True, 'sort_mode': saved_mode})
        except Exception as e:
            Session.rollback()
            logger.error(f"Error saving custom retrieval sort preference: {e}", exc_info=True)
            return jsonify({'ok': False, 'error': 'Unable to save sort preference.'}), 500

    def _ask_about_renames(old_names, new_names):
        """After a save: names that look renamed are asked about on the page it returns to."""
        pairs = detect_renames(Session, current_user, old_names, new_names)
        if pairs:
            session['rename_questions'] = [list(p) for p in pairs]
        else:
            session.pop('rename_questions', None)

    def _pending_rename_questions():
        questions = rename_questions(Session, current_user, session.get('rename_questions'))
        if not questions:
            session.pop('rename_questions', None)
        return questions

    @login_required
    def answer_rename_question():
        """"Is Decline Crunches the same exercise as Crunches A?" Yes moves its history over."""
        old_name = sanitize_text_input(request.form.get('old_name', ''), max_length=160)
        new_name = sanitize_text_input(request.form.get('new_name', ''), max_length=160)
        next_url = request.form.get('next') or url_for('set_plan')
        if not is_safe_redirect_url(next_url, request.host_url):
            next_url = url_for('set_plan')
        answer = request.form.get('answer')
        if answer not in ('yes', 'no'):
            return redirect(next_url)
        pending = [p for p in session.get('rename_questions') or [] if list(p) != [old_name, new_name]]
        if pending:
            session['rename_questions'] = pending
        else:
            session.pop('rename_questions', None)
        if answer == 'yes':
            try:
                rename_exercise(Session, current_user, old_name, new_name)
                flash(f"{new_name} kept the history of {old_name}.", "success")
            except ValueError as e:
                flash(str(e), "error")
            except Exception as e:
                Session.rollback()
                logger.error(f"Exercise rename failed: {e}", exc_info=True)
                flash("Couldn't move that history right now. Please try again.", "error")
        return redirect(next_url)

    @login_required
    def set_plan():
        user = current_user

        try:
            plan = Session.query(Plan).filter_by(user_id=user.id).first()

            if not plan:
                plan = Plan(user_id=user.id, text_content="")
                Session.add(plan)
                Session.flush()

            if request.method == 'POST':
                form_type = request.form.get('form_type', 'save_plan')

                if form_type == 'toggle_follow_admin':
                    new_val = request.form.get('follow_admin_plan') == '1'
                    user.follow_admin_plan = new_val
                    user.updated_at = datetime.now()
                    if new_val:
                        catch_up_with_followed_renames(Session, user)
                    Session.commit()
                    session.pop('rename_questions', None)  # about a text that's been replaced
                    if new_val:
                        flash("Now following admin's plan.", "success")
                    else:
                        flash("Switched to your own plan.", "success")
                    return redirect(url_for('set_plan'))

                if form_type == 'copy_followed' and not is_plan_owner(Session, user):
                    # Their plan becomes this account's own, to change freely; following stops.
                    plan.text_content = _get_admin_plan_text(Session) or DEFAULT_PLAN.strip()
                    plan.updated_at = datetime.now()
                    user.follow_admin_plan = False
                    user.updated_at = datetime.now()
                    catch_up_with_followed_renames(Session, user)
                    Session.commit()
                    session.pop('rename_questions', None)  # about a text that's been replaced
                    flash("Copied. The plan is yours to edit now.", "success")
                    return redirect(url_for('set_plan'))

                plan_text = request.form.get('plan_text', '').strip()
                old_names = plan_exercise_names(_own_plan_text(Session, user) or DEFAULT_PLAN)
                plan.text_content = plan_text
                user.follow_admin_plan = False
                plan.updated_at = datetime.now()
                Session.commit()
                _ask_about_renames(old_names, plan_exercise_names(plan_text))
                flash("Workout plan saved.", "success")
                # Stay on the plan, as Rep ranges does, so the saved text is right there to check.
                return redirect(url_for('set_plan'))

            can_follow = not is_plan_owner(Session, user)
            return render_template(
                'set_plan.html',
                # Not following: the editor starts from the built-in plan if they haven't written one.
                current_plan=_own_plan_text(Session, user) or DEFAULT_PLAN.strip(),
                follow_admin_plan=can_follow and getattr(user, 'follow_admin_plan', False),
                # Copying replaces the plan this account wrote, so that asks first.
                copy_replaces=bool(_own_plan_text(Session, user))
                and _own_plan_text(Session, user).strip() != (_get_admin_plan_text(Session) or '').strip(),
                admin_display_name=get_admin_display_name(Session),
                can_follow=can_follow,
                rename_questions=_pending_rename_questions(),
            )
        except Exception as e:
            Session.rollback()
            logger.error(f"Error in set_plan: {e}", exc_info=True)
            flash("Couldn't save the plan. Please try again.", "error")
            return redirect(url_for('user_dashboard', username=user.username))

    @login_required
    def set_exercises():
        user = current_user

        try:
            reps = Session.query(RepRange).filter_by(user_id=user.id).first()

            if not reps:
                reps = RepRange(user_id=user.id, text_content="")
                Session.add(reps)
                Session.flush()

            if request.method == 'POST':
                form_type = request.form.get('form_type', 'save_exercises')

                if form_type == 'toggle_follow_admin':
                    new_val = request.form.get('follow_admin_exercises') == '1'
                    user.follow_admin_exercises = new_val
                    user.updated_at = datetime.now()
                    if new_val:
                        catch_up_with_followed_renames(Session, user)
                    Session.commit()
                    session.pop('rename_questions', None)  # about a text that's been replaced
                    if new_val:
                        flash("Now following admin's rep ranges.", "success")
                    else:
                        flash("Switched to your own rep ranges.", "success")
                    return redirect(url_for('set_exercises'))

                if form_type == 'copy_followed' and not is_plan_owner(Session, user):
                    reps.text_content = canonical_rep_text(
                        _get_admin_rep_ranges_text(Session) or _build_default_rep_text())
                    reps.updated_at = datetime.now()
                    user.follow_admin_exercises = False
                    user.updated_at = datetime.now()
                    catch_up_with_followed_renames(Session, user)
                    Session.commit()
                    session.pop('rename_questions', None)  # about a text that's been replaced
                    flash("Copied. The rep ranges are yours to edit now.", "success")
                    return redirect(url_for('set_exercises'))

                new_text = canonical_rep_text(request.form.get('rep_text', ''))
                if not new_text and (reps.text_content or '').strip() and request.form.get('rep_text_ready') != '1':
                    # The page's script fills rep_text when Save is pressed. An empty one without its
                    # mark means the script never ran, not that every range was removed.
                    flash("Rep ranges weren't saved. Reload the page and try again.", "error")
                    return redirect(url_for('set_exercises'))
                old_names = rep_exercise_names(reps.text_content or "")
                reps.text_content = new_text
                user.follow_admin_exercises = False
                reps.updated_at = datetime.now()
                Session.commit()
                _ask_about_renames(old_names, rep_exercise_names(new_text))
                flash("Rep ranges saved.", "success")
                return redirect(url_for('set_exercises'))

            can_follow = not is_plan_owner(Session, user)
            entries = merge_rep_entries(parse_rep_entries(reps.text_content or ""))
            groups = exercise_groups_for(Session, user, [name for name, _ in entries])
            return render_template(
                'set_exercises.html',
                entries=[[name, value, groups[name]] for name, value in entries],
                group_order=CUSTOM_PICKER_GROUPS,
                follow_admin_exercises=can_follow and getattr(user, 'follow_admin_exercises', False),
                copy_replaces=bool(_own_rep_ranges_text(Session, user))
                and canonical_rep_text(_own_rep_ranges_text(Session, user))
                != canonical_rep_text(_get_admin_rep_ranges_text(Session)),
                admin_display_name=get_admin_display_name(Session),
                can_follow=can_follow,
                rename_questions=_pending_rename_questions(),
            )
        except Exception as e:
            Session.rollback()
            logger.error(f"Error in set_exercises: {e}", exc_info=True)
            flash("Error saving rep ranges.", "error")
            return redirect(url_for('user_dashboard', username=user.username))

    app.add_url_rule(
        '/settings/exercise-names/answer',
        endpoint='answer_rename_question',
        view_func=answer_rename_question,
        methods=['POST'],
    )
    app.add_url_rule(
        '/retrieve/categories',
        endpoint='retrieve_categories',
        view_func=retrieve_categories,
        methods=['GET'],
    )
    app.add_url_rule(
        '/retrieve/heading/<int:heading_id>',
        endpoint='retrieve_heading_days',
        view_func=retrieve_heading_days,
        methods=['GET'],
    )
    app.add_url_rule(
        '/retrieve/days/<category>',
        endpoint='retrieve_days',
        view_func=retrieve_days,
        methods=['GET'],
    )
    app.add_url_rule(
        '/retrieve/final/<category>/<int:day_id>',
        endpoint='retrieve_final',
        view_func=retrieve_final,
        methods=['GET'],
    )
    app.add_url_rule(
        '/retrieve/custom',
        endpoint='retrieve_custom',
        view_func=retrieve_custom,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/retrieve/custom/plan',
        endpoint='retrieve_custom_plan',
        view_func=retrieve_custom_plan,
        methods=['GET'],
    )
    app.add_url_rule(
        '/retrieve/custom/review',
        endpoint='retrieve_custom_review',
        view_func=retrieve_custom_review,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/retrieve/custom/group',
        endpoint='save_exercise_group',
        view_func=save_exercise_group,
        methods=['POST'],
    )
    app.add_url_rule(
        '/retrieve/custom/sort-preference',
        endpoint='save_custom_retrieval_sort_preference',
        view_func=save_custom_retrieval_sort_preference,
        methods=['POST'],
    )
    app.add_url_rule('/set_plan', endpoint='set_plan', view_func=set_plan, methods=['GET', 'POST'])
    app.add_url_rule(
        '/set_exercises',
        endpoint='set_exercises',
        view_func=set_exercises,
        methods=['GET', 'POST'],
    )
