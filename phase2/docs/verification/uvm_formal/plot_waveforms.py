"""Plot selected actual UVM clock samples and a formal counterexample VCD."""
from pathlib import Path
import argparse,csv,hashlib,json,sys

ap=argparse.ArgumentParser()
ap.add_argument('--python-packages',type=Path)
ap.add_argument('--uvm-timing',type=Path,required=True)
ap.add_argument('--fifo-vcd',type=Path,required=True)
args=ap.parse_args()
if args.python_packages:sys.path.insert(0,str(args.python_packages.resolve()))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'figures';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Serif','font.size':11,'pdf.fonttype':42})
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(fig,name):
    fig.savefig(OUT/(name+'.pdf'),bbox_inches='tight',metadata={'CreationDate':None})
    fig.savefig(OUT/(name+'.png'),dpi=180,bbox_inches='tight');plt.close(fig)
def traces(rows,xkey,fields,title,xlabel,name):
    fig,axes=plt.subplots(len(fields),1,figsize=(10,max(4.6,len(fields)*.82)),sharex=True)
    for ax,(field,label) in zip(axes,fields):
        ax.step([r[xkey] for r in rows],[r[field] for r in rows],where='post',color='.15',linewidth=1.5)
        ax.set_ylabel(label,rotation=0,ha='right',va='center',labelpad=15)
        ax.spines[['top','right']].set_visible(False)
        ax.grid(axis='x',color='.88',linewidth=.6)
        values=[r[field] for r in rows]
        if max(values)<=1:ax.set_ylim(-.2,1.2);ax.set_yticks([0,1])
        else:ax.set_ylim(min(values)-.25,max(values)+.25);ax.set_yticks(sorted(set(values)))
    axes[0].set_title(title,pad=14)
    axes[-1].set_xlabel(xlabel)
    fig.subplots_adjust(left=.17,right=.98,top=.90,bottom=.12,hspace=.20)
    save(fig,name)

with args.uvm_timing.open(newline='') as f:uvm=list(csv.DictReader(f))
uvm=[{k:int(v) for k,v in r.items()} for r in uvm]
tail=[r for r in uvm if r['epoch']==1 and r['y_valid']==1 and r['y_index']==1535]
if not tail:raise ValueError('No complete observed final-Y window')
t0=min(r['time_ns'] for r in tail)
window=[dict(r,cycle=(r['time_ns']-t0)//10) for r in uvm if r['epoch']==1 and t0<=r['time_ns']<=t0+500]
if sum(r['y_valid'] and not r['y_ready'] for r in window)!=33:raise ValueError('Expected seed1 final-Y hold33 observed edges')
if not any(r['done'] for r in window):raise ValueError('DONE must be observed after held output')
if any(r['done'] or not r['busy'] for r in window if r['y_valid'] and not r['y_ready']):raise ValueError('Final-Y hold violated ownership')
traces(window,'cycle',[('y_valid','Y valid'),('y_ready','Y ready'),('busy','Busy'),('done','Done')],
       'UVM observation: final waveform sample held for 33 clock edges',
       'Simulation clock edges relative to first final-Y stall (10 ns per edge)','uvm_final_y')

def parse_vcd(path):
    scopes=[];names={};vals={};records=[];time=0;in_defs=True
    for raw in path.read_text().splitlines():
        line=raw.strip()
        if in_defs:
            tok=line.split()
            if line.startswith('$scope'):scopes.append(tok[2])
            elif line.startswith('$upscope'):scopes.pop()
            elif line.startswith('$var'):names[tok[3]]='.'.join(scopes+[tok[4]])
            elif line.startswith('$enddefinitions'):in_defs=False
            continue
        if line.startswith('#'):
            if vals:records.append((time,dict(vals)))
            time=int(line[1:])
        elif line.startswith('b'):
            bits,code=line[1:].split();vals[names.get(code,code)]=None if any(c in bits.lower() for c in 'xz') else int(bits,2)
        elif line and line[0] in '01xz' and not line.startswith('$'):
            vals[names.get(line[1:],line[1:])]=int(line[0]) if line[0] in '01' else None
    if vals:records.append((time,dict(vals)))
    by_step={}
    keys=['rst_n','clear_i','push_i','pop_i','level_o','full_o']
    for time,record in records:
        if time%10 or 'smt_step' not in record:continue
        row={'step':record['smt_step']}
        for k in keys:row[k]=record['fifo_formal.'+k]
        if any(v is None for v in row.values()):raise ValueError('Unknown displayed formal value')
        by_step[row['step']]=row
    return list(by_step.values())
formal=parse_vcd(args.fifo_vcd)
if not formal or not any(r['full_o'] for r in formal):raise ValueError('Negative witness must reach full')
traces(formal,'step',[('rst_n','Reset n'),('clear_i','Clear'),('push_i','Push request'),('pop_i','Pop request'),('level_o','Occupancy'),('full_o','Full')],
       'Formal counterexample to the deliberately false never-full property',
       'Solver step (symbolic witness, not measured hardware time)','formal_counterexample')
data={'uvm':{'input_sha256':sha(args.uvm_timing),'epoch':1,'seed':1,'samples':window},
      'formal':{'input_sha256':sha(args.fifo_vcd),'property':'a_deliberately_false_never_full','samples':formal},
      'generator_sha256':sha(Path(__file__)),'matplotlib':matplotlib.__version__}
(ROOT/'waveform_data.json').write_text(json.dumps(data,indent=2)+'\n')
print(json.dumps({'uvm_samples':len(window),'formal_steps':len(formal),'status':'RENDERED_ACTUAL_OBSERVATIONS'}))
