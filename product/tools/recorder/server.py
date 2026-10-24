"""Local recorder server (stdlib only, 127.0.0.1 only).

    python -m tools.recorder.server [--port 8765] [--dir downloads/recordings_awaaz]

Serves the recorder page and a small JSON/WAV API; every clip is written to disk before the PUT is acknowledged.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from tools.recorder.store import MAX_S, RATE, RecorderStore, StoreError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# RAKSHAM: new recordings land in the shared data folder next to product/ and ml/
DEFAULT_DIR = REPO_ROOT.parent / "data" / "recordings_awaaz"
DEFAULT_PORT = 8765
HOST = "127.0.0.1"
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
MAX_BODY = int(MAX_S * RATE * 2) + 4096   # largest legal WAV plus header slack
MAX_JSON = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "AsliAwaazRecorder/1"
    store: RecorderStore  # set by make_server

    def log_message(self, fmt, *args):  # quiet: the page shows the status
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ---- plumbing
    def _send(self, status: int, body: bytes, ctype: str, headers: dict = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _guard(self) -> bool:
        """Only this machine: right Host header (DNS rebinding) and no foreign Origin (cross-site writes)."""
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._error(403, "Forbidden host.")
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            self._error(403, "Forbidden origin.")
            return False
        return True

    def _body(self, limit: int) -> bytes:
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise StoreError(411, "Content-Length is required.")
        if n < 0 or n > limit:
            self.close_connection = True
            raise StoreError(413, "Request body too large.")
        return self.rfile.read(n)

    def _dispatch(self, routes: dict) -> None:
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        try:
            if not self._guard():
                return
            fn = routes.get(url.path)
            if fn is None:
                return self._error(404, "Not found.")
            fn(q)
        except StoreError as exc:
            self._error(exc.status, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as exc:  # never kill the thread silently
            self._error(500, f"Server error: {type(exc).__name__}: {exc}")

    # ---- verbs
    def do_GET(self):
        self._dispatch({**{p: self._static for p in STATIC}, "/api/info": self._info, "/api/prompts": self._prompts,
                        "/api/speakers": self._speakers, "/api/speaker": self._speaker, "/api/clip": self._get_clip,
                        "/api/zip": self._zip})

    def do_POST(self):
        self._dispatch({"/api/profile": self._post_profile, "/api/continue": self._post_continue})

    def do_PUT(self):
        self._dispatch({"/api/clip": self._put_clip})

    # ---- handlers
    def _static(self, q):
        name = STATIC[urlsplit(self.path).path]
        self._send(200, (STATIC_DIR / name).read_bytes(), TYPES[Path(name).suffix])

    def _info(self, q):
        self._json(200, {"ok": True, **self.store.info()})

    def _prompts(self, q):
        self._json(200, self.store.prompts)

    def _speakers(self, q):
        self._json(200, self.store.list_speakers())

    def _speaker(self, q):
        self._json(200, {"ok": True, **self.store.get_speaker(q.get("name", ""))})

    def _post_profile(self, q):
        try:
            fields = json.loads(self._body(MAX_JSON).decode("utf-8"))
            if not isinstance(fields, dict):
                raise ValueError
        except ValueError:
            raise StoreError(400, "Body must be a JSON object.")
        self._json(200, {"ok": True, **self.store.save_profile(fields)})

    def _post_continue(self, q):
        self._body(MAX_JSON)
        self._json(200, {"ok": True, **self.store.touch(q.get("name", ""))})

    def _put_clip(self, q):
        data = self._body(MAX_BODY)  # read first so an error reply never leaves a half-read upload behind
        self._json(200, self.store.save_clip(q.get("name", ""), q.get("n", ""), data))

    def _get_clip(self, q):
        self._send(200, self.store.read_clip(q.get("name", ""), q.get("n", "")), "audio/wav")

    def _zip(self, q):
        name = q.get("name") or None
        f = self.store.build_zip(name)
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        label = self.store.get_speaker(name)["profile"].get("folder", "speaker") if name else "all_speakers"
        self.store.append_log("zip_built", label if name else "", "", f"{size} bytes")
        ascii_name = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in label) or "recordings"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f"attachment; filename=\"awaaz_{ascii_name}.zip\"; filename*=UTF-8''awaaz_{quote(label)}.zip")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with f:
            while chunk := f.read(1 << 20):
                self.wfile.write(chunk)


def make_server(root=DEFAULT_DIR, port: int = DEFAULT_PORT, verbose: bool = False) -> ThreadingHTTPServer:
    """Server object bound to 127.0.0.1 (port 0 = any free port); reference files are refreshed."""
    store = RecorderStore(root)
    store.write_reference_files()
    handler = type("BoundHandler", (Handler,), {"store": store})
    httpd = ThreadingHTTPServer((HOST, port), handler)
    httpd.daemon_threads = True
    httpd.store = store
    httpd.verbose = verbose
    return httpd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="recordings folder (default: RAKSHAM/data/recordings_awaaz)")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    try:
        httpd = make_server(a.dir, a.port, a.verbose)
    except OSError as exc:
        print(f"error: cannot start on {HOST}:{a.port} ({exc}). Is the recorder already running? Try --port {a.port + 1}.", file=sys.stderr)
        return 1
    print(f"Recorder ready: http://127.0.0.1:{httpd.server_address[1]}/  (open in Chrome or Edge)")
    print(f"Saving every clip to: {httpd.store.root}")
    print("Stop with Ctrl+C.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
