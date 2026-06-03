#!/usr/bin/env python3
"""Reverse proxy for the audiobook dashboard on port 9081.

Served via tailscale: https://lifeos.taild166b7.ts.net:4443/ → this proxy → :8002
"""
import http.server
import sys
import urllib.error
import urllib.request

TARGET = "http://127.0.0.1:8002"
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
REQUEST_HEADERS_TO_FORWARD = {
    "accept",
    "accept-language",
    "authorization",
    "cache-control",
    "content-type",
    "if-range",
    "range",
    "user-agent",
}
CHUNK_SIZE = 1024 * 1024


class Router(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")

    def do_PUT(self):
        self._forward("PUT")

    def do_DELETE(self):
        self._forward("DELETE")

    def do_OPTIONS(self):
        self._forward("OPTIONS")

    def do_HEAD(self):
        self._forward("HEAD")

    def _copy_headers(self, source):
        for hdr, val in source.getheaders():
            if hdr.lower() not in HOP_BY_HOP_HEADERS and hdr.lower() != "server":
                self.send_header(hdr, val)

    def _stream_body(self, resp):
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            self.wfile.write(chunk)

    def _send_upstream_response(self, resp, method):
        self.send_response(resp.status)
        self._copy_headers(resp)
        self.end_headers()
        if method != "HEAD":
            self._stream_body(resp)

    def _forward(self, method):
        url = TARGET + self.path
        body = None
        content_len = self.headers.get("Content-Length")
        if content_len:
            body = self.rfile.read(int(content_len))

        req = urllib.request.Request(url, data=body, method=method)
        for hdr, val in self.headers.items():
            if hdr.lower() in REQUEST_HEADERS_TO_FORWARD:
                req.add_header(hdr, val)

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                self._send_upstream_response(resp, method)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self._copy_headers(e)
            self.end_headers()
            if method != "HEAD":
                self._stream_body(e)
        except (BrokenPipeError, ConnectionResetError):
            # The browser/mobile player closed the connection after getting enough data.
            return
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Proxy error: {e}".encode())


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9081
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Router)
    print(f"Proxy on :{port} → {TARGET}")
    server.serve_forever()


if __name__ == "__main__":
    main()
