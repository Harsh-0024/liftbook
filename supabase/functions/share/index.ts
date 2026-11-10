// Share links for anyone (no sign-in). The work is in handler.js (plain JavaScript, tested with node).
import { handle } from './handler.js';

Deno.serve((req: Request) => handle(req, Deno.env.toObject()));
