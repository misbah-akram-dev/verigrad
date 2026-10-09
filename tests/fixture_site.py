"""Local fixture website for browser tests: static pages + a few dynamic routes. No internet."""

import json
import os
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE_DIR = Path(__file__).parent / "fixtures" / "site"
BROWSER_CHANNEL = os.environ.get("VERIGRAD_BROWSER_CHANNEL") or ""
TINY_PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
ROBOTS = "User-agent: *\nDisallow: /private/\n"
DEADLINES = {"rounds": [{"name": "Round 1", "deadline": "JSON_ROUND 15 January 2027"}]}
# A real-world path shape: KAUST's admissions site has /study/master's-degree.
APOSTROPHE_PATH = "/study/master's-degree"
APOSTROPHE_PAGE = (
    b"<!doctype html><html><head><title>Master's degree</title></head><body>"
    b"<h1>Master's degree</h1><p>APOSTROPHE_MARKER The master's programme admits students in "
    b"two rounds. Round 1 closes on 1 November 2026 and Round 2 closes on 3 January 2027. "
    b"Applicants need a bachelor's degree, transcripts, two recommendation letters and an "
    b"English test score.</p></body></html>"
)


class FixtureSite:
    def __init__(self, server: ThreadingHTTPServer) -> None:
        self.server = server
        self.hits: Counter[str] = Counter()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"


def _handler(site_holder: list[FixtureSite]) -> type[SimpleHTTPRequestHandler]:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            super().__init__(*args, directory=str(SITE_DIR), **kwargs)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def do_GET(self) -> None:
            # Decoded, so a path matches whether or not the browser percent-encoded it.
            path = unquote(urlsplit(self.path).path)
            site_holder[0].hits[path] += 1
            routes = {
                "/robots.txt": (200, "text/plain", ROBOTS.encode()),
                "/forbidden": (403, "text/html", b"<h1>403 Forbidden</h1>"),
                "/server-error": (500, "text/html", b"<h1>500</h1>"),
                "/api/deadlines.json": (200, "application/json", json.dumps(DEADLINES).encode()),
                "/api/tracking.json": (200, "application/json", b'{"visitor": "x"}'),
                "/docs/rules.pdf": (200, "application/pdf", TINY_PDF),
                APOSTROPHE_PATH: (200, "text/html; charset=utf-8", APOSTROPHE_PAGE),
            }
            if path in routes:
                status, content_type, body = routes[path]
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    return Handler


@contextmanager
def serve_fixture_site() -> Iterator[FixtureSite]:
    holder: list[FixtureSite] = []
    # Loopback only. Pages also call it as `localhost`, which is a different site key.
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(holder))
    site = FixtureSite(server)
    holder.append(site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield site
    finally:
        server.shutdown()
        server.server_close()
