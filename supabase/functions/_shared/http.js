// Replies from the Edge Functions. The app runs on another address than Supabase, so every reply
// says which pages may read it (CORS).

export const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type, x-liftbook-key',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
};

export function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8', ...headers } });
}

export function text(body, status = 200) {
  return new Response(String(body), { status, headers: { ...CORS, 'Content-Type': 'text/plain; charset=utf-8' } });
}

export const preflight = () => new Response(null, { status: 204, headers: CORS });
