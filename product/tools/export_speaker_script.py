"""Write docs/SPEAKER_SCRIPT.txt (everything the speaker has to say) from tools/recorder/prompts.json.

    python tools/export_speaker_script.py            # rewrite docs/SPEAKER_SCRIPT.txt
    python tools/export_speaker_script.py --check    # exit 1 if the file is out of date

The recorder server writes the same text to <recordings dir>/SPEAKER_SCRIPT.txt (tools/recorder/prompts.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.recorder.prompts import PROMPTS_JSON, load_prompts, script_text  # noqa: E402

OUT = ROOT / "docs" / "SPEAKER_SCRIPT.txt"


def read_prompts(path: Path = PROMPTS_JSON) -> list:
    """[{id, n, lang, topic, text}] in recording order."""
    return load_prompts(path)


def build(path: Path = PROMPTS_JSON) -> str:
    return script_text(read_prompts(path))


def write(out: Path = OUT, path: Path = PROMPTS_JSON) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(path), encoding="utf-8-sig", newline=chr(10))
    return out


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8-sig") == build()
        print("up to date" if ok else "OUT OF DATE: run python tools/export_speaker_script.py")
        return 0 if ok else 1
    print(f"wrote {write()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
