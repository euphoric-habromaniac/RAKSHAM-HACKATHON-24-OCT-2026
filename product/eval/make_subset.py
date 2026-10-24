"""Link or copy the --limit subset of an ASVspoof protocol into its own directory.

Degrading all 71k eval files per condition is slow. This picks the same
subset that eval.run_aasist picks for the same --limit/--seed/--balanced, so
degrade.telephony only has to process those files.

    python -m eval.make_subset --protocol <eval.trl.txt> --audio-dir <eval flac dir> \
        --limit 5000 --out subset5000/flac
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_aasist import find_audio, read_protocol, subset  # noqa: E402


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--protocol", type=Path, required=True)
    ap.add_argument("--audio-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, required=True)
    ap.add_argument("--balanced", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--copy", action="store_true", help="copy instead of symlink")
    a = ap.parse_args(argv)

    items = subset(read_protocol(a.protocol), a.limit, a.seed, a.balanced)
    a.out.mkdir(parents=True, exist_ok=True)
    missing = 0
    for utt, _ in items:
        src = find_audio(a.audio_dir, utt)
        if src is None:
            missing += 1
            continue
        dst = a.out / src.name
        if dst.exists() or dst.is_symlink():
            continue
        if a.copy:
            shutil.copy2(src, dst)
        else:
            try:
                os.symlink(src.resolve(), dst)
            except OSError:
                shutil.copy2(src, dst)
    if missing:
        print(f"error: {missing} files missing in {a.audio_dir}", file=sys.stderr)
        return 2
    print(f"{len(items)} files in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
