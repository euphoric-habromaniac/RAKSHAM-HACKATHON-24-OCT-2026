"""Read a recordings folder (downloads/recordings_awaaz or an unzipped zip) for ingest and verify.

    <Speaker Name>/N.wav  profile.json  consent.json     N = sentence number 1..100
Speaker id comes from profile.json, consent from consent.json, the phrase id from prompts.json by sentence number.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path
from typing import Optional

from service.consent import ConsentRecord
from tools.recorder.prompts import load_prompts, prompt_by_number
from tools.recorder.store import PROMPT_COUNT, read_json

_CLIP = re.compile(r"^([1-9]\d{0,2})\.wav$")


def speaker_folders(incoming: Path) -> list:
    """Sub-folders that hold a profile.json (a recorder speaker folder)."""
    return sorted(d for d in Path(incoming).iterdir() if d.is_dir() and (d / "profile.json").is_file())


def is_recorder_layout(incoming: Path) -> bool:
    return Path(incoming).is_dir() and bool(speaker_folders(incoming))


def _duration(path: Path) -> str:
    try:
        with wave.open(str(path), "rb") as w:
            return f"{w.getnframes() / w.getframerate():.2f}"
    except (wave.Error, EOFError, OSError, ZeroDivisionError):
        return ""


def scan_rows(incoming: Path, prompts: Optional[list] = None) -> list:
    """One row per N.wav on disk, with the 9 ingest columns plus `path`, `consent_file`, `sentence_number`."""
    prompts = prompts or load_prompts()
    rows = []
    for d in speaker_folders(incoming):
        prof = read_json(d / "profile.json")
        for f in sorted(d.iterdir(), key=lambda p: (len(p.name), p.name)):
            m = _CLIP.match(f.name)
            if not (m and f.is_file() and 1 <= int(m.group(1)) <= PROMPT_COUNT):
                continue
            n = int(m.group(1))
            p = prompt_by_number(prompts, n)
            rows.append({"speaker_id": str(prof.get("speaker_id", "")), "phrase_id": p.get("id", ""), "language": p.get("lang", ""),
                         "accent_group": prof.get("accent_group", ""), "age_band": prof.get("age_band", ""),
                         "gender": prof.get("gender", ""), "device": prof.get("device", ""), "duration_s": _duration(f),
                         "file": f"{d.name}/{f.name}", "path": f, "consent_file": d / "consent.json", "sentence_number": n})
    return rows


def load_consent(path: Path) -> Optional[ConsentRecord]:
    """The folder's consent.json as a ConsentRecord (None if missing or unreadable)."""
    data = read_json(Path(path))
    try:
        return ConsentRecord.model_validate(data) if data else None
    except ValueError:
        return None
