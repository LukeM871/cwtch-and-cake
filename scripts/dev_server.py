"""Preview the website locally against the live API.

- Serves site/ at http://localhost:8765 with the same clean addresses as CloudFront
  (/menu/ → /menu/index.html, /menu → 301 /menu/).
- Copies the live site's security headers (including the exact Content-Security-Policy),
  so anything the CSP would block in production is blocked here too.
- Passes /api/* straight through to the live API (through CloudFront, so the origin check works).
- Port 8765 is a registered Cognito callback, so the admin login works locally too.

Usage: python scripts/dev_server.py [https://<your-cloudfront-domain>]
"""
from __future__ import annotations

import json
import mimetypes
import sys
import urllib.parse
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LIVE = (sys.argv[1] if len(sys.argv) > 1 else "https://d37nt89jw5nszl.cloudfront.net").rstrip("/")
SITE = Path(__file__).resolve().parents[1] / "site"
FIXTURES = Path(__file__).resolve().parent / "ui-fixtures"  # dev-only break-ui data switch
PORT = 8765
COPY_HEADERS = ("content-security-policy", "strict-transport-security", "x-content-type-options",
                "x-frame-options", "referrer-policy", "permissions-policy", "cross-origin-opener-policy")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")


def live_security_headers() -> dict[str, str]:
    with urllib.request.urlopen(urllib.request.Request(LIVE + "/", method="HEAD"), timeout=20) as r:
        return {k: v for k, v in r.headers.items() if k.lower() in COPY_HEADERS and k.lower() != "strict-transport-security"}


SECURITY = live_security_headers()


class Handler(BaseHTTPRequestHandler):
    server_version = "cwtch-dev"

    def log_message(self, fmt, *args):  # one short line per request
        sys.stderr.write(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")

    def _security(self):
        for k, v in SECURITY.items():
            self.send_header(k, v)

    def _fixture(self):
        """DEV ONLY break-ui switch: if the page was opened with ?data=worst|empty|one, answer
        GET /api/* from scripts/ui-fixtures/<mode>.json (the same data boundary the site uses)."""
        if self.command != "GET":
            return None
        ref = urllib.parse.urlparse(self.headers.get("Referer", ""))
        mode = urllib.parse.parse_qs(ref.query).get("data", [""])[0]
        if mode not in ("worst", "empty", "one"):
            return None
        fixtures = json.loads((FIXTURES / f"{mode}.json").read_text(encoding="utf-8"))
        return fixtures.get(self.path.split("?", 1)[0])

    def _proxy(self):
        fake = self._fixture()
        if fake is not None:
            data = json.dumps(fake, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._security()
            self.end_headers()
            self.wfile.write(data)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() in ("content-type", "authorization", "accept")}
        req = urllib.request.Request(LIVE + self.path, data=body, method=self.command, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            status, rheaders, data = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, rheaders, data = e.code, e.headers, e.read()
        self.send_response(status)
        for k in ("Content-Type", "Cache-Control"):
            if rheaders.get(k):
                self.send_header(k, rheaders[k])
        self.send_header("Content-Length", str(len(data)))
        self._security()
        self.end_headers()
        self.wfile.write(data)

    def _static(self, head=False):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path.endswith("/"):
            path += "index.html"
        elif "." not in path.rsplit("/", 1)[-1]:
            query = self.path[len(path):]
            self.send_response(301)
            self.send_header("Location", path + "/" + query)
            self.end_headers()
            return
        root = FIXTURES if path.startswith("/__dev/") else SITE
        file = (root / path.removeprefix("/__dev/").lstrip("/")).resolve()
        if root not in file.parents or not file.is_file():
            file, status = SITE / "404.html", 404
        else:
            status = 200
        data = file.read_bytes()
        if file.suffix == ".html":  # dev only: add the Demo / Worst case / Empty / One switch
            data = data.replace(b"</head>", b'<link rel="stylesheet" href="/__dev/data-toggle.css">'
                                b'<script type="module" src="/__dev/data-toggle.js"></script></head>', 1)
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self._security()
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def do_GET(self):
        self._proxy() if self.path.startswith("/api/") else self._static()

    def do_HEAD(self):
        self._static(head=True)

    def do_POST(self):
        self._proxy()

    do_PUT = do_PATCH = do_DELETE = do_POST


if __name__ == "__main__":
    print(f"Serving {SITE} on http://localhost:{PORT} (API → {LIVE}/api)")
    print("Security headers copied from the live site:", ", ".join(SECURITY))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
