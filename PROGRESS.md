# Progress log

Append one line per hour or per milestone: time, who, what, commit, next. Record what is measured, not what is hoped.

## 2026-10-25 (assembly of RAKSHAM)

- **Initialized** unified repository structure for RAKSHAM.
- **Fixed** every hard-coded path in `ml/` (one module, `ml/raksham_paths.py`); `rak.py` is the single entry point.
- **Integrated** the live detector into the product as an opt-in L2: `ASLI_L2_BACKEND=live` (`product/service/live_scorer.py`, 5 tests).
- **Verified** from the new folder: `python rak.py check` passes; product tests 427 passed, 0 skipped (with `setup --ml`); `ml/live_detector/verify_all.py` reproduces the earlier numbers (100% per clip in-sample, strangers called fake 76.7%); demo saves and reopens a case under `cases/`.
- **Not copied** (too large, regenerable): ASVspoof raw and degraded audio (12.6 GB), fine-tune checkpoints (19.8 GB). `python rak.py link-heavy` links them.
- **Next**: more speakers and a second cloner (expand to more speakers); confirm the ask on deck page 11.

## 2026-10-25 (portability)

- **Verified** a relocated copy (path with spaces, no .venv): `rak.py setup` then `rak.py check` passed (415 passed, 7 torch tests skipped without --ml); demo served.
- **Added** `rak.py pack`, stale-venv rebuild in `setup`, junction warning in `doctor`; notebook copy uses relative paths.
