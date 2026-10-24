"""Train the live detector on sehaj_dataset hinglish rows; sentence-disjoint 5-fold CV; export numpy .npz."""
import sys, time, warnings
from pathlib import Path
import numpy as np, pandas as pd, soundfile as sf
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn import metrics
sys.path.insert(0, str(Path(__file__).parent))
import detector as D
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raksham_paths import SEHAJ as DS
OUT = Path(__file__).parent
L = pd.read_csv(DS / "labels.csv"); H = L[L.language == "hinglish"].reset_index(drop=True)
H["sent"] = H.file.str.extract(r"_(\d{3})_")[0].astype(int)
H["fold"] = H.sent % 5
audio = [sf.read(DS / f, dtype="float32")[0] for f in H.file]
print("loaded", len(audio), flush=True)

def windows(win, hop=4000):
    X, rows = [], []
    for i, x in enumerate(audio):
        for s in range(0, len(x) - win + 1, hop):
            w = x[s:s + win]
            if D.is_silent(w): continue
            X.append(D.features(w)); rows.append(i)
    return np.array(X), np.array(rows)

def mk(kind):
    if kind == "LogReg": return make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=3000))
    return make_pipeline(StandardScaler(), MLPClassifier((128, 64), alpha=1e-2, early_stopping=True, max_iter=200, random_state=0))

def export(model, win, path):
    sc, clf = model[0], model[-1]
    if hasattr(clf, "coefs_"): Ws, bs = clf.coefs_, clf.intercepts_
    else: Ws, bs = [clf.coef_.T], [clf.intercept_]
    d = {"win": win, "mu": sc.mean_.astype(np.float32), "sd": sc.scale_.astype(np.float32), "n_layers": len(Ws)}
    for i, (W, b) in enumerate(zip(Ws, bs)): d[f"W{i}"] = W.astype(np.float32); d[f"b{i}"] = np.asarray(b, np.float32)
    np.savez(path, **d)

best_of = {}
for win, tag in ((8000, "0p5s"), (16000, "1p0s")):
    t0 = time.time(); X, ridx = windows(win); y = H.label_id.values[ridx]
    print(f"\n=== window {win/16000:.1f}s: {len(X)} windows ({time.time()-t0:.0f}s) ===", flush=True)
    fold = H.fold.values[ridx]; cond = H.condition.values[ridx]; clip = ridx
    scores = {}
    for kind in ("LogReg", "MLP"):
        p = np.zeros(len(X))
        for f in range(5):
            te = fold == f; p[te] = mk(kind).fit(X[~te], y[~te]).predict_proba(X[te])[:, 1]
        acc = ((p > .5) == y).mean(); scores[kind] = acc
        sp = H.speaker_id.values[ridx]; nm = {"uwrncdc6": "Kushagra", "vukqxv0v": "Yash", "n5heuy41": "Pranjal"}
        print("   per speaker (out-of-fold): " + " ".join(f"{nm[k]}={((p[sp==k]>.5)==y[sp==k]).mean():.3f}" for k in nm))
        pc = pd.Series(p).groupby(clip).mean(); yc = H.label_id.values[pc.index]
        spk = H.speaker_id.values[ridx]
        per = {c: ((p[cond == c] > .5) == y[cond == c]).mean() for c in ("clean", "gsm", "g711u")}
        fk, rl = y == 0, y == 1
        print(f"{kind:7} window acc={acc:.3f} AUC={metrics.roc_auc_score(y,p):.3f} fake-caught={(p[fk]<=.5).mean():.3f} real-ok={(p[rl]>.5).mean():.3f} | "
              + " ".join(f"{c}={v:.3f}" for c, v in per.items()) + f" | whole-clip acc={((pc>.5).values==yc).mean():.3f}", flush=True)
    kind = max(scores, key=scores.get); model = mk(kind).fit(X, y)
    export(model, win, OUT / f"model_{tag}.npz"); print(f"saved model_{tag}.npz ({kind})", flush=True)
    m = D.Detector(OUT / f"model_{tag}.npz"); w = audio[0][:win]
    t = time.perf_counter(); [m.score(w) for _ in range(200)]; print(f"latency per decision: {(time.perf_counter()-t)/200*1000:.1f} ms (numpy only)", flush=True)
print("ALL_DONE")
