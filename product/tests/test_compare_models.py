import numpy as np

from eval import compare_models as C
from eval.run_aasist import write_scores
from tools.hinglish_data import write_manifest


def test_report_only_with_accents_and_borrowed_spoof(tmp_path):
    rng = np.random.default_rng(0)
    out, hg = tmp_path / "res", tmp_path / "hg"
    spk = [f"s{i % 6}" if i < 50 else "t1" for i in range(60)]
    man = [{"utt_id": f"bf__{spk[i]}__p{i}", "speaker_id": spk[i], "phrase_id": f"p{i}",
            "label": "bonafide", "accent_group": "Hindi" if i < 50 else "Tamil"} for i in range(60)]
    write_manifest(hg / "manifest.csv", man)
    for lab, sep in [("base", 1.0), ("ft", 2.0)]:
        for cond in ("clean16k", "gsm"):
            la = [(f"u{i}", 1, float(rng.normal(sep, 1)), 0.0) for i in range(100)] + \
                 [(f"v{i}", 0, float(rng.normal(-sep, 1)), 0.0) for i in range(100)]
            write_scores(out / lab / f"{cond}.csv", la)
            write_scores(out / lab / "hinglish" / f"{cond}.csv",
                         [(m["utt_id"], 1, float(rng.normal(sep, 1)), 0.0) for m in man])
    text = C.build_report(out, ["base", "ft"], hg, min_n=20)
    assert "## LA eval subset" in text and "## Hinglish held-out" in text
    assert "*" in text  # borrowed spoof side is flagged
    assert "| Hindi | 6 |" in text
    assert "| Tamil | 1 | n<20 | n<20 |" in text  # 10 clips: not scored
    assert "Uncertainty" in text
