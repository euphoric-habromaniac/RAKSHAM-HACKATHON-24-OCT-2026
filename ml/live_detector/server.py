"""Local server for the Voice Check demo: serves demo/ and stores finished calls ON DISK, on this machine only.

    python server.py            # http://127.0.0.1:8765/  (bound to localhost; nothing leaves the machine)

Each call is saved as cases/<CASE-ID>/case.json (analysis, decisions, challenges, actions, audio SHA-256)
and cases/<CASE-ID>/audio.wav (full 16 kHz mono waveform). Cases are write-once: there is no delete endpoint.
"""
import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]  # RAKSHAM/
DEMO, CASES = ROOT / "demo", REPO / "cases"
CASE_ID = re.compile(r"^CASE-[0-9A-Z-]{6,40}$")
CASE_FILE = re.compile(r"^/api/case/([^/]+)/(case\.json|audio\.wav)$")
MAX_BYTES = 300 * 1024 * 1024


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DEMO), **k)

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/cases":
            out = []
            for d in sorted(CASES.glob("CASE-*")):
                try:
                    c = json.loads((d / "case.json").read_text(encoding="utf-8"))
                    out.append({"case_id": c["case_id"], "started": c["call"]["started"], "duration_s": c["call"]["duration_s"],
                                "verdict": c["summary"]["verdict"], "flagged_segments": c["summary"]["flagged_segments"],
                                "challenges": c["summary"]["challenges"], "has_audio": (d / "audio.wav").exists()})
                except Exception:
                    continue
            return self._send(200, json.dumps(sorted(out, key=lambda r: r["started"] or "", reverse=True)).encode())
        m = CASE_FILE.match(self.path)
        if m and CASE_ID.match(m.group(1)):
            f = CASES / m.group(1) / m.group(2)
            if f.exists():
                return self._send(200, f.read_bytes(), "audio/wav" if f.suffix == ".wav" else "application/json")
            return self._send(404, b'{"error":"not found"}')
        return super().do_GET()

    def do_PUT(self):
        m = CASE_FILE.match(self.path)
        if not m or not CASE_ID.match(m.group(1)):
            return self._send(400, b'{"error":"bad path"}')
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0 or n > MAX_BYTES:
            return self._send(413, b'{"error":"bad size"}')
        d = CASES / m.group(1)
        f = d / m.group(2)
        if f.exists():
            return self._send(409, b'{"error":"case files are write-once"}')
        d.mkdir(parents=True, exist_ok=True)
        f.write_bytes(self.rfile.read(n))
        return self._send(201, json.dumps({"saved": str(f.relative_to(REPO)).replace("\\", "/")}).encode())

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    CASES.mkdir(exist_ok=True)
    print("Voice Check on http://127.0.0.1:8765/  (cases saved in", CASES, ")")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
