#!/usr/bin/env python3
"""HTTPS reverse proxy for the audiobook dashboard.

Proxies https://lifeos.taild166b7.ts.net:8443 → http://127.0.0.1:8002
with a self-signed cert (browser must accept once).
"""
import http.server
import ssl
import urllib.request
import os
import sys

TARGET = "http://127.0.0.1:8002"
CERT_DIR = os.path.dirname(os.path.abspath(__file__))


class Proxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_PUT(self):
        self._proxy("PUT")

    def do_DELETE(self):
        self._proxy("DELETE")

    def do_OPTIONS(self):
        self._proxy("OPTIONS")

    def do_HEAD(self):
        self._proxy("HEAD")

    def _proxy(self, method):
        url = TARGET + self.path
        body = None
        content_len = self.headers.get("Content-Length")
        if content_len:
            body = self.rfile.read(int(content_len))

        req = urllib.request.Request(url, data=body, method=method)
        # Forward relevant headers
        for hdr in ("Content-Type", "Accept", "Authorization", "User-Agent"):
            if hdr in self.headers:
                req.add_header(hdr, self.headers[hdr])

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                # Forward response headers
                for hdr, val in resp.getheaders():
                    if hdr.lower() not in ("transfer-encoding", "connection", "server"):
                        self.send_header(hdr, val)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"Proxy error: {e}".encode())


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8443
    server = http.server.HTTPServer(("0.0.0.0", port), Proxy)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        os.path.join(CERT_DIR, "cert.pem"),
        os.path.join(CERT_DIR, "key.pem"),
    )
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    print(f"HTTPS proxy on https://lifeos.taild166b7.ts.net:{port} → {TARGET}")
    server.serve_forever()


if __name__ == "__main__":
    main()
