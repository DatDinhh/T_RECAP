"""Render academic verification diagrams and evidence excerpts, without running RTL."""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path

ap=argparse.ArgumentParser()
ap.add_argument('--python-packages',type=Path)
args=ap.parse_args()
if args.python_packages:sys.path.insert(0,str(args.python_packages.resolve()))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch,FancyArrowPatch

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'figures';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Serif','font.size':11,'pdf.fonttype':42,
                     'axes.spines.top':False,'axes.spines.right':False})
def panel(w=11,h=5.5):
    fig,ax=plt.subplots(figsize=(w,h));fig.subplots_adjust(left=.02,right=.98,bottom=.02,top=.98)
    ax.set_xlim(0,11);ax.set_ylim(0,6);ax.axis('off');return fig,ax
def box(ax,x,y,w,h,text,shade='.96'):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.04,rounding_size=0.08',
                              edgecolor='.2',facecolor=shade,linewidth=1.1))
    ax.text(x+w/2,y+h/2,text,ha='center',va='center',linespacing=1.35)
def arrow(ax,a,b,label=None):
    ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=13,color='.2',linewidth=1.1))
    if label:ax.text((a[0]+b[0])/2,(a[1]+b[1])/2+.13,label,ha='center',va='bottom',fontsize=9)
def save(fig,name):
    fig.savefig(OUT/(name+'.pdf'),metadata={'Creator':'TRECAP verification report','CreationDate':None})
    fig.savefig(OUT/(name+'.png'),dpi=180);plt.close(fig)

fig,ax=panel()
box(ax,.3,4.65,3.1,.85,'UVM test and environment\nconfiguration, phases, objections')
box(ax,.3,2.9,2.7,1.05,'Sequence / sequencer\nepoch configuration\nseeded schedules')
box(ax,4.0,2.9,2.7,1.05,'Driver + virtual interface\nPCM, reset, start\noutput backpressure')
box(ax,7.9,2.9,2.7,1.05,'Unchanged TSH2 RTL\nFFT / threshold / IFFT\nY and spectral export')
box(ax,7.9,.95,2.7,1.05,'Passive monitor\naccepted transfers\nheld data and completion')
box(ax,4.0,.95,2.7,1.05,'Analysis-port scoreboard\nexact values and ordering\nobserved event counts')
box(ax,.3,.95,2.7,1.05,'Admitted fixtures\nindependent reference\nimmutable expected outputs')
arrow(ax,(1.65,4.65),(1.65,3.95));arrow(ax,(3,3.42),(4,3.42))
arrow(ax,(6.7,3.42),(7.9,3.42));arrow(ax,(9.25,2.9),(9.25,2))
arrow(ax,(7.9,1.47),(6.7,1.47));arrow(ax,(3,1.47),(4,1.47))
ax.text(5.5,.25,'Result gate: complete comparisons, required events, clean reports, bounded completion',ha='center',fontsize=10)
save(fig,'uvm_architecture')

fig,ax=panel()
box(ax,.35,4.6,3.0,.9,'Implementation RTL\nsource hashes + parameters')
box(ax,4.0,4.6,3.0,.9,'Harness\nassertions + explicit assumptions')
box(ax,7.65,4.6,3.0,.9,'Reachability / fault controls\ncover goals + false properties')
box(ax,3.35,2.85,4.3,1.0,'Yosys frontend and SBY engine\ntransition system + solver')
arrow(ax,(1.85,4.6),(4.1,3.85));arrow(ax,(5.5,4.6),(5.5,3.85));arrow(ax,(9.15,4.6),(6.9,3.85))
box(ax,.35,.65,3.0,1.15,'Safety result\nproof or bounded check\nexact assumptions and instance')
box(ax,4.0,.65,3.0,1.15,'Cover result\nreachable witness\nwithin declared search depth')
box(ax,7.65,.65,3.0,1.15,'Negative control\nexpected assertion failure\ninspect counterexample')
arrow(ax,(4.1,2.85),(1.85,1.8));arrow(ax,(5.5,2.85),(5.5,1.8));arrow(ax,(6.9,2.85),(9.15,1.8))
ax.text(5.5,.15,'A timeout, UNKNOWN or unsupported frontend is never counted as a proof.',ha='center',fontsize=10)
save(fig,'formal_architecture')

manifest={'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'matplotlib':matplotlib.__version__,'kind':'conceptual verification architecture diagrams',
          'files':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in sorted(OUT.glob('*')) if p.suffix in ('.pdf','.png')]}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'figures':len(manifest['files']),'status':'RENDERED_DIAGRAMS'}))
