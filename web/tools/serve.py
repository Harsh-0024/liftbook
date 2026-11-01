#!/usr/bin/env python3
"""Serves web/ for local testing, on every network address so a phone on the same Wi-Fi can open it.

Like `python3 -m http.server`, but tells browsers to check for a newer copy of every file, so a
change shows up on the next reload (Safari otherwise keeps old copies of the app's files).

    python3 web/tools/serve.py [port]      (default 8765)
"""
import http.server
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    http.server.ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
