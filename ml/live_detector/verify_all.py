"""Wide verification of the saved 0.5 s model: in-sample Hinglish, English ASVspoof (not us), noise/silence."""
import sys, numpy as np, pandas as pd, soundfile as sf
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import detector as D
from raksham_paths import SEHAJ
DS = str(SEHAJ)
m = D.Detector(str(HERE / 'model_0p5s.npz')); W = 8000
L=pd.read_csv(DS+"/labels.csv")
def judge(x):
    ps=[];tot=0
    for s in range(0,len(x)-W+1,4000):
        tot+=1; w=x[s:s+W]
        if D.has_speech(w): ps.append(m.score(w))
    return ps,tot
nm={"uwrncdc6":"Kushagra","vukqxv0v":"Yash","n5heuy41":"Pranjal"}
print("\n== A. ALL 1,800 Hinglish clips (model was trained on these, so optimistic) ==")
H=L[L.language=='hinglish']; rows=[]
for _,r in H.iterrows():
    ps,tot=judge(sf.read(f"{DS}/{r.file}",dtype='float32')[0])
    rows.append((nm[r.speaker_id],r.condition,r.label_id,np.mean(ps) if ps else np.nan,np.mean(np.array(ps)>.5) if ps else np.nan,len(ps)/max(tot,1)))
R=pd.DataFrame(rows,columns=['spk','cond','y','p','win_real','judged'])
R['clip_ok']=((R.p>.5)==R.y); R['win_ok']=np.where(R.y==1,R.win_real,1-R.win_real)
print(f"clips with no judged speech: {R.p.isna().sum()}; clip accuracy {R.clip_ok[R.p.notna()].mean():.4f}; window accuracy {R.win_ok.mean():.4f}")
print(R.groupby('spk')[['clip_ok','win_ok']].mean().round(3).to_string()); print(R.groupby('cond')[['clip_ok','win_ok']].mean().round(3).to_string())
print("\n== B. ENGLISH ASVspoof clean (5,000 other people - NOT the 3 of us) ==")
E=L[(L.language=='english')&(L.condition=='clean')]
rows=[]
for _,r in E.iterrows():
    ps,tot=judge(sf.read(f"{DS}/{r.file}",dtype='float32')[0])
    rows.append((r.label_id,np.mean(ps) if ps else np.nan,len(ps)>0))
Q=pd.DataFrame(rows,columns=['y','p','speech'])
for y,name in ((1,'real English speakers'),(0,'fake English (ASVspoof attacks)')):
    q=Q[(Q.y==y)&Q.speech]; print(f"{name:34} n={len(q)} judged REAL: {(q.p>.5).mean():.3f}  judged FAKE: {(q.p<=.5).mean():.3f}")
print("=> real strangers are mostly called FAKE: the model is built to confirm the 3 of us, not to accept anyone's real voice.")
print("\n== C. non-speech through the full pipeline (gate + model) ==")
rng=np.random.default_rng(0)
def colored(n,b):
    f=np.fft.rfftfreq(n);a=np.ones_like(f);a[1:]=f[1:]**(-b/2);x=np.fft.irfft(a*np.exp(2j*np.pi*rng.random(len(f))),n);return x/x.std()
for name,mk in {'white':lambda:colored(16000,0),'pink':lambda:colored(16000,1),'rumble':lambda:colored(16000,2),'clicks':lambda:np.where(rng.random(16000)<0.002,rng.standard_normal(16000)*8,0)+0.1*colored(16000,0)}.items():
    fake=judged=0
    for _ in range(100):
        x=(mk()*10**rng.uniform(-3.5,-0.9)).astype(np.float32); ps,tot=judge(x); judged+=len(ps); fake+=sum(p<=.5 for p in ps)
    print(f"{name:8} windows judged as speech: {judged}/{100*tot}; of those called FAKE: {fake}")
sil=[];fl=0;tw=0
for f in H[H.condition=='clean'].file[:400]:
    x=sf.read(f"{DS}/{f}",dtype='float32')[0]; head=x[:6000]
    tw+=1; fl+=D.has_speech(np.r_[head,np.zeros(max(0,W-len(head)))].astype(np.float32)) if len(head)>0 else 0
print(f"recording lead-in (first 0.4 s, before speaking): passed as speech {fl}/{tw}")
