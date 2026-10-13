"""Supplementary figure: the 1,000 Monte Carlo runs of the case study (S2), as computed by the engine.

Runs engine.run_forecast with the Monte Carlo band (1,000 runs, seed 42) and records the closing
balance of every run; the percentiles and the probability come from the engine itself. Needs the
S2 dataset loaded in PostgreSQL. Output: docs/figures/Supplementary_monte_carlo_1000_futures.png
"""
import sys,json; from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from config import settings
from engine._loader import analyst_engine
import engine._montecarlo as M
from engine._forecast import run_forecast
paths=[]; orig=M.aggregate_weekly
def cap(*a,**k):
    w=orig(*a,**k); paths.append([x['closing'] for x in w]); return w
M.aggregate_weekly=cap
r=run_forecast('S2_big_customer',analyst_engine(settings),scenarios=['expected'],include_mc=True,threshold=509538.0)
band=r['expected'].mc_band
OUT={'paths':paths,'band':{str(k):v for k,v in band.items()}}

import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
d=OUT; P=np.array(d['paths'])/1e3; B=d['band']
T=509.538; wk=np.arange(0,14)
P0=np.hstack([np.full((len(P),1),1200.0),P])
p10=[1200]+[B[str(k)]['p10']/1e3 for k in range(1,14)]; p50=[1200]+[B[str(k)]['p50']/1e3 for k in range(1,14)]; p90=[1200]+[B[str(k)]['p90']/1e3 for k in range(1,14)]
fig,(a,h)=plt.subplots(1,2,figsize=(13,5.6),gridspec_kw={'width_ratios':[2.3,1]})
ORANGE='#c2410c'
def badge(ax,x,y,n,fs=11):
    ax.text(x,y,str(n),ha='center',va='center',fontsize=fs,fontweight='bold',color='white',
            bbox=dict(boxstyle='circle,pad=0.28',fc=ORANGE,ec='none'),zorder=10)
for row in P0: a.plot(wk,row,color='#7f8c8d',alpha=0.04,lw=0.8)
a.fill_between(wk,p10,p90,color='#2E86DE',alpha=0.18,label='Likely range: 8 of every 10 simulations')
a.plot(wk,p50,color='#1B4F9C',lw=2.6,label='Expected balance: the middle simulation')
a.axhline(T,color='#C0392B',ls='--',lw=1.8,label='Minimum to keep (€510k)')
a.plot([],[],color='#7f8c8d',lw=1,label='Each grey line = one simulation (1,000 in all)')
a.axvline(6,color='k',lw=0.8,ls=':')
w=6
badge(a,11,p50[11]+140,1); badge(a,2,p90[2]+150,2)
from matplotlib.patches import FancyBboxPatch
a.add_patch(FancyBboxPatch((7.15,1150),5.0,520,boxstyle='round,pad=0.05,rounding_size=0.15',fc='white',ec='#999',zorder=8))
a.text(7.35,1590,'Week 6',fontsize=10,fontweight='bold',va='center',zorder=9)
for i,(n,t) in enumerate([(1,f'expected balance €{p50[w]:.0f}k'),(2,f'likely range €{p10[w]:.0f}k – €{p90[w]:.0f}k'),(3,'probability of a shortfall 65%')]):
    yy=1470-i*115; badge(a,7.5,yy,n,fs=9); a.text(7.75,yy,t,fontsize=9.5,va='center',zorder=9)
a.annotate('',xy=(6,p50[w]),xytext=(7.4,1150),arrowprops=dict(arrowstyle='->',color='k'),zorder=9)
a.set_xticks(wk); a.set_xlabel('Week (0 = today, 28 Sept 2026)'); a.set_ylabel('Bank balance (€k)')
a.set_title('Case study: 1,000 simulations of the bank balance',fontsize=12,loc='left')
_h,_l=a.get_legend_handles_labels(); a.legend([_h[i] for i in (1,0,2,3)],[_l[i] for i in (1,0,2,3)],loc='lower left',fontsize=8.5,framealpha=0.95); a.grid(alpha=0.25)
x=P[:,5]; below=x<T
bins=np.linspace(x.min(),x.max(),30)
h.hist(x[below],bins=bins,color='#C0392B',alpha=0.8,label=f'Below the minimum: {below.sum()} of 1,000 = {below.sum()/10:.0f}%')
h.hist(x[~below],bins=bins,color='#2E86DE',alpha=0.8,label=f'Above the minimum: {(~below).sum()} of 1,000')
h.axvline(p50[w],color='#1B4F9C',lw=2.2,label=f'Expected balance: €{p50[w]:.0f}k'); h.axvline(T,color='#C0392B',ls='--',lw=1.8,label='Minimum: €510k'); h.set_ylim(0,135)
badge(h,150,72,3); badge(h,p50[w]-35,108,1)
h.set_title('Week 6: where the 1,000 simulations end',fontsize=12,loc='left'); h.set_xlabel('Bank balance in week 6 (€k)'); h.set_ylabel('Number of simulations')
h.legend(fontsize=8.5,loc='upper left'); h.grid(alpha=0.25)
plt.tight_layout(); plt.savefig(str(Path(__file__).resolve().parent.parent/'docs/figures/Supplementary_monte_carlo_1000_futures.png'),dpi=150)
print(round(p10[w]),round(p50[w]),round(p90[w]),below.sum(),x.min().round(),x.max().round())
