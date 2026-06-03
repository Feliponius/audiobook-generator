#!/usr/bin/env python3
"""Serve landing page on port 18789 for the tailnet hub."""
import http.server
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18789
LANDING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing.html")

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(LANDING, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()

server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
print(f"Hub landing on http://127.0.0.1:{PORT} -> https://lifeos.taild166b7.ts.net/")
server.serve_forever()
