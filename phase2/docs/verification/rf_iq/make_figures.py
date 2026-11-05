"""Render report figures from published scalar evidence and an actual RTL VCD."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

HERE = Path(__file__).resolve().parent
FIG = HERE / 'figures'
FIG.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                     'axes.labelcolor':'#253447','text.color':'#253447','axes.titleweight':'bold'})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical():
    p = HERE/'evidence/historical_projection.json'
    data = json.loads(p.read_text())['physical_run']['cases']
    names = ['0 sparse', '$10^8$ dense', '$10^8$ sparse', '$10^{10}$ sparse', '$10^{11}$ sparse']
    colors = ['#8191a5','#4a6c8d','#168b8c','#168b8c','#168b8c']
    fig, ax = plt.subplots(1,2,figsize=(10,3.4),layout='constrained')
    sizes = np.array([c['valid_prefix_packet_bytes'] for c in data])/1024
    ax[0].bar(range(5),sizes,color=colors,width=.63)
    dense = data[0]['dense_valid_prefix_bytes']/1024
    ax[0].axhline(dense,color='#c18433',ls=':',label='Full dense spectral packets')
    ax[0].set(ylabel='KiB over 2,049 valid-prefix frames',title='Measured spectral packet bytes')
    ax[0].legend(frameon=False,fontsize=8,loc='upper right')
    for i,y in enumerate(sizes): ax[0].text(i,y+30,f'{y:,.1f}',ha='center',fontsize=8)
    errs = [c['relative_l2_valid_real_pct'] for c in data]
    ax[1].bar(range(5),errs,color=colors,width=.63)
    ax[1].set(ylabel='Relative L2 error (%)',title='Reconstructed waveform error',ylim=(0,42))
    for i,y in enumerate(errs): ax[1].text(i,y+.6,f'{y:.3f}%',ha='center',fontsize=8)
    for a in ax:
        a.set_xticks(range(5),names,rotation=20)
        a.grid(axis='y',alpha=.18)
        a.set_axisbelow(True)
    for ext in ('png','pdf'): fig.savefig(FIG/f'historical_tradeoff.{ext}',dpi=200)
    plt.close(fig)
    (HERE/'evidence/historical_figure_source.json').write_text(json.dumps({'artifact_kind':'derived_plot_from_historical_scalar_results','input':'historical_projection.json','input_sha256':sha(p),'no_new_hardware_execution':True},indent=2)+'\n')


def diagrams():
    def box(ax,x,y,w,h,text,color='#e5f1f1'):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.06',facecolor=color,edgecolor='#45677a',linewidth=1))
        ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=10)
    def arrow(ax,a,b):
        ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'->','lw':1.3,'color':'#45677a'})
    fig,ax=plt.subplots(figsize=(10,2.8),layout='constrained')
    ax.set(xlim=(0,10),ylim=(0,2.8))
    ax.axis('off')
    positions=[.1,2.65,5.2,7.75]
    texts=['Laptop\nRecorded CU8 file','HPS\nTransport and MMIO','FPGA RF adapter\nFIR and real-IF conversion','Existing FPGA core\nFFT, threshold, IFFT/WOLA']
    for x,text in zip(positions,texts): box(ax,x,1.65,2.1,.75,text)
    for x in positions[:-1]: arrow(ax,(x+2.17,2.02),(x+2.48,2.02))
    box(ax,7.75,.2,2.1,.8,'Separate outputs\nY waveform and TSP1 powers','#ece8f4')
    box(ax,4.35,.2,2.45,.8,'HPS queues\nRead and return output bytes','#f5ebd6')
    box(ax,.4,.2,2.75,.8,'Laptop checks and display\nOptional RF packet decoder','#e8edf5')
    arrow(ax,(8.8,1.59),(8.8,1.07))
    arrow(ax,(7.68,.6),(6.87,.6))
    arrow(ax,(4.28,.6),(3.22,.6))
    for ext in ('png','pdf'): fig.savefig(FIG/f'system_boundary.{ext}',dpi=200)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,3.4),layout='constrained')
    ax.set(xlim=(0,10),ylim=(0,3.4))
    ax.axis('off')
    box(ax,.15,2.35,2.7,.75,'I/Q histories\n21 signed 9-bit values')
    box(ax,3.55,2.35,2.7,.75,'Coefficient ROM\nAddress = 4 x tap + phase')
    box(ax,3.55,1.25,2.7,.75,'One shared MAC\n27-bit product, 36-bit sum')
    box(ax,7.15,1.25,2.7,.75,'Phase sign and gain\n+I, -Q, -I, +Q')
    arrow(ax,(1.5,2.29),(3.48,1.63))
    arrow(ax,(4.9,2.29),(4.9,2.07))
    arrow(ax,(6.32,1.63),(7.08,1.63))
    box(ax,7.75,.15,2.1,.75,'Round and saturate\nSigned 12-bit output','#ece8f4')
    box(ax,4.35,.15,2.45,.75,'HOLD until accepted\nStable data and sidebands','#f5ebd6')
    box(ax,.4,.15,2.75,.75,'Finite file source\n4N valid samples, then padding','#e8edf5')
    arrow(ax,(8.5,1.19),(8.8,.97))
    arrow(ax,(7.68,.52),(6.87,.52))
    arrow(ax,(4.28,.52),(3.22,.52))
    for ext in ('png','pdf'): fig.savefig(FIG/f'adapter_schedule.{ext}',dpi=200)
    plt.close(fig)


def waveform(vcd):
    names=['clk','sample_valid_o','sample_ready_i','sample_data_o','output_count_o','state_q','phase_q','sample_last_o','sample_clipped_o']
    mapping={}
    values={name:0 for name in names}
    snapshots=[]
    t=0
    in_header=True
    scale=None
    with vcd.open() as file:
        for raw in file:
            line=raw.strip()
            if in_header:
                if line=='1ps': scale=1
                if line.startswith('$var'):
                    words=line.split()
                    if words[4] in names and len(words)>5:
                        if words[2]=='1' and words[5].startswith('['):
                            continue
                        mapping[words[3]]=words[4]
                if line.startswith('$enddefinitions'): in_header=False
                continue
            if line.startswith('$dumpoff'):
                break
            if line.startswith('#'):
                snapshots.append((t,dict(values)))
                t=int(line[1:])
            elif line.startswith(('b','B')):
                bits,code=line[1:].split()
                if code in mapping and all(c in '01' for c in bits):
                    value=int(bits,2)
                    if mapping[code]=='sample_data_o' and value>=2048: value-=4096
                    values[mapping[code]]=value
            elif line and line[0] in '01' and line[1:] in mapping:
                values[mapping[line[1:]]]=int(line[0])
    snapshots.append((t,dict(values)))
    if scale!=1 or set(names)-set(mapping.values()):
        raise ValueError('Unexpected VCD signal layout or timescale')
    intervals=[]
    start=None
    for (t,values),(tn,_) in zip(snapshots,snapshots[1:]):
        stalled=values['sample_valid_o']==1 and values['sample_ready_i']==0
        if stalled and start is None: start=t
        if not stalled and start is not None:
            intervals.append((start,t))
            start=None
    positive=[pair for pair in intervals if pair[1]-pair[0]>=20000]
    if not positive: raise ValueError('No visible stalled RTL output in VCD')
    begin,end=max(positive,key=lambda pair:pair[1]-pair[0])
    lo=max(0,begin-250000)
    hi=end+650000
    rows=[(t,v) for t,v in snapshots if lo<=t<=hi]
    # Preserve a pre-window value for each step function.
    prior=[(t,v) for t,v in snapshots if t<lo]
    if prior: rows.insert(0,(lo,prior[-1][1]))
    held=[v for t,v in rows if begin<=t<end]
    for key in ['sample_data_o','output_count_o','sample_last_o','sample_clipped_o']:
        if len({v[key] for v in held})!=1: raise ValueError('Stalled-output instability in '+key)
    times=np.array([t for t,_ in rows])/1e6
    plot_names=['state_q','sample_valid_o','sample_ready_i','sample_data_o','output_count_o','sample_last_o']
    labels=['FSM state','Output valid','Consumer ready','Signed data','Accepted count','Last sample']
    fig,axs=plt.subplots(6,1,figsize=(10,4.9),sharex=True,layout='constrained',gridspec_kw={'height_ratios':[1,1,1,1.4,1.2,1]})
    for ax,key,label in zip(axs,plot_names,labels):
        ys=[v[key] for _,v in rows]
        ax.step(times,ys,where='post',color='#176a8c',linewidth=1.4)
        ax.set_ylabel(label,rotation=0,ha='right',va='center',fontsize=9,labelpad=13)
        ax.axvspan(begin/1e6,end/1e6,color='#e8bd58',alpha=.23)
        ax.grid(axis='x',alpha=.18)
        if key=='state_q': ax.set_yticks([1,2,3,4],['LOAD','MAC','MAKE','HOLD'])
        elif key not in ('sample_data_o','output_count_o'): ax.set_yticks([0,1])
        ax.tick_params(labelsize=8)
    axs[0].set_title('Actual RTL simulation: output held during consumer backpressure',loc='left',pad=12,fontsize=12)
    axs[-1].set_xlabel('Simulation time (microseconds)')
    axs[-1].set_xlim(lo/1e6,hi/1e6)
    for ext in ('png','pdf'): fig.savefig(FIG/f'rtl_backpressure.{ext}',dpi=220)
    plt.close(fig)
    trace=HERE/'evidence/waveform_trace.csv'
    with trace.open('w',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['time_ps']+names)
        writer.writerows([[t]+[v[n] for n in names] for t,v in rows])
    (HERE/'evidence/waveform_source.json').write_text(json.dumps({'artifact_kind':'extracted_actual_rtl_simulation_trace','source_vcd_name':vcd.name,'source_vcd_sha256':sha(vcd),'timescale':'1 ps','window_ps':[lo,hi],'stalled_interval_ps':[begin,end],'stable_fields_checked':['sample_data_o','output_count_o','sample_last_o','sample_clipped_o'],'trace':'waveform_trace.csv','trace_sha256':sha(trace),'hardware_measurement':False},indent=2)+'\n')
    print(json.dumps({'waveform':'figures/rtl_backpressure.png','stalled_interval_ps':[begin,end],'source_sha256':sha(vcd)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--vcd',type=Path)
    args=parser.parse_args()
    historical()
    diagrams()
    if args.vcd: waveform(args.vcd.resolve())
