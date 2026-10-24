#!/usr/bin/env python3
"""RAKSHAM: one entry point for the whole repo.

    python rak.py setup [--ml]  create .venv and install what the service, tests and detector need (--ml adds CPU torch)
    python rak.py doctor        check folders, data, models, environment
    python rak.py data-check    verify sehaj_dataset labels vs files, recordings vs clones
    python rak.py test          run the product test suite (service, policy, adapters)
    python rak.py smoke         one clip end to end: product smoke test + live detector through the service adapter
    python rak.py check         doctor + data-check + test + smoke (the "does everything work" command)
    python rak.py demo          Voice Check demo + case storage on http://127.0.0.1:8765/
    python rak.py service       the Asli Awaaz decision service on http://127.0.0.1:8000/  (--live uses our detector as L2)
    python rak.py precommit     size guard, secret scan, quick tests: run before every commit
    python rak.py pack          zip the whole folder for another computer (no .venv, refuses if junctions exist)
    python rak.py link-heavy    OPT-IN: junction the big regenerable data from the original folders (no copy)
"""
import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCT, ML, DATA = ROOT / "product", ROOT / "ml", ROOT / "data"
VENV = ROOT / ".venv"
SEHAJ, REC, GEN = DATA / "sehaj_dataset", DATA / "recordings_awaaz", DATA / "generated"
CODE = ROOT.parent  # Documents/code
ORIGINALS = {
    PRODUCT / "data" / "raw": CODE / "asli-awaaz" / "data" / "raw",
    PRODUCT / "data" / "deg": CODE / "asli-awaaz" / "data" / "deg",
    ML / "models" / "finetune": CODE / "derived_db" / "finetune",
}
OK, BAD, WARN = "[ok]  ", "[FAIL]", "[warn]"
failures = []


def _venv_python():
    for p in (VENV / "Scripts" / "python.exe", VENV / "bin" / "python"):
        if p.exists():
            return p
    return None


def venv_state() -> str:
    """'absent', 'ok' or 'stale' (present but unusable here, e.g. the folder was zipped over from another computer)."""
    p = _venv_python()
    if p is None:
        return "absent"
    try:
        ok = subprocess.run([str(p), "-c", "import sys"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    return "ok" if ok else "stale"


_PY = None


def py() -> str:
    global _PY
    if _PY is None:
        _PY = str(_venv_python()) if venv_state() == "ok" else sys.executable
    return _PY


def report(ok: bool, msg: str, warn: bool = False):
    print(f"{OK if ok else (WARN if warn else BAD)} {msg}")
    if not ok and not warn:
        failures.append(msg)


def run(cmd, env=None, cwd=None) -> int:
    e = {**os.environ, **(env or {})}
    return subprocess.call(cmd, env=e, cwd=str(cwd or ROOT))


def cmd_setup(args):
    state = venv_state()
    if state == "stale":
        print("the existing .venv does not work on this computer (copied from another one): rebuilding it")
        shutil.rmtree(VENV)
        state = "absent"
    if state == "absent":
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    global _PY
    _PY = None
    subprocess.check_call([py(), "-m", "pip", "install", "-q", "-U", "pip"])
    reqs = ["-r", str(PRODUCT / "requirements-service.txt"), "-r", str(PRODUCT / "requirements-docs.txt"), "numpy", "scipy", "soundfile", "pandas", "tqdm", "scikit-learn"]
    subprocess.check_call([py(), "-m", "pip", "install", "-q", *reqs])
    if "--ml" in args:  # CPU torch: enables the AASIST/torch tests (7 are skipped without it)
        subprocess.check_call([py(), "-m", "pip", "install", "-q", "torch"])
    print("setup done. Heavy ML (clone generation, fine-tuning) needs torch + coqui-tts: ")
    return 0


def junctions():
    """Directory junctions / symlinks inside the repo (a zip tool would follow them into the originals)."""
    found = []
    for t in ORIGINALS:
        if t.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(t)):
            found.append(t)
    return found


def cmd_doctor(_):
    print(f"RAKSHAM at {ROOT}\n")
    report(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (need 3.10+)")
    vs = venv_state()
    report(vs == "ok", f".venv is {vs}" + ("" if vs == "ok" else " (run: python rak.py setup)"), warn=True)
    j = junctions()
    report(not j, "no junction links in the tree" if not j else f"junction links present, remove before zipping: {', '.join(str(x.relative_to(ROOT)) for x in j)}", warn=True)
    for d in (PRODUCT / "service", PRODUCT / "ui", PRODUCT / "tests", ML / "live_detector", ML / "voice_data", SEHAJ, REC, GEN,
              ROOT / "deck" / "finale", ROOT / "design-system", ROOT / "docs"):
        report(d.exists(), f"folder {d.relative_to(ROOT)}")
    for f in ("model_0p5s.npz", "model_1p0s.npz", "detector.py", "server.py"):
        report((ML / "live_detector" / f).exists(), f"ml/live_detector/{f}")
    report((ML / "live_detector" / "demo" / "model.json").exists(), "ml/live_detector/demo/model.json (browser model)")
    report((SEHAJ / "labels.csv").exists(), "data/sehaj_dataset/labels.csv")
    n_rec = len(list(REC.glob("*/*.wav"))); n_gen = len(list(GEN.glob("*/*.wav")))
    report(n_rec == 300, f"real recordings: {n_rec} wav (expect 300)")
    report(n_gen == 300, f"voice clones: {n_gen} wav (expect 300)")
    for spk in sorted(p for p in REC.iterdir() if p.is_dir()):
        c = spk / "consent.json"
        report(c.exists(), f"consent file for {spk.name}")
    free = shutil.disk_usage(ROOT).free / 1e9
    report(free > 10, f"disk free {free:.1f} GB (need > 10)", warn=free <= 10)
    for target, original in ORIGINALS.items():
        state = "linked" if target.exists() else ("not linked (optional: python rak.py link-heavy)" if original.exists() else "original not found")
        print(f"{WARN if not target.exists() else OK} heavy data {target.relative_to(ROOT)}: {state}")
    print("\nsummary:", "ALL REQUIRED CHECKS PASSED" if not failures else f"{len(failures)} FAILED")
    return 1 if failures else 0


def cmd_data_check(_):
    rows = list(csv.DictReader(open(SEHAJ / "labels.csv", encoding="utf-8", newline="")))
    missing = [r["file"] for r in rows if not (SEHAJ / r["file"]).exists()]
    lang = Counter(r["language"] for r in rows)
    report(len(rows) == 16800, f"labels.csv rows: {len(rows)} (expect 16,800 = 15,000 English + 1,800 Hinglish)")
    report(lang.get("hinglish") == 1800 and lang.get("english") == 15000, f"languages: {dict(lang)}")
    report(not missing, f"every labelled file exists ({len(missing)} missing)")
    h = [r for r in rows if r["language"] == "hinglish"]
    split = Counter((r["split"], r["label"]) for r in h)
    report(split[("test", "real")] == 300 and split[("test", "fake")] == 300, f"hinglish test split balanced: {dict(split)}")
    spk_splits = {}
    for r in rows:
        if r["language"] == "english":
            spk_splits.setdefault(r["speaker_id"], set()).add(r["split"])
    leaks = [s for s, v in spk_splits.items() if len(v) > 1]
    report(not leaks, f"English splits are speaker-disjoint ({len(leaks)} speakers in 2 splits)")
    real = {Path(r["file"]).name.replace("_real", "") for r in h if r["label"] == "real" and r["condition"] == "clean"}
    fake = {Path(r["file"]).name.replace("_fake", "") for r in h if r["label"] == "fake" and r["condition"] == "clean"}
    report(real == fake and len(real) == 300, f"every real Hinglish clip has a paired fake ({len(real)} real, {len(fake)} fake)")
    man = list(csv.DictReader(open(GEN / "manifest_generated.csv", encoding="utf-8", newline="")))
    report(len(man) == 300, f"clone manifest rows: {len(man)} (expect 300)")
    report(all((GEN / r["file"]).exists() for r in man), "every manifest clone exists")
    print("\nnote: Hinglish validation shares speakers with training; only the test split (Yash) is speaker-disjoint.")
    return 1 if failures else 0


def cmd_test(_):
    return run([py(), "-m", "pytest", "tests", "-q"], env={"PYTHONPATH": str(PRODUCT)}, cwd=PRODUCT)


def cmd_smoke(_):
    rc = run([py(), "tools/smoke.py"], env={"PYTHONPATH": str(PRODUCT)}, cwd=PRODUCT)
    code = (
        "import wave,sys; sys.path.insert(0,'.'); from service.live_scorer import LiveDetectorSpoofScorer as S;"
        "d='../ml/live_detector/demo/samples/';"
        "r=lambda f: wave.open(d+f,'rb').readframes(10**9);"
        "s=S(); a=s.score(r('vukqxv0v_047_real.wav'),16000,{}); b=s.score(r('vukqxv0v_047_fake.wav'),16000,{});"
        "print('live detector via service adapter: real score %.3f, fake score %.3f' % (a,b)); sys.exit(0 if a<0.5<b else 1)"
    )
    rc2 = run([py(), "-c", code], cwd=PRODUCT)
    report(rc == 0, "product smoke test")
    report(rc2 == 0, "live detector through the L2 adapter separates real from fake")
    return 1 if failures else 0


def cmd_check(args):
    rc = 0
    for name, fn in (("doctor", cmd_doctor), ("data-check", cmd_data_check), ("test", cmd_test), ("smoke", cmd_smoke)):
        print(f"\n===== {name} =====")
        rc |= fn(args) or 0
    print("\n" + ("EVERYTHING PASSED" if rc == 0 and not failures else "SOMETHING FAILED, see [FAIL] lines above"))
    return 1 if (rc or failures) else 0


def cmd_demo(_):
    print("Voice Check on http://127.0.0.1:8765/  (saved calls go to ./cases)")
    return run([py(), str(ML / "live_detector" / "server.py")])


def cmd_service(args):
    env = {"PYTHONPATH": str(PRODUCT)}
    if "--live" in args:
        env["ASLI_L2_BACKEND"] = "live"
        print("L2 = live detector (numpy)")
    return run([py(), "-m", "uvicorn", "service.api:app", "--host", "127.0.0.1", "--port", "8000"], env=env, cwd=PRODUCT)


FORBIDDEN_EXT = {".wav", ".pth", ".pt", ".zip", ".rar", ".exe", ".ct"}
SECRET = re.compile(r"(api[_-]?key\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}|-----BEGIN (RSA |EC )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,})", re.I)


def _ignored(path: Path) -> bool:
    """Approximate .gitignore matching, used only when this folder is not a git repo yet."""
    import fnmatch

    rel = path.relative_to(ROOT).as_posix()
    if ".git" in path.parts:
        return True
    gi = ROOT / ".gitignore"
    for line in gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []:
        pat = line.strip()
        if not pat or pat.startswith("#") or pat.startswith("!"):
            continue
        if pat.endswith("/"):
            d = pat.rstrip("/")
            parts = rel.split("/")
            if rel.startswith(d + "/") or ("/" + d + "/") in ("/" + rel) or any(fnmatch.fnmatch(part, d) for part in parts[:-1])                     or any(fnmatch.fnmatch("/".join(parts[:i]), d) for i in range(1, len(parts))):
                return True
        elif "/" in pat:
            if fnmatch.fnmatch(rel, pat) or rel.startswith(pat.rstrip("*").rstrip("/") + "/"):
                return True
        elif fnmatch.fnmatch(path.name, pat) or pat in path.parts:
            # `!results/**/*.log` style exceptions are ignored here (kept simple); logs under results/ are allowed below
            if pat == "*.log" and rel.startswith("results/"):
                continue
            return True
    return False


def cmd_precommit(args):
    if (ROOT / ".git").exists():
        out = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True)
        files = [ROOT / p for p in out.splitlines() if p]
    else:
        print("(not a git repo yet: scanning the files .gitignore intends to keep; run `git init` to make this exact)")
        files = [p for p in ROOT.rglob("*") if p.is_file() and not _ignored(p)]
    big = [p for p in files if p.exists() and p.stat().st_size > 5_000_000]
    bad = [p for p in files if p.suffix.lower() in FORBIDDEN_EXT]
    report(not big, f"no file above 5 MB ({', '.join(str(p.relative_to(ROOT)) for p in big[:5]) or 'none'})")
    report(not bad, f"no audio, weights or archives ({', '.join(str(p.relative_to(ROOT)) for p in bad[:5]) or 'none'})")
    leaks = []
    for p in files:
        if p.suffix.lower() in {".py", ".json", ".md", ".txt", ".html", ".csv", ".env", ".cfg"} and p.exists() and p.stat().st_size < 2_000_000:
            try:
                if SECRET.search(p.read_text(encoding="utf-8", errors="ignore")):
                    leaks.append(p)
            except OSError:
                pass
    report(not leaks, f"no secrets found ({', '.join(str(p.relative_to(ROOT)) for p in leaks[:5]) or 'none'})")
    consent = [p for p in files if p.name == "consent.json"]
    report(not consent, "no signed consent files in the commit")
    if "--no-tests" not in (args or []):
        rc = cmd_test(None)
        report(rc == 0, "product tests pass")
    print("\nstill to do by hand: read `git diff --staged`, add a line to PROGRESS.md, update results/deck if a number changed.")
    return 1 if failures else 0


def cmd_pack(args):
    """Zip the whole folder (code, data, models, .git) for another computer. Not .venv (rebuilt there by setup)."""
    import zipfile
    from datetime import date

    j = junctions()
    if j:
        print(f"{BAD} refusing to pack: junction links would pull in the original data ({', '.join(str(x.relative_to(ROOT)) for x in j)}).")
        print("       remove them first: rmdir <link>   (never a recursive delete)")
        return 1
    skip_dirs = {".venv", "__pycache__", ".pytest_cache", ".ipynb_checkpoints", "node_modules"}
    if "--no-cases" in args:
        skip_dirs.add("cases")
    out = ROOT.parent / f"RAKSHAM_portable_{date.today().isoformat()}.zip"
    if "-o" in args:
        out = Path(args[args.index("-o") + 1])
    files = [p for p in ROOT.rglob("*") if p.is_file() and not (set(p.relative_to(ROOT).parts) & skip_dirs) and p != out]
    size = sum(p.stat().st_size for p in files) / 1e6
    print(f"{len(files)} files, {size:,.0f} MB before compression -> {out}")
    if "--dry-run" in args:
        return 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for p in files:
            z.write(p, Path("RAKSHAM") / p.relative_to(ROOT))
    print(f"{OK} wrote {out} ({out.stat().st_size / 1e6:,.0f} MB). On the other computer: unzip, python rak.py setup, python rak.py check")
    return 0


def cmd_link_heavy(_):
    made = 0
    for target, original in ORIGINALS.items():
        if target.exists():
            print(f"{OK} already there: {target.relative_to(ROOT)}")
            continue
        if not original.exists():
            print(f"{WARN} original missing, skipped: {original}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            subprocess.check_call(["cmd", "/c", "mklink", "/J", str(target), str(original)], stdout=subprocess.DEVNULL)
        else:
            target.symlink_to(original, target_is_directory=True)
        print(f"{OK} linked {target.relative_to(ROOT)} -> {original}")
        made += 1
    print("\nTo remove a link use `rmdir <link>` (Windows) or `rm <link>` (not `rm -r`, not Remove-Item -Recurse): that deletes only the link.")
    return 0


COMMANDS = {"setup": cmd_setup, "doctor": cmd_doctor, "data-check": cmd_data_check, "test": cmd_test, "smoke": cmd_smoke,
            "check": cmd_check, "pack": cmd_pack, "demo": cmd_demo, "service": cmd_service, "precommit": cmd_precommit, "link-heavy": cmd_link_heavy}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]) or 0)
