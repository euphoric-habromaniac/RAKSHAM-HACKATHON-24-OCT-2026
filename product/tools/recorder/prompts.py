"""The 100 prompts (tools/recorder/prompts.json is the single source of truth) and the texts derived from them."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

PROMPTS_JSON = Path(__file__).resolve().parent / "prompts.json"
TITLE = {"hindi": "Hindi", "english": "English", "hinglish": "Hinglish"}
HOW_TO = [
    "- Sit in a quiet room: door shut, fans and AC off, phone on silent.",
    "- Keep the microphone about a hand-span away and speak at your normal speed.",
    "- One clip per line: press Record, pause a moment, read the line, press Stop.",
    "- Say it naturally, the way you would say it on a phone call. Do not over-act.",
    "- Read digit strings one digit at a time and amounts exactly as written.",
    "- If you make a mistake, press Redo and read the line again.",
    "- You may skip a line you cannot read and come back to it later.",
]


def parse_prompts(text: str) -> list:
    """[{id, n, lang, topic, text}] in recording order."""
    return json.loads(text)


def load_prompts(path: Path = PROMPTS_JSON) -> list:
    return parse_prompts(Path(path).read_text(encoding="utf-8"))


def prompt_by_number(prompts: list, n: int) -> dict:
    return prompts[n - 1] if 1 <= n <= len(prompts) else {}


def script_text(prompts: list) -> str:
    """docs/SPEAKER_SCRIPT.txt: everything the speaker has to say, in recording order."""
    count = lambda lang: sum(1 for p in prompts if p["lang"] == lang)  # noqa: E731
    head = ["ASLI AWAAZ - SPEAKER SCRIPT",
            f"{len(prompts)} lines to read aloud ({count('hindi')} Hindi, {count('english')} English, "
            f"{count('hinglish')} Hinglish), in the same order as the recording app.",
            "", "HOW TO RECORD", *HOW_TO, "", "LINES", ""]
    lines = [f"{p['n']:03d}  [{p['id']} | {TITLE[p['lang']]} | {p['topic']}]\n     {p['text']}\n" for p in prompts]
    return "\n".join(head + lines)


def prompts_csv(prompts: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["n", "id", "language", "topic", "text"])
    for p in prompts:
        w.writerow([p["n"], p["id"], p["lang"], p["topic"], p["text"]])
    return buf.getvalue()
