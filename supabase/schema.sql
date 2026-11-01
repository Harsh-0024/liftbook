-- Liftbook: the Supabase side.
--
-- Paste this whole file into Supabase -> SQL Editor -> New query -> Run.
-- It is safe to run again: everything is "create if missing" or replaced.
--
-- How it fits together
--   * Every phone and computer keeps its own full copy of the person's data.
--     This database is where they exchange changes, and the main copy; a
--     nightly job also copies it to Neon and Google Drive.
--   * The app signs in as the person and talks to these tables directly
--     through Supabase's REST API. Row-level security means each person can
--     only ever read and write their own rows, so the public key is safe to
--     ship inside the app.
--   * Rows are never deleted through the API. A delete on one device arrives
--     as deleted_at being set, so the other devices delete their copy too.
--   * Newest change wins: an upload older than what is stored is ignored
--     (see keep_newest()).
--   * server_updated_at is stamped by the server on every write. Devices
--     download "everything changed since I last looked" by this column, so a
--     device with a wrong clock cannot make changes go missing.
--   * legacy_id is the row's id in the old Flask app's database, kept so the
--     import (scripts/import_to_supabase.py) can be run again safely.

-- --------------------------------------------------------------------------
-- tables that devices sync
-- --------------------------------------------------------------------------

-- One row per person: name, username, bodyweight and photo.
create table if not exists public.profiles (
    user_id           uuid primary key default auth.uid() references auth.users (id) on delete cascade,
    legacy_id         integer unique,
    username          text not null check (username ~ '^[A-Za-z0-9_.-]{3,50}$'),
    full_name         text not null default '' check (char_length(full_name) <= 100),
    bodyweight        double precision check (bodyweight is null or bodyweight between 0 and 1000),
    avatar_path       text,                    -- in the "avatars" storage bucket
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),   -- the device's change time (newest wins)
    deleted_at        timestamptz,             -- unused; keeps every table the same shape for the app
    server_updated_at timestamptz not null default now()
);
create unique index if not exists profiles_username_unique on public.profiles (lower(username));

-- One row per exercise per workout, as the old app stores them.
create table if not exists public.workout_logs (
    user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
    id                uuid not null,           -- made by the device
    legacy_id         integer,
    date              timestamp not null,      -- the person's own clock time, no time zone
    workout_name      text check (char_length(workout_name) <= 100),
    exercise          text not null check (char_length(exercise) between 1 and 100),
    exercise_string   text,
    sets              jsonb,                   -- {"weights": [...], "reps": [...], ...}
    bodyweight        double precision,
    uses_bodyweight   boolean,
    top_weight        double precision,
    top_reps          integer,
    estimated_1rm     double precision,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    deleted_at        timestamptz,
    server_updated_at timestamptz not null default now(),
    primary key (user_id, id)
);
create unique index if not exists workout_logs_legacy on public.workout_logs (legacy_id);
create index if not exists workout_logs_by_date on public.workout_logs (user_id, date);
create index if not exists workout_logs_by_exercise on public.workout_logs (user_id, exercise, date);

-- The plan, rep ranges and shortcut keys: each one block of text per person.
create table if not exists public.user_texts (
    user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
    kind              text not null check (kind in ('plan', 'rep_ranges', 'shortcut_keys')),
    text              text not null default '' check (char_length(text) <= 200000),
    updated_at        timestamptz not null default now(),
    deleted_at        timestamptz,
    server_updated_at timestamptz not null default now(),
    primary key (user_id, kind)
);

-- Everything a person has said about one exercise: timed or not, bodyweight
-- or not, which muscle group, and how often they open its stats.
-- A null means "no choice made; use the app's default".
create table if not exists public.exercise_settings (
    user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
    exercise_key      text not null check (char_length(exercise_key) between 1 and 160),
    exercise_name     text check (char_length(exercise_name) <= 160),
    is_timed          boolean,
    is_bodyweight     boolean,
    bodyweight_source text check (char_length(bodyweight_source) <= 32),
    group_name        text check (char_length(group_name) <= 32),
    view_count        integer not null default 0,
    last_viewed_at    timestamptz,
    updated_at        timestamptz not null default now(),
    deleted_at        timestamptz,
    server_updated_at timestamptz not null default now(),
    primary key (user_id, exercise_key)
);

-- Each time a person pulled up an exercise on the Retrieve page, for
-- "most retrieved" sorting. Only ever added to.
create table if not exists public.retrieval_events (
    user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
    id                uuid not null,
    legacy_id         integer,
    exercise_key      text not null check (char_length(exercise_key) between 1 and 160),
    retrieved_at      timestamptz not null,
    updated_at        timestamptz not null default now(),
    deleted_at        timestamptz,
    server_updated_at timestamptz not null default now(),
    primary key (user_id, id)
);
create unique index if not exists retrieval_events_legacy on public.retrieval_events (legacy_id);

-- Exercises a person renamed, with the logs each rename moved, to undo it.
create table if not exists public.exercise_renames (
    user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
    id                uuid not null,
    legacy_id         integer,
    old_key           text not null check (char_length(old_key) between 1 and 160),
    old_name          text not null check (char_length(old_name) between 1 and 160),
    new_name          text not null check (char_length(new_name) between 1 and 160),
    log_ids           jsonb not null default '[]',    -- workout_logs ids
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    deleted_at        timestamptz,
    server_updated_at timestamptz not null default now(),
    primary key (user_id, id)
);
create unique index if not exists exercise_renames_legacy on public.exercise_renames (legacy_id);
create unique index if not exists exercise_renames_one_per_name
    on public.exercise_renames (user_id, old_key) where deleted_at is null;

-- One settings row per person: following the shared plan, sort orders,
-- the Stats page's time range. The app decides what goes in it.
create table if not exists public.app_settings (
    user_id           uuid primary key default auth.uid() references auth.users (id) on delete cascade,
    json              jsonb not null default '{}',
    updated_at        timestamptz not null default now(),
    deleted_at        timestamptz,
    server_updated_at timestamptz not null default now()
);

-- "What changed since I last looked", per person.
create index if not exists profiles_pull          on public.profiles          (user_id, server_updated_at);
create index if not exists workout_logs_pull      on public.workout_logs      (user_id, server_updated_at);
create index if not exists user_texts_pull        on public.user_texts        (user_id, server_updated_at);
create index if not exists exercise_settings_pull on public.exercise_settings (user_id, server_updated_at);
create index if not exists retrieval_events_pull  on public.retrieval_events  (user_id, server_updated_at);
create index if not exists exercise_renames_pull  on public.exercise_renames  (user_id, server_updated_at);
create index if not exists app_settings_pull      on public.app_settings      (user_id, server_updated_at);

-- --------------------------------------------------------------------------
-- newest change wins, and the server stamps every write
-- --------------------------------------------------------------------------
create or replace function public.keep_newest()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if tg_op = 'UPDATE' then
        -- An upload older than (or the same as) what is stored changes nothing.
        if new.updated_at <= old.updated_at then
            return null;  -- skip this row's update
        end if;
        new.user_id := old.user_id;  -- a row can never be moved to another person
    end if;
    new.server_updated_at := clock_timestamp();
    return new;
end;
$$;

do $$
declare t text;
begin
    foreach t in array array['profiles', 'workout_logs', 'user_texts', 'exercise_settings',
                             'retrieval_events', 'exercise_renames', 'app_settings'] loop
        execute format('drop trigger if exists keep_newest on public.%I', t);
        execute format(
            'create trigger keep_newest before insert or update on public.%I
             for each row execute function public.keep_newest()', t);
    end loop;
end;
$$;

-- --------------------------------------------------------------------------
-- own rows only
-- --------------------------------------------------------------------------
-- Signed-in people may read, add and change their own rows. There is no
-- delete rule, so nobody can delete rows through the API at all - not even
-- their own, and not by mistake. Signed-out requests ("anon") get nothing.
-- legacy_id is the import's alone, so the app can't write it.
do $$
declare t text;
begin
    foreach t in array array['profiles', 'workout_logs', 'user_texts', 'exercise_settings',
                             'retrieval_events', 'exercise_renames', 'app_settings'] loop
        execute format('alter table public.%I enable row level security', t);
        execute format('revoke all on public.%I from anon, authenticated', t);
        execute format('grant select, insert, update on public.%I to authenticated', t);
        execute format('drop policy if exists own_rows on public.%I', t);
        execute format(
            'create policy own_rows on public.%I for all to authenticated
             using (user_id = (select auth.uid()))
             with check (user_id = (select auth.uid()))', t);
    end loop;
end;
$$;

do $$
declare t text;
begin
    foreach t in array array['profiles', 'workout_logs', 'retrieval_events', 'exercise_renames'] loop
        execute format('revoke insert, update on public.%I from authenticated', t);
        execute format(
            'grant insert (%1$s), update (%1$s) on public.%2$I to authenticated',
            (select string_agg(quote_ident(column_name), ', ')
             from information_schema.columns
             where table_schema = 'public' and table_name = t and column_name <> 'legacy_id'),
            t);
    end loop;
end;
$$;

-- "Is this username free?" while someone is creating an account (so before
-- they are signed in). Answers yes or no only; it never reveals whose name
-- it is, and a person's own current username counts as free for them.
create or replace function public.username_available(name text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select not exists (
        select 1 from public.profiles
        where lower(username) = lower(name)
          and user_id is distinct from (select auth.uid())
    );
$$;
revoke all on function public.username_available(text) from public;
grant execute on function public.username_available(text) to anon, authenticated;

-- --------------------------------------------------------------------------
-- admins, and the plan others can follow
-- --------------------------------------------------------------------------
-- Who is an admin. Not reachable through the API at all (no policies); only
-- the functions below read it. The first admin added is the main one, whose
-- plan and rep ranges other people can follow.
create table if not exists public.admins (
    user_id  uuid primary key references auth.users (id) on delete cascade,
    added_at timestamptz not null default now()
);
alter table public.admins enable row level security;
revoke all on public.admins from anon, authenticated;

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (select 1 from public.admins where user_id = (select auth.uid()));
$$;
revoke all on function public.is_admin() from public;
grant execute on function public.is_admin() to authenticated;

-- The plan and rep ranges people follow when "Follow the shared plan" is on:
-- the main admin's, or the next admin's if the main one has none.
-- {"plan": "...", "rep_ranges": "...", "updated_at": "..."}
create or replace function public.shared_plan()
returns json
language sql
stable
security definer
set search_path = ''
as $$
    select json_build_object(
        'plan', (
            select t.text from public.user_texts t join public.admins a using (user_id)
            where t.kind = 'plan' and t.deleted_at is null and btrim(t.text) <> ''
            order by a.added_at, a.user_id limit 1),
        'rep_ranges', (
            select t.text from public.user_texts t join public.admins a using (user_id)
            where t.kind = 'rep_ranges' and t.deleted_at is null and btrim(t.text) <> ''
            order by a.added_at, a.user_id limit 1),
        'updated_at', (
            select max(t.server_updated_at) from public.user_texts t join public.admins a using (user_id)
            where t.kind in ('plan', 'rep_ranges'))
    );
$$;
revoke all on function public.shared_plan() from public;
grant execute on function public.shared_plan() to authenticated;

-- --------------------------------------------------------------------------
-- the person's own AI keys (for the coach)
-- --------------------------------------------------------------------------
-- People can add keys, see a key's label and last four characters, rename,
-- switch off and delete them - but never read a key back. Only the coach (an
-- Edge Function, using the service key) reads the key itself.
create table if not exists public.ai_keys (
    id           bigint generated always as identity primary key,
    legacy_id    integer unique,
    user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
    label        text not null default '' check (char_length(label) <= 100),
    api_key      text not null check (char_length(api_key) between 8 and 255),
    key_hint     text generated always as (right(api_key, 4)) stored,
    -- Groq keys start with gsk_; the coach takes everything else for Gemini.
    provider     text generated always as (case when btrim(api_key) like 'gsk\_%' then 'groq' else 'gemini' end) stored,
    is_active    boolean not null default true,
    created_at   timestamptz not null default now(),
    last_used_at timestamptz
);
-- Added after the first import, so it is also added to a table made before.
alter table public.ai_keys add column if not exists provider text
    generated always as (case when btrim(api_key) like 'gsk\_%' then 'groq' else 'gemini' end) stored;
create index if not exists ai_keys_user on public.ai_keys (user_id);
alter table public.ai_keys enable row level security;
revoke all on public.ai_keys from anon, authenticated;
grant select (id, user_id, label, key_hint, provider, is_active, created_at, last_used_at) on public.ai_keys to authenticated;
grant insert (label, api_key) on public.ai_keys to authenticated;
grant update (label, is_active) on public.ai_keys to authenticated;
grant delete on public.ai_keys to authenticated;
drop policy if exists own_rows on public.ai_keys;
create policy own_rows on public.ai_keys for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

-- --------------------------------------------------------------------------
-- coach answers: kept so their quality can be reviewed
-- --------------------------------------------------------------------------
-- Written by the coach (service key). People read their own and rate them.
create table if not exists public.coach_answers (
    id         bigint generated always as identity primary key,
    legacy_id  integer unique,
    user_id    uuid not null references auth.users (id) on delete cascade,
    question   text not null,
    answer     text not null,
    source     text not null default 'ai' check (source in ('ai', 'rules')),
    model      text,
    steps      jsonb,
    calls      integer,
    tokens     integer,
    ms         integer,
    failed     text,
    rating     integer check (rating in (-1, 1)),
    comment    text check (char_length(comment) <= 2000),
    created_at timestamptz not null default now()
);
create index if not exists coach_answers_user on public.coach_answers (user_id, created_at desc);
alter table public.coach_answers enable row level security;
revoke all on public.coach_answers from anon, authenticated;
grant select on public.coach_answers to authenticated;
grant update (rating, comment) on public.coach_answers to authenticated;
drop policy if exists own_rows on public.coach_answers;
create policy own_rows on public.coach_answers for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

-- --------------------------------------------------------------------------
-- feedback: what people like, dislike, would improve or want next
-- --------------------------------------------------------------------------
-- People can send feedback and read their own (to see whether it was read);
-- they can't change or delete it. Admins read everyone's and mark it through
-- the functions below.
create table if not exists public.feedback (
    id         bigint generated always as identity primary key,
    legacy_id  integer unique,
    user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
    kind       text not null check (kind in ('like', 'dislike', 'improve', 'idea')),
    message    text not null check (char_length(btrim(message)) between 1 and 2000),
    page       text not null default '' check (char_length(page) <= 200),
    status     text not null default 'new' check (status in ('new', 'seen', 'done')),
    created_at timestamptz not null default now()
);
create index if not exists feedback_user on public.feedback (user_id, created_at desc);
create index if not exists feedback_newest on public.feedback (created_at desc);
alter table public.feedback enable row level security;
revoke all on public.feedback from anon, authenticated;
grant select on public.feedback to authenticated;
-- Only these columns: nobody can send feedback that is already "done".
grant insert (kind, message, page) on public.feedback to authenticated;
drop policy if exists own_read on public.feedback;
create policy own_read on public.feedback for select to authenticated
    using (user_id = (select auth.uid()));
drop policy if exists own_insert on public.feedback;
create policy own_insert on public.feedback for insert to authenticated
    with check (user_id = (select auth.uid()));

-- Everyone's feedback with who sent it, newest first, for admins only.
create or replace function public.admin_feedback()
returns json
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if not public.is_admin() then
        raise exception 'admins only' using errcode = '42501';
    end if;
    return (
        select coalesce(json_agg(t order by t.created_at desc), '[]'::json)
        from (
            select f.id, f.kind, f.message, f.page, f.status, f.created_at,
                   f.user_id, u.email,
                   coalesce(p.username, '')  as username,
                   coalesce(p.full_name, '') as full_name
            from public.feedback f
            join auth.users u on u.id = f.user_id
            left join public.profiles p on p.user_id = f.user_id
        ) t
    );
end;
$$;
revoke all on function public.admin_feedback() from public;
grant execute on function public.admin_feedback() to authenticated;

create or replace function public.admin_set_feedback_status(feedback_id bigint, new_status text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if not public.is_admin() then
        raise exception 'admins only' using errcode = '42501';
    end if;
    update public.feedback set status = new_status where id = feedback_id;
end;
$$;
revoke all on function public.admin_set_feedback_status(bigint, text) from public;
grant execute on function public.admin_set_feedback_status(bigint, text) to authenticated;

-- Admin pages: everyone's accounts with how much they log, and the coach's
-- recent answers with their ratings (the old app's /admin and /admin/coach).
-- Read only; admins see emails here and nowhere else.
create or replace function public.admin_users()
returns json
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if not public.is_admin() then
        raise exception 'admins only' using errcode = '42501';
    end if;
    return (
        select coalesce(json_agg(t order by t.last_workout desc nulls last, t.created_at desc), '[]'::json)
        from (
            select u.id as user_id, u.email, u.created_at, u.last_sign_in_at,
                   u.email_confirmed_at is not null as confirmed,
                   coalesce(p.username, '')  as username,
                   coalesce(p.full_name, '') as full_name,
                   p.avatar_path is not null as has_photo,
                   exists (select 1 from public.admins a where a.user_id = u.id) as is_admin,
                   (select count(distinct w.date::date) from public.workout_logs w
                     where w.user_id = u.id and w.deleted_at is null) as workouts,
                   (select max(w.date) from public.workout_logs w
                     where w.user_id = u.id and w.deleted_at is null) as last_workout
            from auth.users u
            left join public.profiles p on p.user_id = u.id
        ) t
    );
end;
$$;
revoke all on function public.admin_users() from public;
grant execute on function public.admin_users() to authenticated;

create or replace function public.admin_coach_answers(max_rows integer default 100)
returns json
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if not public.is_admin() then
        raise exception 'admins only' using errcode = '42501';
    end if;
    return json_build_object(
        'totals', (select json_build_object(
                       'answers', count(*),
                       'helpful', count(*) filter (where rating = 1),
                       'not_helpful', count(*) filter (where rating = -1),
                       'built_in', count(*) filter (where source = 'rules'))
                   from public.coach_answers),
        'answers', (select coalesce(json_agg(t order by t.created_at desc), '[]'::json)
                    from (select c.id, c.question, c.answer, c.source, c.model, c.rating, c.comment,
                                 c.ms, c.tokens, c.failed, c.created_at,
                                 coalesce(p.username, '') as username
                          from public.coach_answers c
                          left join public.profiles p on p.user_id = c.user_id
                          order by c.created_at desc
                          limit greatest(1, least(coalesce(max_rows, 100), 500))) t)
    );
end;
$$;
revoke all on function public.admin_coach_answers(integer) from public;
grant execute on function public.admin_coach_answers(integer) to authenticated;

-- --------------------------------------------------------------------------
-- Apple Shortcuts keys
-- --------------------------------------------------------------------------
-- A Shortcut logs workouts and gets plan days with a key of its own (it can't
-- sign in). Only a SHA-256 of the key is kept, so the key is shown once, when
-- it is made; a new key replaces the old one. The shortcut Edge Function looks
-- the hash up with the service key. People see when their key was made and
-- last used, and its last four characters.
create table if not exists public.shortcut_keys (
    user_id      uuid primary key references auth.users (id) on delete cascade,
    key_hash     text not null unique check (key_hash ~ '^[0-9a-f]{64}$'),
    key_hint     text not null,
    created_at   timestamptz not null default now(),
    last_used_at timestamptz
);
alter table public.shortcut_keys enable row level security;
revoke all on public.shortcut_keys from anon, authenticated;
grant select (user_id, key_hint, created_at, last_used_at) on public.shortcut_keys to authenticated;
drop policy if exists own_read on public.shortcut_keys;
create policy own_read on public.shortcut_keys for select to authenticated
    using (user_id = (select auth.uid()));

-- A new key for the signed-in person ("lbk_" and 64 random hex characters),
-- replacing any old one. Returned once; only its hash is stored.
create or replace function public.new_shortcut_key()
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    k text;
begin
    if (select auth.uid()) is null then
        raise exception 'not signed in' using errcode = '42501';
    end if;
    k := 'lbk_' || replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '');
    insert into public.shortcut_keys (user_id, key_hash, key_hint)
    values ((select auth.uid()), encode(sha256(convert_to(k, 'UTF8')), 'hex'), right(k, 4))
    on conflict (user_id) do update
        set key_hash = excluded.key_hash, key_hint = excluded.key_hint, created_at = now(), last_used_at = null;
    return k;
end;
$$;
revoke all on function public.new_shortcut_key() from public;
grant execute on function public.new_shortcut_key() to authenticated;

-- Switch Shortcuts off: the key stops working.
create or replace function public.remove_shortcut_key()
returns void
language sql
volatile
security definer
set search_path = ''
as $$
    delete from public.shortcut_keys where user_id = (select auth.uid());
$$;
revoke all on function public.remove_shortcut_key() from public;
grant execute on function public.remove_shortcut_key() to authenticated;

-- --------------------------------------------------------------------------
-- what the Edge Functions may do (with the service key)
-- --------------------------------------------------------------------------
-- The service role skips row-level security, but newer projects no longer give
-- it table rights by default, so the coach and the shortcut functions
-- (supabase/functions) get exactly what they use: a Shortcut reads and saves
-- one person's training data, the coach reads AI keys and keeps its answers.
grant select, insert, update on public.profiles, public.workout_logs, public.user_texts,
    public.exercise_settings, public.retrieval_events, public.exercise_renames,
    public.app_settings to service_role;
grant select on public.admins to service_role;
grant select, update (last_used_at) on public.ai_keys to service_role;
grant select, insert on public.coach_answers to service_role;
grant select, update (last_used_at) on public.shortcut_keys to service_role;
grant execute on function public.shared_plan() to service_role;

-- --------------------------------------------------------------------------
-- deleting your own account
-- --------------------------------------------------------------------------
-- Removes the sign-in and, through "on delete cascade", every row above.
-- The profile photo is removed by the app first (storage can't cascade).
create or replace function public.delete_my_account()
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if (select auth.uid()) is null then
        raise exception 'not signed in' using errcode = '42501';
    end if;
    delete from auth.users where id = (select auth.uid());
end;
$$;
revoke all on function public.delete_my_account() from public;
grant execute on function public.delete_my_account() to authenticated;

-- --------------------------------------------------------------------------
-- profile photos
-- --------------------------------------------------------------------------
-- A private bucket. Each person's photos live in a folder named after their
-- user id, and only they can read or change that folder.
do $$
begin
    if not exists (select 1 from information_schema.schemata where schema_name = 'storage') then
        return;  -- a plain Postgres (the tests) has no storage
    end if;

    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('avatars', 'avatars', false, 2097152, array['image/png', 'image/jpeg', 'image/webp'])
    on conflict (id) do nothing;

    drop policy if exists avatars_own on storage.objects;
    create policy avatars_own on storage.objects for all to authenticated
        using (bucket_id = 'avatars' and (storage.foldername(name))[1] = (select auth.uid())::text)
        with check (bucket_id = 'avatars' and (storage.foldername(name))[1] = (select auth.uid())::text);
end;
$$;
