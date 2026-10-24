"""Fill open deck placeholders from measured results and team decisions.

Only placeholders with a present, sourced value are substituted. Originals are
never modified: slides are copied to --out first.

    python -m eval.fill_placeholders --results results.json --targets targets.json \
        [--src ../../deck/slides] [--out deck-filled/slides]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

# (slide file, placeholder text, key). One exact <b>...</b> element each.
PLACEHOLDERS = [
    ("evidence.html", "[N]", "hinglish_n"),
    ("evidence.html", "[M]", "hinglish_m"),
    ("evidence.html", "[x]", "genuine_stepup_target_pct"),
    ("trust.html", "[x]", "fairness_gap_points"),
    ("arch2.html", "[Bank retention policy]", "bank_retention_policy"),
]


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fmt(x: float) -> str:
    return str(int(x)) if float(x) == int(x) else str(x)


def _target(targets: dict, key: str):
    """Return (value, why_not). Needs value and decided_by."""
    t = targets.get(key)
    if not isinstance(t, dict) or t.get("value") is None:
        return None, "no value in targets.json"
    if not str(t.get("decided_by") or "").strip():
        return None, "value has no decided_by"
    return t["value"], None


def resolve(results: dict, targets: dict) -> dict:
    """Map key -> (text or None, source or reason)."""
    out = {}
    prov = results.get("provenance", {})
    h = results.get("hinglish_set")
    sourced = bool(h) and bool(prov.get("command")) and bool(prov.get("generated_at")) \
        and bool(h.get("manifest", {}).get("file"))
    if not sourced or h["n_speakers"] < 1:
        out["hinglish_n"] = (None, "no sourced Hinglish counts in results.json")
        out["hinglish_m"] = (None, "no sourced Hinglish counts in results.json")
    else:
        src = f"results.json ({h['manifest']['file']}, {prov['generated_at']})"
        out["hinglish_n"] = (str(h["n_speakers"]), src)
        cps = h["clips_per_speaker"]
        if cps["uniform"]:
            out["hinglish_m"] = (str(cps["min"]), src)
        else:
            rule, why = _target(targets, "hinglish_m_rule")
            if why is None and rule == "min":
                out["hinglish_m"] = (str(cps["min"]), src + " minimum rule")
            else:
                out["hinglish_m"] = (None, f"clips per speaker differ ({cps['min']} to {cps['max']}); set hinglish_m_rule")
    for key, lo, hi in (("genuine_stepup_target_pct", 0, 100), ("fairness_gap_points", 0, None)):
        v, why = _target(targets, key)
        n = _num(v)
        if why:
            out[key] = (None, why)
        elif n is None or n < lo or (hi is not None and n > hi):
            out[key] = (None, f"value {v!r} not a number in range")
        else:
            out[key] = (_fmt(n), f"targets.json, decided by {targets[key]['decided_by']}")
    v, why = _target(targets, "bank_retention_policy")
    if why:
        out["bank_retention_policy"] = (None, why)
    elif not isinstance(v, str) or not v.strip():
        out["bank_retention_policy"] = (None, "text is empty")
    else:
        out["bank_retention_policy"] = (html.escape(v.strip()), f"targets.json, decided by {targets['bank_retention_policy']['decided_by']}")
    return out


def fill(src: Path, out: Path, results: dict, targets: dict) -> list:
    src, out = src.resolve(), out.resolve()
    if src == out:
        raise SystemExit("--out must differ from --src; originals are never modified")
    if src in out.parents:
        raise SystemExit("--out must not sit inside --src")
    if not src.is_dir():
        raise SystemExit(f"slides dir not found: {src}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, out, dirs_exist_ok=True)
    if (src.parent / "deck.json").is_file():
        shutil.copy2(src.parent / "deck.json", out.parent / "deck.json")
    values = resolve(results, targets)
    report = []
    for fname, ph, key in PLACEHOLDERS:
        path = out / fname
        text, note = values[key]
        pat = re.compile(r"<b\b[^>]*>" + re.escape(ph) + r"</b>")
        s = path.read_text(encoding="utf-8")
        if not pat.search(s):
            report.append((fname, ph, key, "missing", "placeholder element not found in slide"))
        elif text is None:
            report.append((fname, ph, key, "open", note))
        else:
            path.write_text(pat.sub(lambda m: text, s), encoding="utf-8")
            report.append((fname, ph, key, "filled", f"{text} <- {note}"))
    return report


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", type=Path, default=Path("results.json"))
    ap.add_argument("--targets", type=Path, default=Path("targets.json"))
    ap.add_argument("--src", type=Path, default=Path("deck/slides"))
    ap.add_argument("--out", type=Path, default=Path("deck-filled/slides"))
    a = ap.parse_args(argv)

    def load(p: Path) -> dict:
        if not p.is_file():
            print(f"note: {p} not found, treated as empty")
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    report = fill(a.src, a.out, load(a.results), load(a.targets))
    for fname, ph, key, status, note in report:
        print(f"{status.upper():7} {fname:14} {ph:26} {key}: {note}")
    nf = sum(r[3] == "filled" for r in report)
    print(f"\n{nf} filled, {len(report) - nf} still open. Output: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
