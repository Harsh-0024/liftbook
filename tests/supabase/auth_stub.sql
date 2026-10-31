-- The few parts of a Supabase project that supabase/schema.sql and the import
-- rely on, for testing on a plain Postgres.
do $$ begin
    -- roles belong to the whole server, so an earlier test may have made them
    if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;
grant usage on schema public to anon, authenticated;

create schema auth;
grant usage on schema auth to anon, authenticated;

create table auth.users (
    id                     uuid primary key,
    instance_id            uuid,
    aud                    varchar(255),
    role                   varchar(255),
    email                  varchar(255),
    encrypted_password     varchar(255),
    email_confirmed_at     timestamptz,
    raw_app_meta_data      jsonb,
    raw_user_meta_data     jsonb,
    created_at             timestamptz,
    updated_at             timestamptz,
    confirmation_token     varchar(255),
    recovery_token         varchar(255),
    email_change_token_new varchar(255),
    email_change           varchar(255)
);
create unique index users_email_key on auth.users (email);

create table auth.identities (
    id              uuid primary key,
    provider_id     text not null,
    user_id         uuid not null references auth.users (id) on delete cascade,
    identity_data   jsonb not null,
    provider        text not null,
    last_sign_in_at timestamptz,
    created_at      timestamptz,
    updated_at      timestamptz,
    unique (provider_id, provider)
);

-- Supabase reads the signed-in person from the request's token; tests set it with
-- set_config('request.jwt.claim.sub', ...).
create function auth.uid() returns uuid
language sql stable
as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant execute on function auth.uid() to anon, authenticated;
