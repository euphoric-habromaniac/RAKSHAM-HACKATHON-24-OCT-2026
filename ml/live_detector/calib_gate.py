import sys, numpy as np, pandas as pd, soundfile as sf
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import detector as D
from raksham_paths import SEHAJ
DS = str(SEHAJ)
L=pd.read_csv(DS+"/labels.csv"); H=L[(L.language=='hinglish')&(L.condition.isin(['clean','gsm']))].sample(240,random_state=0)
rng=np.random.default_rng(0); win=8000
for tag,sel in (('real',H.label_id==1),('fake',H.label_id==0)):
    tot=ok=lt=lo=0
    for f in H[sel].file:
        x=sf.read(f"{DS}/{f}",dtype='float32')[0]
        for s in range(0,len(x)-win+1,4000):
            w=x[s:s+win]; g=D.has_speech(w); tot+=1; ok+=g
            if np.sqrt(np.mean(w**2))>0.01: lt+=1; lo+=g
    print(f"{tag} windows passing gate: {ok}/{tot} = {ok/tot:.3f}  | of LOUD windows (rms>0.01, i.e. speaking): {lo}/{lt} = {lo/lt:.3f}")
def colored(n,beta):
    f=np.fft.rfftfreq(n); a=np.ones_like(f); a[1:]=f[1:]**(-beta/2); x=np.fft.irfft(a*np.exp(2j*np.pi*rng.random(len(f))),n); return x/x.std()
res={}
for name,mk in {'white':lambda:colored(8000,0),'pink':lambda:colored(8000,1),'brown(rumble)':lambda:colored(8000,2),
                'fan hum 120Hz+noise':lambda:np.sin(2*np.pi*120*np.arange(8000)/16000)+0.5*colored(8000,1),
                'keyboard clicks':lambda:np.where(rng.random(8000)<0.002,rng.standard_normal(8000)*8,0)+0.1*colored(8000,0)}.items():
    hits=0;N=300
    for _ in range(N):
        lvl=10**rng.uniform(-3.5,-0.9)   # -70 .. -18 dBFS rms
        hits+=D.has_speech((mk()*lvl).astype(np.float32))
    print(f"{name:22} passes gate: {hits}/{N}")
