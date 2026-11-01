# Edge Functions

Two Supabase Edge Functions (Deno) for project `qjlmxlnmfowqsunpzvac`:

- `coach`: the AI coach. The app sends the chat with the person's sign-in token. The function
  reads their training data as them (row-level security), then asks Gemini or Groq with their own key
  from `ai_keys` (read with the service key). Answers are kept in `coach_answers`. Port of
  `services/ai_coach.py` and `services/coach_tools.py`: same prompts, models, key order and tools.
- `shortcut`: Apple Shortcuts. `POST /shortcut/log/<key>` logs a workout and
  `GET /shortcut/pick/<key>?list=1` / `?key=<session>` gets a plan day. The key is the person's
  Shortcut key from Settings > Apple Shortcuts (only its SHA-256 is stored, in `shortcut_keys`).
  Changes are written the way a device syncs them, so they show up in the app on the next sync.

The logic lives in plain JS (`handler.js`, `coach.js`; Get Workout's day matching is `web/core/sessions.js`) and reuses `web/core` and
`web/app`. `index.ts` only hands requests to it.

```
node --test supabase/functions/test/          # unit tests, against a fake Supabase
python scripts/make_function_fixtures.py      # refresh the Python parity fixtures
supabase functions deploy coach shortcut --project-ref qjlmxlnmfowqsunpzvac --use-api
```

Supabase gives the functions `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY`.
Optional secrets: `LIFTBOOK_APP_URL` (where "open in app" links go; default
https://app.liftbook.in/), `LIFTBOOK_TZ_OFFSET_MINUTES` (Shortcut dates; default 330, India),
`AI_MODEL_ORDER`, `GEMINI_COACH_MODEL`.

## Cutover (nothing here is live yet)

What people using the old app must do when they move to the new one:

1. **Apple Shortcuts**: the old shortcuts call `liftbook.up.railway.app` (Render as fallback)
   with the old app's key, which the new app can't check. In the new app open Settings >
   Apple Shortcuts, tap "Make my Shortcut key", then add both shortcuts again from that page
   (`web/shortcuts/Log Workout.shortcut`, `Get Workout.shortcut`, built with
   `python scripts/build_apple_shortcuts.py --supabase`) and paste the key when asked.
2. The old "recommend" shortcut address is gone; it now answers with a message to re-add
   Get Workout.
3. Saved session nicknames for Get Workout (`user_texts` kind `shortcut_keys`) carry over and
   are edited in Settings > Apple Shortcuts > Session names.
4. AI keys move with the import; the coach is now open to everyone (it was admin-only). With no
   key, or when no model answers, the old app's built-in answers (`web/core/history_qa.js`) still
   answer the questions they know.

What the owner must do:

- Set `LIFTBOOK_APP_URL` once the app has its address:
  `supabase secrets set LIFTBOOK_APP_URL=<address> --project-ref qjlmxlnmfowqsunpzvac`.
- Re-run `supabase/schema.sql` on a new project (it grants the service role what the functions
  use; newer projects no longer grant it by default).
