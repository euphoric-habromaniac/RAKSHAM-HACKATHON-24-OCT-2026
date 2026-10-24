"""Pure helpers and the upload queue of tools/recorder/static/app.js under node (no browser, no mic)."""
import json
import shutil
import subprocess
import wave
import io
import base64
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "tools" / "recorder" / "static" / "app.js"

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[2], 'utf8');
const ctx = vm.createContext({ module: { exports: {} }, console, setTimeout, clearTimeout });
vm.runInContext(code, ctx);
const A = ctx.module.exports;
const sine = (n, amp) => Float32Array.from({ length: n }, (_, i) => amp * Math.sin(2 * Math.PI * 220 * i / 16000));
(async () => {
  const out = {};
  const pcm = sine(16000, 0.5);
  out.wav = Buffer.from(A.wavBytes(Float32Array.of(...pcm, 2, -2))).toString('base64');
  out.stats = [A.audioStats(sine(16000, 0.5)), A.audioStats(new Float32Array(100)), A.audioStats(Float32Array.of(1, -1, 1))];
  out.warn = [A.takeWarning(sine(8000, 0.5)), A.takeWarning(sine(32000, 1.0)), A.takeWarning(sine(32000, 0.005)), A.takeWarning(sine(32000, 0.5))];
  out.concat = Array.from(A.concatChunks([Float32Array.of(1, 2), Float32Array.of(3), new Float32Array(0)]));
  const rs = A.resampleLinear(sine(48000, 0.5), 48000, 16000);
  out.resample = { len: rs.length, same: A.resampleLinear(pcm, 16000, 16000) === pcm, peak: A.peakOf(rs), empty: A.resampleLinear(new Float32Array(0), 48000, 16000).length };
  out.norm = [A.normName('  Asha   RAO! '), A.normName('सुनीता वर्मा'), A.normName('Dev-Patel 2')];
  out.first = [A.firstUndoneIndex(100, []), A.firstUndoneIndex(100, [1, 2, 3]), A.firstUndoneIndex(100, [2, 3]), A.firstUndoneIndex(5, [1, 2, 3, 4, 5]),
    A.firstUndoneIndex(100, [1, 2, 4])];
  out.urls = [A.clipUrl('Yash Chauhan', 7), A.zipUrl('सुनीता'), A.zipUrl(''), A.zipUrl(null)];
  out.time = A.fmtTime(new Date(2026, 0, 2, 3, 4, 5));
  out.status = [
    A.statusInfo({ serverOk: true, pending: 0, dir: 'D:\\rec', lastSaved: '10:11:12', name: 'Yash', doneCount: 3, total: 100 }),
    A.statusInfo({ serverOk: true, pending: 0, dir: 'D:\\rec', lastSaved: '', name: '', doneCount: 0, total: 100 }),
    A.statusInfo({ serverOk: false, pending: 2, dir: 'D:\\rec', lastSaved: '', name: 'Yash', doneCount: 3, total: 100 }),
    A.statusInfo({ serverOk: false, pending: 0, dir: '', lastSaved: '', name: '', doneCount: 0, total: 100 })];

  // upload queue: retry on network errors, drop permanent ones, replace a waiting duplicate, keep order
  const log = [], acks = [], fails = [];
  let down = true, calls = 0;
  const up = A.createUploader({
    send: async item => { calls++; log.push(`${item.name}:${item.n}`); if (item.n === 9) throw Object.assign(new Error('bad'), { permanent: true });
      if (down) throw new TypeError('network'); return { ok: true }; },
    onAck: i => acks.push(i.n), onFail: (i, e) => fails.push([i.n, e.message]), onChange: () => {},
    sleep: async () => { if (calls >= 3) down = false; },
  });
  up.enqueue({ name: 'A', n: 1, blob: 'x' });
  up.enqueue({ name: 'A', n: 2, blob: 'old' });
  up.enqueue({ name: 'A', n: 2, blob: 'new' });  // replaces the waiting one
  up.enqueue({ name: 'A', n: 9, blob: 'bad' });
  const idle = await up.whenIdle(2000);
  out.queue = { idle, acks, fails, pending: up.pending(), failing: up.failing(), attemptsOf1: log.filter(x => x === 'A:1').length, log };
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    d = tmp_path_factory.mktemp("js")
    (d / "harness.js").write_text(HARNESS, encoding="utf-8")
    p = subprocess.run([node, str(d / "harness.js"), str(APP)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_app_js_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    subprocess.run([node, "--check", str(APP)], check=True, timeout=60)


def test_wav_is_16k_mono_16bit_pcm_and_clamped(result):
    raw = base64.b64decode(result["wav"])
    with wave.open(io.BytesIO(raw), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 16002)
        frames = w.readframes(w.getnframes())
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE" and len(raw) == 44 + 2 * 16002
    last = [int.from_bytes(frames[-4:-2], "little", signed=True), int.from_bytes(frames[-2:], "little", signed=True)]
    assert last == [32767, -32767]  # out-of-range samples are clamped
    assert max(int.from_bytes(frames[i:i + 2], "little", signed=True) for i in range(0, 32000, 2)) == pytest.approx(16384, abs=2)


def test_stats_and_warnings(result):
    quiet, silent, clipped = result["stats"]
    assert quiet["peak"] == pytest.approx(0.5, abs=0.001) and quiet["clipped"] is False and quiet["rms_dbfs"] == pytest.approx(-9.03, abs=0.05)
    assert silent["rms_dbfs"] == -120 and silent["peak"] == 0
    assert clipped["clipped"] is True
    short, loud, quiet_w, ok = result["warn"]
    assert "Too short" in short and "Clipped" in loud and "Very quiet" in quiet_w and ok == ""


def test_concat_resample_and_names(result):
    assert result["concat"] == [1, 2, 3]
    r = result["resample"]
    assert r["len"] == 16000 and r["same"] is True and r["empty"] == 0 and r["peak"] == pytest.approx(0.5, abs=0.05)
    assert result["norm"] == ["asha rao", "सुनीता वर्मा", "devpatel 2"]


def test_resume_index_urls_time_and_status_texts(result):
    assert result["first"] == [0, 3, 0, 5, 2]
    assert result["urls"] == ["/api/clip?name=Yash%20Chauhan&n=7", "/api/zip?name=%E0%A4%B8%E0%A5%81%E0%A4%A8%E0%A5%80%E0%A4%A4%E0%A4%BE", "/api/zip", "/api/zip"]
    assert result["time"] == "03:04:05"
    ok, idle, down, down_idle = result["status"]
    assert ok == {"ok": True, "text": "SAVING TO DISK: D:\\rec | last saved 10:11:12 | 3/100 saved for Yash"}
    assert idle["ok"] and idle["text"].endswith("last saved none yet | no speaker selected")
    assert down["ok"] is False and down["text"].startswith("NOT SAVING: server unreachable") and "2 clip(s)" in down["text"]
    assert down_idle == {"ok": False, "text": "NOT SAVING: server unreachable"}


def test_upload_queue_retries_until_saved_and_drops_permanent_errors(result):
    q = result["queue"]
    assert q["idle"] is True and q["pending"] == 0 and q["acks"] == [1, 2]
    assert q["fails"] == [[9, "bad"]]
    assert q["attemptsOf1"] >= 3 and q["log"].count("A:2") == 1  # the replaced duplicate was never sent
