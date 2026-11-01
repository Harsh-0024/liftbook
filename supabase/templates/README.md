# Liftbook's emails

The emails Supabase Auth sends: `confirmation.html` (sign-up), `recovery.html` (password reset),
`email_change.html` (new email) and `magic_link.html` (sign-in link). Subjects and file paths are in
`supabase/config.toml`. They use Supabase's template values: `{{ .ConfirmationURL }}`, `{{ .Email }}`,
`{{ .NewEmail }}`, `{{ .SiteURL }}` (the logo comes from the Site URL, so it follows the switch).

Sending goes through Resend's SMTP, set in the dashboard. Supabase only accepts custom templates once
custom SMTP is on.

After changing a template, from the repo root:

    supabase config diff --project-ref qjlmxlnmfowqsunpzvac
    supabase config push --project-ref qjlmxlnmfowqsunpzvac
