import sys, json, numpy as np
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); import detector as D
m=np.load(HERE / 'model_0p5s.npz'); r=lambda a:np.round(np.asarray(a,np.float64),6).tolist()
json.dump({'win':int(m['win']),'mu':r(m['mu']),'sd':r(m['sd']),'fb':r(D._FB),'dct':r(D._DCT),'hann':r(D._WIN),
           'layers':[{'W':r(m[f'W{i}']),'b':r(m[f'b{i}'])} for i in range(int(m['n_layers']))]},open(HERE / 'demo' / 'model.json','w'),separators=(',',':'))
print('exported model.json')
