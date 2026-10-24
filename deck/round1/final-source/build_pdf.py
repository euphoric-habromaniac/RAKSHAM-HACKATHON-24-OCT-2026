import json, asyncio
from playwright.async_api import async_playwright
import os
D=os.environ.get('DECK_PROJECT',os.path.dirname(os.path.abspath(__file__)))  # folder holding deck.json and slides/
deck=json.load(open(f'{D}/deck.json',encoding='utf-8'))
fonts=''.join(f'<link rel="stylesheet" href="{f["href"]}">' for f in deck['faces'].values())
CSS='''*{box-sizing:border-box}@page{size:1920px 1080px;margin:0}html,body{margin:0;padding:0}
section{width:1920px;height:1080px;position:relative;overflow:hidden;page-break-after:always;break-after:page}
h1,h2,h3,p,ul,ol{margin:0}table{border-collapse:collapse;width:100%}td,th{padding:0.35em 0.6em;border:1px solid #6F7D94;vertical-align:top}aside{display:none}x-shape,x-connector{display:block}'''
SHIM='''
document.querySelectorAll('x-shape').forEach(e=>{const k=e.getAttribute('kind');
 if(k==='diamond'){e.style.clipPath='polygon(50% 0,100% 50%,50% 100%,0 50%)';}
 if(k==='arrow-right'){e.style.clipPath='polygon(0 30%,60% 30%,60% 0,100% 50%,60% 100%,60% 70%,0 70%)';e.style.border='none'}});
document.querySelectorAll('section').forEach(sec=>{
const NS='http://www.w3.org/2000/svg';const svg=document.createElementNS(NS,'svg');
svg.setAttribute('width',1920);svg.setAttribute('height',1080);svg.style.cssText='position:absolute;left:0;top:0;pointer-events:none';
sec.querySelectorAll('x-connector').forEach(e=>{
 let [x1,y1,x2,y2]=['x1','y1','x2','y2'].map(a=>+e.getAttribute(a));const r=e.getAttribute('route')||'straight';
 const col=e.style.color||'#000';const w=parseFloat(e.style.borderWidth)||2;const dash=e.style.borderStyle==='dashed';const both=e.getAttribute('head')==='both';
 let pts;if(r==='hv')pts=[[x1,y1],[x2,y1],[x2,y2]];else if(r==='vh')pts=[[x1,y1],[x1,y2],[x2,y2]];else if(r==='elbow'){const mx=(x1+x2)/2;pts=[[x1,y1],[mx,y1],[mx,y2],[x2,y2]]}else pts=[[x1,y1],[x2,y2]];
 const pl=document.createElementNS(NS,'polyline');pl.setAttribute('points',pts.map(p=>p.join(',')).join(' '));
 pl.setAttribute('fill','none');pl.setAttribute('stroke',col);pl.setAttribute('stroke-width',w);if(dash)pl.setAttribute('stroke-dasharray','10 6');svg.appendChild(pl);
 const head=(a,b,c,d)=>{const ang=Math.atan2(d-b,c-a),L=14;const t=document.createElementNS(NS,'polygon');
  t.setAttribute('points',[[c,d],[c-L*Math.cos(ang-0.45),d-L*Math.sin(ang-0.45)],[c-L*Math.cos(ang+0.45),d-L*Math.sin(ang+0.45)]].map(p=>p.join(',')).join(' '));t.setAttribute('fill',col);svg.appendChild(t)};
 const n=pts.length;head(...pts[n-2],...pts[n-1]);if(both)head(...pts[1],...pts[0]);
 e.remove()});
sec.appendChild(svg);});
'''
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page(viewport={'width':1920,'height':1080})
        body=''.join(open(f'{D}/slides/{s}.html',encoding='utf-8').read() for s in deck['order'])
        await pg.set_content(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Asli Awaaz, Round 1</title>{fonts}<style>{CSS}</style></head><body>{body}</body></html>',wait_until='networkidle')
        await pg.evaluate('document.fonts.ready'); await pg.evaluate(SHIM)
        await pg.pdf(path=os.environ.get('PDF_OUT',os.path.join(D,'final.pdf')),width='1920px',height='1080px',print_background=True,margin={'top':'0','bottom':'0','left':'0','right':'0'},tagged=True,outline=True)
        await b.close()
asyncio.run(main())

# Blank the generator labels so the file carries only its title.
from pypdf import PdfReader, PdfWriter
_out=os.environ.get('PDF_OUT',os.path.join(D,'final.pdf'))
_r=PdfReader(_out); _w=PdfWriter(clone_from=_r)
_w.add_metadata({'/Title':'Asli Awaaz, Round 1','/Creator':'','/Producer':''})
with open(_out,'wb') as _f: _w.write(_f)
