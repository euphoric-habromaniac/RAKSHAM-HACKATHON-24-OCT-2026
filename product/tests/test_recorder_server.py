"""Real HTTP against the recorder server on an ephemeral port (no browser, no mic)."""
import csv
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import pytest

from recorder_helpers import FIELDS, make_wav
from tools.recorder import server as srv


class Client:
    def __init__(self, httpd):
        self.base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(self, method, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def json(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
        status, raw, _ = self.call(method, path, data, {"Content-Type": "application/json"} if data is not None else None)
        return status, json.loads(raw)

    def put(self, name, n, wav):
        return self.json("PUT", f"/api/clip?name={urllib.parse.quote(name)}&n={n}", wav)


def start(root):
    httpd = srv.make_server(root, 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, t


def stop(httpd, t):
    httpd.shutdown()
    httpd.server_close()
    t.join(5)


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "rec"
    httpd, t = start(root)
    yield Client(httpd), root, httpd
    stop(httpd, t)


def test_binds_to_loopback_only(env):
    _, _, httpd = env
    assert httpd.server_address[0] == "127.0.0.1"
    assert srv.HOST == "127.0.0.1"


def test_static_files_and_info_and_prompts(env):
    c, root, _ = env
    status, body, h = c.call("GET", "/")
    assert status == 200 and b"Continue a speaker" in body and h["Content-Type"].startswith("text/html")
    assert c.call("GET", "/app.js")[0] == 200 and c.call("GET", "/style.css")[0] == 200
    assert c.call("GET", "/../server.py")[0] == 404 and c.call("GET", "/static/app.js")[0] == 404
    assert c.json("GET", "/api/info")[1] == {"ok": True, "dir": str(root.resolve()), "prompt_count": 100}
    status, prompts = c.json("GET", "/api/prompts")
    assert status == 200 and len(prompts) == 100 and prompts[0]["id"] == "p001_hi" and prompts[99]["n"] == 100
    assert (root / "SPEAKER_SCRIPT.txt").exists() and (root / "README.txt").exists() and (root / "prompts.csv").exists()


def test_full_flow_profile_clip_resume_zip(env):
    c, root, _ = env
    assert c.json("GET", "/api/speakers") == (200, [])
    status, v = c.json("POST", "/api/profile", FIELDS)
    assert status == 200 and v["ok"] and v["existing"] is False and v["done"] == []
    sid = v["profile"]["speaker_id"]
    for n in (1, 2, 3):
        status, r = c.put("Test Person", n, make_wav(1.5 + n / 10))
        assert status == 200 and r["ok"] and r["done_count"] == n and r["size"] == len(make_wav(1.5 + n / 10))
        assert (root / "Test Person" / f"{n}.wav").stat().st_size == r["size"]  # on disk before the reply
    status, sp = c.json("GET", "/api/speaker?name=test%20person")
    assert status == 200 and sp["done"] == [1, 2, 3] and sp["profile"]["speaker_id"] == sid
    status, lst = c.json("GET", "/api/speakers")
    assert lst[0]["name"] == "Test Person" and lst[0]["done"] == 3 and lst[0]["speaker_id"] == sid
    status, raw, h = c.call("GET", "/api/clip?name=Test%20Person&n=2")
    assert status == 200 and raw == make_wav(1.7) and h["Content-Type"] == "audio/wav"
    assert c.json("GET", "/api/clip?name=Test%20Person&n=9")[0] == 404
    status, v2 = c.json("POST", "/api/profile", {**FIELDS, "name": "TEST person"})
    assert v2["existing"] is True and v2["profile"]["speaker_id"] == sid and v2["done"] == [1, 2, 3]
    status, cont = c.json("POST", "/api/continue?name=Test%20Person", b"")
    assert status == 200 and cont["done"] == [1, 2, 3]

    c.json("POST", "/api/profile", {**FIELDS, "name": "सुनीता वर्मा"})
    c.put("सुनीता वर्मा", 7, make_wav())
    status, raw, h = c.call("GET", "/api/zip")
    assert status == 200 and h["Content-Type"] == "application/zip" and int(h["Content-Length"]) == len(raw)
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = set(z.namelist())
    assert {"Test Person/1.wav", "Test Person/2.wav", "Test Person/3.wav", "Test Person/profile.json", "Test Person/consent.json",
            "सुनीता वर्मा/7.wav", "manifest_master.csv", "people.csv", "_session_log.csv", "SPEAKER_SCRIPT.txt", "prompts.csv", "README.txt"} <= names
    assert len(list(csv.DictReader(io.StringIO(z.read("manifest_master.csv").decode("utf-8"))))) == 4
    status, raw, h = c.call("GET", "/api/zip?name=test%20person")
    one = zipfile.ZipFile(io.BytesIO(raw))
    assert "Test Person/3.wav" in one.namelist() and not any(n.startswith("सुनीता") for n in one.namelist())
    assert "attachment" in h["Content-Disposition"] and ".zip" in h["Content-Disposition"]
    assert c.json("GET", "/api/zip?name=Nobody")[0] == 404
    events = [r["event"] for r in csv.DictReader(io.StringIO((root / "_session_log.csv").read_text(encoding="utf-8")))]
    assert "zip_built" in events and events.count("clip_saved") == 4


def test_restart_resumes_from_disk(tmp_path):
    root = tmp_path / "rec"
    httpd, t = start(root)
    c = Client(httpd)
    sid = c.json("POST", "/api/profile", FIELDS)[1]["profile"]["speaker_id"]
    for n in (1, 2, 3):
        assert c.put("Test Person", n, make_wav())[0] == 200
    stop(httpd, t)
    httpd2, t2 = start(root)
    try:
        c2 = Client(httpd2)
        status, sp = c2.json("GET", "/api/speaker?name=Test%20Person")
        assert status == 200 and sp["done"] == [1, 2, 3] and sp["profile"]["speaker_id"] == sid
        assert c2.json("GET", "/api/speakers")[1][0]["done"] == 3
    finally:
        stop(httpd2, t2)


def test_rejects_wrong_format_and_bad_input(env):
    c, root, _ = env
    c.json("POST", "/api/profile", FIELDS)
    for bad in (make_wav(rate=44100), make_wav(channels=2), make_wav(seconds=0.1), b"garbage", b""):
        status, body = c.put("Test Person", 1, bad)
        assert status == 400 and body["ok"] is False and body["error"]
    assert not (root / "Test Person" / "1.wav").exists()
    assert c.put("Test Person", 0, make_wav())[0] == 400
    assert c.put("Test Person", 101, make_wav())[0] == 400
    assert c.put("Test Person", "x", make_wav())[0] == 400
    assert c.put("Nobody", 1, make_wav())[0] == 404
    assert c.json("POST", "/api/profile", b"not json")[0] == 400
    assert c.json("POST", "/api/profile", {**FIELDS, "allow_recording": False})[0] == 400
    assert c.json("POST", "/api/profile", {**FIELDS, "name": "CON"})[0] == 400
    assert c.json("GET", "/api/nothing")[0] == 404
    status, body = c.json("GET", "/api/speaker?name=Nobody")
    assert status == 404 and body["ok"] is False


def test_traversal_names_rejected_or_contained(env):
    c, root, _ = env
    evils = ("../../evil", "..\\..\\evil", "%2e%2e%2f%2e%2e%2fevil", "/abs/path", "C:\\x")
    quoted = [e if "%" in e else urllib.parse.quote(e) for e in evils]
    for q in quoted:  # no profile exists yet: nothing may be written, nothing may be read
        assert c.json("PUT", f"/api/clip?name={q}&n=1", make_wav())[0] in (400, 404)
        assert c.json("GET", f"/api/clip?name={q}&n=1")[0] in (400, 404)
        assert c.call("GET", f"/api/zip?name={q}")[0] in (400, 404)
        assert c.json("GET", f"/api/speaker?name={q}")[0] in (400, 404)
    for evil in evils:  # a profile is created, but only as one plain folder inside the recordings dir
        assert c.json("POST", "/api/profile", {**FIELDS, "name": evil})[0] in (200, 400)
    outside = [p for p in root.parent.rglob("*") if root not in p.parents and p != root and p.is_file()]
    assert outside == []
    assert all(d.parent == root.resolve() for d in root.iterdir() if d.is_dir())
    assert not (root.parent / "evil").exists() and not (root.parent.parent / "evil").exists()


def test_oversized_body_rejected(env):
    c, _, _ = env
    c.json("POST", "/api/profile", FIELDS)
    big = b"\x00" * (srv.MAX_BODY + 10)
    try:
        status, _ = c.put("Test Person", 1, big)
    except (urllib.error.URLError, ConnectionError, OSError):
        status = 413  # server closes the connection after refusing; both mean refused
    assert status in (400, 413)


def test_foreign_host_and_origin_refused(env):
    c, _, httpd = env
    port = httpd.server_address[1]
    status, _, _ = c.call("GET", "/api/info", None, {"Host": f"evil.example:{port}"})
    assert status == 403
    status, _, _ = c.call("POST", "/api/profile", json.dumps(FIELDS).encode(), {"Origin": "https://evil.example", "Content-Type": "text/plain"})
    assert status == 403
    status, _, _ = c.call("GET", "/api/info", None, {"Origin": f"http://localhost:{port}"})
    assert status == 200


def test_parallel_puts_are_serialised_and_all_land(env):
    c, root, _ = env
    c.json("POST", "/api/profile", FIELDS)
    results = {}

    def go(n):
        results[n] = c.put("Test Person", n, make_wav(1.0 + n / 50))[0]

    threads = [threading.Thread(target=go, args=(n,)) for n in range(1, 21)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert set(results.values()) == {200}
    assert c.json("GET", "/api/speaker?name=Test%20Person")[1]["done"] == list(range(1, 21))
    rows = list(csv.DictReader(io.StringIO((root / "manifest_master.csv").read_text(encoding="utf-8"))))
    assert sorted(int(r["sentence_number"]) for r in rows) == list(range(1, 21))
