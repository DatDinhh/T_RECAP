#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reproduce architecture figures from RTL contracts and recorded simulation/fit evidence."""
from __future__ import annotations
import argparse, csv, hashlib, html, json, shutil
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, FancyArrowPatch

M,G,T,GRAY="#8C1D40","#FFC627","#246B77","#777A80"
PM,PG,PT="#F4E5EA","#FFF4CD","#E4F0F2"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":13,"axes.labelsize":13,
 "xtick.labelsize":11,"ytick.labelsize":11,"axes.spines.top":False,"axes.spines.right":False,
 "axes.edgecolor":"#AAA4A7","text.color":"#252525","axes.labelcolor":"#252525",
 "figure.facecolor":"white","axes.facecolor":"white","grid.color":"#E4E1E3",
 "grid.linewidth":.7,"lines.linewidth":1.8,"legend.frameon":False,"svg.fonttype":"none",
 "pdf.fonttype":42,"savefig.facecolor":"white","axes.formatter.useoffset":False})
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def js(p):return json.loads(Path(p).read_text(encoding="utf-8-sig"))
def rows(p):
 with Path(p).open(newline="",encoding="utf-8-sig") as f:return list(csv.DictReader(f))
def nums(p):return [{k:float(v) if k=="time_ns" else int(v) for k,v in r.items()} for r in rows(p)]
def memh(p):
 a=np.array([int(v,16) for v in Path(p).read_text().split()],dtype=np.int64)
 return np.where(a>=2048,a-4096,a)
def layout(title,sub,n=1,foot="RTL structure and documented contracts. Board energy measurements remain pending."):
 fig,aa=plt.subplots(n,1,figsize=(16,9),squeeze=False)
 fig.subplots_adjust(left=.10,right=.955,bottom=.12,top=.79,hspace=.48)
 fig.text(.055,.945,"T-RECAP  /  ARCHITECTURE",color=M,fontsize=12,weight="bold")
 fig.text(.965,.945,"Team #2",ha="right",color=M,fontsize=12)
 fig.text(.055,.882,title,color=M,fontsize=25,weight="bold")
 fig.text(.055,.837,sub,color=GRAY,fontsize=12.3)
 fig.text(.055,.035,foot,color=GRAY,fontsize=10.3)
 for a in aa[:,0]:a.grid(True);a.set_axisbelow(True)
 return fig,aa[:,0]
def canvas(title,sub):
 fig,aa=layout(title,sub);a=aa[0];a.set_position([.055,.115,.91,.665])
 a.set_xlim(0,100);a.set_ylim(0,100);a.axis("off");return fig,a
def box(a,x,y,w,h,title,body="",tone=PM,ts=14,bs=11.5):
 a.add_patch(Rectangle((x,y),w,h,facecolor=tone,edgecolor=M if tone==PM else T if tone==PT else "#B78E1C",lw=1.4))
 a.text(x+w/2,y+h-5,title,ha="center",va="top",weight="bold",fontsize=ts,color=M)
 if body:a.text(x+w/2,y+h/2-2,body,ha="center",va="center",fontsize=bs,linespacing=1.45)
def arrow(a,pts,color=M,dash=False):
 for p,q in zip(pts[:-2],pts[1:-1]):a.plot([p[0],q[0]],[p[1],q[1]],color=color,lw=1.6,ls="--" if dash else "-")
 a.add_patch(FancyArrowPatch(pts[-2],pts[-1],arrowstyle="-|>",mutation_scale=13,color=color,lw=1.6,linestyle="--" if dash else "-"))
def note(a,x,y,s,**kw):a.text(x,y,s,va="top",**kw)

def build(repo,run,out):
 out.mkdir(parents=True,exist_ok=True);(out/"figures").mkdir(exist_ok=True);(out/"data").mkdir(exist_ok=True)
 records=[];pub=js(repo/"docs/results/de1soc_lite_bram_20260915.json")
 fit="runs/quartus/windows/20260915-lite-bram-01/implementation-reports/trecap_de1soc.fit.rpt"
 sta="runs/quartus/windows/20260915-lite-bram-01/fitted-timing/fitted_timing.tsv"
 for p in [fit,sta]:assert sha(repo/p)==pub["evidence"][p]["sha256"],p
 pdf=PdfPages(out/"T_RECAP_Architecture_Figures.pdf",metadata={"Title":"T-RECAP Architecture Figures","Author":"Team #2"})
 def save(fig,key,title,caption,sources,kind):
  fig.text(.965,.035,f"{len(records)+1:02} / 10",ha="right",fontsize=10,color=GRAY)
  fig.savefig(out/"figures"/(key+".png"),dpi=180);fig.savefig(out/"figures"/(key+".svg"))
  pdf.savefig(fig);plt.close(fig);records.append(dict(id=key,title=title,caption=caption,sources=sources,evidence_kind=kind))
 # 1. Data ownership.
 fig,a=canvas("System data flow and ownership","One mathematical core in FPGA fabric, with separate observation and control paths")
 box(a,0,57,23,32,"Input sources","BRAM replay\nLINE-IN / audio adapter\nADC / diagnostic source",PG)
 box(a,31,57,27,32,"FPGA mathematical core","STFT, threshold mask, WOLA\nFrame-owned configuration\nCore-owned error metrics")
 box(a,68,57,30,32,"Observation and transport","Valid-only taps\nPacketizers and payload FIFO\nDDR record writer",PT)
 arrow(a,[(23,73),(31,73)]);arrow(a,[(58,73),(68,73)],T);note(a,60,83,"taps",color=T,fontsize=11)
 box(a,68,13,30,24,"HPS Linux","DDR consumer and UDP sender",PG)
 box(a,31,13,27,24,"PC dashboard","Waveforms, spectra and control",PT)
 box(a,0,13,23,24,"FPGA CSR owners","Shadow / commit configuration")
 arrow(a,[(83,57),(83,37)],T);note(a,85,48,"DDR ring",color=T,fontsize=11)
 arrow(a,[(68,25),(58,25)],T);note(a,59,32,"UDP",color=T,fontsize=11)
 arrow(a,[(44,13),(44,4),(83,4),(83,13)],M,True);note(a,55,9,"PC commands",color=M,fontsize=10)
 arrow(a,[(68,19),(63,19),(63,46),(11.5,46),(11.5,37)],M,True)
 note(a,35,44,"HPS bridge writes CSRs",color=M,fontsize=11)
 arrow(a,[(23,31),(27,31),(27,53),(44,53),(44,57)],M,True)
 note(a,0,99,"FPGA core and fabric control: 50 MHz",color=M,fontsize=13,weight="bold")
 note(a,0,-1,"Telemetry congestion may drop records. It cannot backpressure the mathematical core.",color=GRAY,fontsize=11)
 save(fig,"01_system_ownership","System ownership",
 "The physical board instantiates one core inside source/core integration. The HPS forwards committed telemetry records and writes controls. Observers have no ready return path into the DSP core. End-to-end HPS/DDR/dashboard board acceptance remains open.",
 ["rtl/platform/de1soc/de1_soc_trecap_top.sv","docs/architecture/architecture_implementation.md"],"RTL structure")
 # 2. Core datapath and widths.
 fig,a=canvas("Fixed-point DSP datapath","FFT length 256, hop 128, reference alignment D = 384 samples")
 xs=[0,26,52,78]
 tops=[("Frame history","512 x 76-bit ring\n256-sample extraction"),("Analysis window","Unsigned 16-bit Qw\nSigned 27-bit result"),
 ("FFT256","28-bit real / imaginary\n8 radix-2 stages"),("Canonical spectrum","28-bit real / imaginary\nHermitian pair handling")]
 bots=[("Synthesis WOLA","36-bit window result\n37-bit overlap accumulator\n12-bit output"),("IFFT256","36-bit real / imaginary\n8 radix-2 stages"),
 ("Spectrum builder","28-bit masked spectrum\nOrdered complete frame"),("Magnitude and mask","56-bit magnitude squared\nEligible bins: mag2 < THR2\nDC protected")]
 for x,(t,b) in zip(xs,tops):box(a,x,61,21,28,t,b,ts=12.5)
 for x,(t,b) in zip(xs,bots):box(a,x,16,21,28,t,b,PG,ts=12.5,bs=10.8)
 for i in range(3):arrow(a,[(xs[i]+21,75),(xs[i+1],75)])
 arrow(a,[(88.5,61),(88.5,44)])
 for i in range(3,0,-1):arrow(a,[(xs[i],30),(xs[i-1]+21,30)])
 note(a,0,99,"Signed 12-bit input samples",color=M,fontsize=13)
 note(a,1,9,"Delayed input history: 1024 x 76 bits     e[n] = x[n-384] - y[n]     Full-stream error aggregates",fontsize=12,color=T)
 note(a,1,53,"4-entry {frame_idx, THR2} queue keeps each frame's threshold consistent",fontsize=11,color=GRAY)
 save(fig,"02_fixed_point_datapath","Fixed-point datapath",
 "Separate iterative FFT and IFFT engines use the frozen coefficient tables. The core captures THR2 at frame admission. WOLA uses the real IFFT component. Delayed-input history supports error calculation. The offline C++ reference model is not a physical FPGA block.",
 ["rtl/core/trecap_core_top.sv","rtl/include/generated/trecap_core_pkg.sv","spec/generated/width_config.json"],"RTL structure")
 # 3. Seven scheduled edges.
 fig,aa=layout("Registered butterfly schedule","One butterfly uses seven rising edges. Each transform executes all 1024 butterflies per frame.",
 foot="Source-derived local schedule. Assumes a legal frame, continuous input and ready output.")
 a=aa[0];a.set_xlim(.5,7.5);a.set_ylim(0,4);a.set_yticks([]);a.set_xticks(range(1,8));a.set_xlabel("Scheduled rising edge")
 labels=["RAM / ROM\nread","Four signed\nproducts","Complex\nsum / difference","Shift-15\nround + saturate","Butterfly\nadd / subtract","Final\nround + saturate","Two-address\nwriteback"]
 for i,l in enumerate(labels,1):a.barh(3.35,.82,left=i-.41,height=.7,color=PM,edgecolor=M);a.text(i,3.35,l,ha="center",va="center",fontsize=11)
 for y,text,col,size in [(2.62,"FFT: 28-bit complex data, 17-bit twiddles, divide by two at each stage",M,14),
  (2.20,"IFFT: 36-bit complex data, 17-bit twiddles, no per-stage divide",T,14),(1.58,"Transform frame service",M,15),
  (1.12,"256 load clocks + 7168 compute clocks + 512 output clocks = 7936 clocks",M,15),
  (.56,"One complex output every two clocks. Input gaps and output stalls extend service.",GRAY,13)]:a.text(.7,y,text,color=col,fontsize=size)
 save(fig,"03_butterfly_schedule","Registered butterfly schedule",
 "The registered transaction separates multiplication, complex sum, quantization, addition and writeback. Counts include first and last accepted edges. Local transform service is 7936 clocks only under the stated conditions. It is not an end-to-end latency measurement.",
 ["docs/architecture/transform_microarchitecture.md","rtl/fft/trecap_fft_stage.sv"],"RTL schedule")
 # 4. Selected memory geometries.
 mem=[("Delayed-input history","1024 x 76",77824),("Input frame history","512 x 76",38912),("FFT working frame","256 x 56",14336),
 ("Canonicalizer frame","256 x 56",14336),("IFFT working frame","256 x 72",18432),("WOLA accumulator","384 x 37",14208),
 ("WOLA synthesis frame","256 x 36",9216),("Board replay ROM","4096 x 12",49152),("Telemetry payload","2700 x 32",86400),("DDR builder payload","292 x 32",9344)]
 fig,aa=layout("Selected storage in the implemented architecture","Logical array capacities from RTL. Coefficient ROMs, audio FIFOs and control state are omitted.",
 foot="Logical capacities do not predict fitted M10K packing. The complete fitted board uses 55 RAM blocks.")
 a=aa[0];a.set_position([.22,.145,.65,.635]);y=np.arange(len(mem))
 a.barh(y,[r[2]/1024 for r in mem],color=[M]*7+[T]*3,height=.62);a.set_yticks(y,[r[0] for r in mem]);a.invert_yaxis();a.set_xlim(0,115);a.set_xlabel("Logical storage (Kibit, 1024 bits)")
 for i,(_,geom,bits) in enumerate(mem):a.text(bits/1024+1.4,i,f"{geom} = {bits:,} bits",va="center",fontsize=10.5)
 a.grid(axis="y",visible=False)
 save(fig,"04_storage_geometry","Storage geometry",
 "Large stores use synchronous embedded-memory schedules. Both history stores include sample indices. Selected logical capacities do not include every memory or register and are distinct from fitted device resource totals.",
 ["docs/architecture/storage_schedule.md","docs/architecture/transform_microarchitecture.md"],"RTL structure")
 # 5. Actual frame activity includes compute-state runs as well as handshakes.
 stat=run/"multitone/static/capture";stall=run/"multitone/stalled/capture"
 chosen=[r for r in rows(stat/"frame_timing.csv") if int(r["frame_idx"])==0]
 t0=min(int(r["start_cycle"]) for r in chosen)
 fig,aa=layout("Observed first-frame pipeline activity","Fresh ModelSim core simulation. Interface spans and transform compute phases come from recorded RTL signals.",
 foot="Unpaced replay simulation. Interface spans include gaps. Compute spans identify actual engine state intervals.")
 a=aa[0];a.set_position([.19,.15,.72,.625])
 for i,r in enumerate(chosen):
  start=int(r["start_cycle"])-t0;end=int(r["end_cycle"])-t0
  a.barh(i,end-start+1,left=start,height=.62,color=M if "compute" in r["stage"] else T)
  suffix=f"{end-start+1} clocks" if "compute" in r["stage"] else f"{r['accepted_beats']} beats"
  a.text(end+150,i,f"{start:,}..{end:,} ({suffix})",va="center",fontsize=10.5)
 a.set_yticks(range(len(chosen)),[r["stage"].replace("_"," ") for r in chosen]);a.invert_yaxis()
 a.set_xlim(0,max(int(r["end_cycle"])-t0 for r in chosen)*1.37);a.set_xlabel(f"Simulation clock cycles relative to first window transfer at cycle {t0}");a.grid(axis="y",visible=False)
 save(fig,"05_observed_frame_timing","Observed frame timing",
 "Actual handshakes bound the first frame's interface spans. Engine-state traces identify 7168 compute clocks for each transform. Interface spans include gaps. The burst-driven testbench differs from periodic board sampling, so this is not board latency.",
 ["runs/architecture_presentation_20260922/multitone/static/capture/frame_timing.csv"],"RTL simulation")
 # 6. Select a real held nonzero sample and retain surrounding cycles.
 trace=nums(stall/"cycle_trace.csv")
 starts=[i for i,r in enumerate(trace) if r["y_valid"]==1 and r["y_ready"]==0 and r["rst_n"]==1 and r["clear"]==0]
 assert starts
 idx=next((i for i in starts if trace[i]["y_idx"]==600),next((i for i in starts if trace[i]["y_data"]!=0),starts[0]));clip=trace[max(0,idx-5):min(len(trace),idx+23)]
 cy=np.array([r["cycle"] for r in clip])
 fig,aa=layout("Output handshake under backpressure","Actual signals from the stalled RTL run. Transfer occurs only when valid and ready are both high.",3,
 foot="RTL simulation, values sampled at rising edges before register updates. Gold spans show valid held while ready is low.")
 for key,col in [("y_valid",M),("y_ready",T)]:aa[0].step(cy,[r[key]+(1.4 if key=="y_valid" else 0) for r in clip],where="post",color=col,label=key,lw=2)
 aa[0].set_yticks([0,1,1.4,2.4],["0","1","0","1"]);aa[0].set_ylabel("ready / valid");aa[0].set_ylim(-.15,3.3);aa[0].legend(loc="upper right",ncols=2,fontsize=11)
 aa[1].step(cy,[r["y_idx"] for r in clip],where="post",color=M);aa[1].set_ylabel("Output index")
 aa[2].step(cy,[r["y_data"] for r in clip],where="post",color=M);aa[2].set_ylabel("Output (LSB)");aa[2].set_xlabel("Simulation clock cycle")
 for r in clip:
  if r["y_valid"] and not r["y_ready"]:
   for a in aa:a.axvspan(r["cycle"],r["cycle"]+1,color=G,alpha=.27)
  if r["y_valid"] and r["y_ready"]:
   for a in aa:a.axvline(r["cycle"],color=T,ls=":",lw=.9)
 for a in aa:a.set_xlim(cy[0],cy[-1]+1)
 aa[0].text(.02,.86,"Dotted lines mark accepted transfers",transform=aa[0].transAxes,fontsize=11,color=GRAY)
 with (out/"data/handshake_excerpt.csv").open("w",newline="") as f:
  wr=csv.DictWriter(f,fieldnames=list(clip[0]));wr.writeheader();wr.writerows(clip)
 save(fig,"06_output_handshake","Output handshake",
 "Gold marks valid=1 and ready=0. Output index and data remain held until acceptance. The testbench injects stalls at the reusable core output. Physical board telemetry taps cannot drive core ready.",
 ["runs/architecture_presentation_20260922/multitone/stalled/capture/cycle_trace.csv"],"RTL simulation")
 # 7. Numerical comparison using all emitted samples.
 ystat=nums(stat/"y_accepts.csv");ystall=nums(stall/"y_accepts.csv")
 ref=memh(repo/"artifacts/reference_outputs/near_threshold_multitone_Ns1024_thr64/y_out.memh")
 yi=np.array([r["sample_idx"] for r in ystat]);yv=np.array([r["y_out"] for r in ystat])
 ys=np.array([r["y_out"] for r in ystall]);si=np.array([r["sample_idx"] for r in ystall])
 assert np.array_equal(yi,np.arange(len(ref))) and np.array_equal(si,yi)
 assert np.array_equal(yv,ref) and np.array_equal(ys,ref)
 fig,aa=layout("RTL and reference output waveforms","Multitone input, THR2 = 4096, 1536 output samples. Static and stalled runs preserve the same output codes.",3,
 foot="Finite core simulation on one selected vector. These waveforms are not board captures or a universal correctness proof.")
 aa[0].plot(yi,ref,color=G,lw=3,label="Reference output");aa[0].plot(yi,yv,color=M,lw=1.1,ls="--",label="RTL output")
 aa[0].set_ylabel("Output (LSB)");aa[0].set_ylim(-750,1100);aa[0].legend(loc="upper right",ncols=2,fontsize=11)
 aa[1].plot(yi,yv-ref,color=M);aa[1].set_ylim(-1,1);aa[1].set_ylabel("RTL - ref (LSB)")
 aa[1].text(.02,.78,"0 mismatches in both runs, including startup and the full tail",transform=aa[1].transAxes,color=M,fontsize=12)
 aa[2].plot(yi,np.array([r["cycle"] for r in ystat])-ystat[0]["cycle"],color=M,label="Static")
 aa[2].plot(si,np.array([r["cycle"] for r in ystall])-ystall[0]["cycle"],color=T,ls="--",label="Stalled")
 aa[2].set_ylabel("Cycles since\nfirst acceptance");aa[2].set_xlabel("Output sample index n");aa[2].legend(loc="upper left",fontsize=11,ncols=2)
 for a in aa:a.set_xlim(0,len(ref)-1)
 save(fig,"07_rtl_reference_waveforms","RTL and reference waveforms",
 "Every output matches the qualified reference for this multitone case in both static and stalled simulations. The lower graph shows scheduling separately from numerical sample order. It is not a CPU/FPGA speed comparison.",
 ["runs/architecture_presentation_20260922/multitone/static/capture/y_accepts.csv","runs/architecture_presentation_20260922/multitone/stalled/capture/y_accepts.csv","artifacts/reference_outputs/near_threshold_multitone_Ns1024_thr64/y_out.memh"],"RTL simulation")
 # 8. Analytical schedule allocation.
 fig,aa=layout("Frame-work allocation and sample-rate deadlines","50 MHz fabric, 128 samples per hop. The 18000-clock allocation covers the documented connected schedule.",2,
 foot="Analytical budget with healthy periodic input and ready output. Finite tail flushing is a separate cost.")
 for a,total,label in zip(aa,[64000,50e6*128/48000],["100 ksample/s","48 ksample/s"]):
  a.barh(0,18000,height=.48,color=M,label="Frame-work allocation")
  a.barh(0,total-18000,left=18000,height=.48,color=PG,edgecolor="#C9AC50",label="Remaining hop interval")
  a.set_yticks([0],[label]);a.set_ylim(-.6,.9);a.set_xlim(0,140000)
  a.text(9000,0,"18,000",ha="center",va="center",color="white",weight="bold",fontsize=12)
  a.text(total/2+9000,0,f"{total-18000:,.0f} clocks remaining",ha="center",va="center",fontsize=12)
  a.text(.01,.80,f"Allocation: {18000/total*100:.3f}% of one hop     Hop duration: {total/50e3:.4f} ms",transform=a.transAxes,fontsize=12,color=M)
  a.grid(axis="y",visible=False)
 aa[1].set_xlabel("Fabric clock cycles per hop")
 save(fig,"08_frame_deadline_budget","Frame deadline budget",
 "The source-derived connected bound including metrics allowance is 17673 clocks, rounded to an 18000-clock allocation. At 50 MHz this is 360 microseconds. The recurrent budget excludes finite tail, analog delay and transport. Unbounded external stalls invalidate a finite service guarantee.",
 ["docs/architecture/architecture_design.md","docs/architecture/transform_microarchitecture.md"],"Analytical budget")
 # 9. Archived fitted resources.
 res=pub["resources"];keys=["alms","dsp_blocks","ram_blocks","block_memory_bits"];names=["ALMs","DSP blocks","RAM blocks","Block-memory bits"]
 vals=[100*res[k]["used"]/res[k]["available"] for k in keys]
 fig,aa=layout("Fitted FPGA resource utilization","Quartus Prime Lite 20.1.1, Cyclone V 5CSEMA5F31C6. Archived BRAM build dated 15 September 2026.",
 foot="Actual full-board fit for the archived profile. Resource counts do not measure electrical energy or acceleration.")
 a=aa[0];a.set_position([.20,.20,.69,.55]);y=np.arange(4)
 a.barh(y,[100]*4,color="#F0ECEE",height=.55);a.barh(y,vals,color=[M,T,M,T],height=.55)
 a.set_yticks(y,names);a.invert_yaxis();a.set_xlim(0,100);a.set_xlabel("Device capacity used (%)");a.grid(axis="y",visible=False)
 for i,(k,v) in enumerate(zip(keys,vals)):a.text(v+1.5,i,f"{res[k]['used']:,} / {res[k]['available']:,} ({v:.2f}%)",va="center",fontsize=12.5)
 fig.text(.20,.095,"29,452 registers     209 fitted pins checked     Whole-board BRAM profile",fontsize=13,color=M)
 save(fig,"09_fitted_resources","Fitted resources",
 "The archived Lite build uses 21220 ALMs, 36 DSP blocks and 55 RAM blocks. Percentages use exact reported used/available counts. These are whole-board totals, including interfaces and telemetry, rather than isolated-core costs.",
 ["docs/results/de1soc_lite_bram_20260915.json",fit],"Quartus fit")
 # 10. Fabric-only clock-to-clock timing queries.
 corners=pub["timing"]["operating_conditions"];names=["Slow 85 C","Slow 0 C","Fast 0 C","Fast 85 C"]
 fig,aa=layout("Fitted timing across four operating corners","CLOCK_50 to CLOCK_50 at a 20 ns clock period. All four corners use the 1100 mV model.",2,
 foot="Archived static timing analysis, 15 September 2026. Global timing includes additional clocks and has different minima.")
 for a,key,label,col in [(aa[0],"clock_50_setup_ns","Setup slack (ns)",M),(aa[1],"clock_50_hold_ns","Hold slack (ns)",T)]:
  vals=[r[key] for r in corners];bars=a.bar(names,vals,color=col,width=.50)
  a.axhline(0,color=GRAY,lw=1);a.set_ylabel(label);a.set_ylim(0,max(vals)*1.35);a.grid(axis="x",visible=False)
  for b,v in zip(bars,vals):a.text(b.get_x()+b.get_width()/2,v+max(vals)*.055,f"+{v:.3f}",ha="center",fontsize=13,weight="bold",color=col)
 aa[1].text(.98,.90,"Smallest modeled hold margin: 0.002 ns",transform=aa[1].transAxes,ha="right",fontsize=12,color=M)
 save(fig,"10_fitted_timing","Fitted timing",
 "All four explicit fabric-clock timing queries pass. Minimum fabric setup is +2.333 ns and minimum hold is +0.002 ns. That narrow positive hold margin applies to the analyzed model. Global minimum setup is +1.727 ns and differs from the fabric-only number.",
 ["docs/results/de1soc_lite_bram_20260915.json",sta],"Quartus static timing")
 pdf.close()
 # Portable data snapshots.
 refs=sorted(set(p for r in records for p in r["sources"]))
 sources={p:{"sha256":sha(repo/p),"bytes":(repo/p).stat().st_size} for p in refs if (repo/p).is_file()}
 shutil.copy2(repo/"docs/results/de1soc_lite_bram_20260915.json",out/"data/fitted_build_result.json")
 for variant in ["static","stalled"]:
  dest=out/"data"/variant;dest.mkdir(exist_ok=True)
  for name in ["frame_timing.csv","stage_events.csv","sample_commits.csv","y_accepts.csv","metrics_observed.json"]:
   src=run/f"multitone/{variant}/capture"/name
   if src.exists():shutil.copy2(src,dest/name)
  vcd=run/f"multitone/{variant}/architecture.vcd"
  if vcd.exists():shutil.copy2(vcd,dest/"architecture.vcd")
 for name in ["manifest.json","trace_schema.json","README.md"]:
  if (run/name).exists():shutil.copy2(run/name,out/"data"/("capture_"+name))
 shutil.copy2(repo/"artifacts/reference_outputs/near_threshold_multitone_Ns1024_thr64/y_out.memh",out/"data/reference_y_out.memh")
 shutil.copy2(Path(__file__),out/"plot_architecture_presentation.py")
 manifest={"schema":"trecap_architecture_presentation_v1","team":"Team #2","figures":records,"source_files":sources,
 "rtl_waveform":{"case":"near_threshold_multitone_Ns1024_thr64","THR2":4096,"outputs_per_run":len(ref),"static_mismatches":int(np.count_nonzero(yv-ref)),"stalled_mismatches":int(np.count_nonzero(ys-ref))},"matplotlib":matplotlib.__version__}
 (out/"provenance.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
 chapters=[]
 for r in records:
  title=html.escape(r["title"]);key=r["id"]
  chapters.append(f'<section><h2>{title}</h2><p class="kind">{r["evidence_kind"]}</p><img src="figures/{key}.svg" alt="{title}"><p>{html.escape(r["caption"])}</p><a href="figures/{key}.png">PNG</a> &nbsp; <a href="figures/{key}.svg">SVG</a></section>')
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T-RECAP Architecture Figures</title><style>body{margin:0;background:#f5f3f4;color:#252525;font:17px/1.6 system-ui,sans-serif}header{background:#8c1d40;color:white;padding:32px max(4vw,24px)}header strong{color:#ffc627}main{max-width:1250px;margin:auto;padding:24px}section{background:white;margin:24px 0;padding:25px}h1{margin:0}h2,a{color:#8c1d40}img{width:100%;display:block}.kind{color:#777a80}nav{display:flex;gap:24px;flex-wrap:wrap}</style><header><strong>TEAM #2</strong><h1>T-RECAP Architecture</h1><p>RTL structure, simulation waveforms and fitted implementation evidence</p></header><main><nav><a href="T_RECAP_Architecture_Figures.pdf">Open all ten figures</a><a href="README.md">Figure explanations</a><a href="provenance.json">Sources and provenance</a></nav>'''+''.join(chapters)+"</main></html>"
 (out/"index.html").write_text(page,encoding="utf-8")
 md=["# T-RECAP architecture presentation figures","","Team #2","","## Presentation order",
 "For a short TA discussion, use 01 (system ownership), 02 (datapath), 06 (handshake) and 09 (fitted resources). Use 07 for numerical comparison and 10 for timing.","","## Evidence boundaries",
 "- Structure diagrams follow checked-in RTL and architecture contracts.",
 "- Butterfly and deadline charts show source-derived schedules or analytical budgets.",
 "- Waveforms come from fresh ModelSim finite-core simulation.",
 "- Resource and timing charts use the archived 15 September 2026 Quartus Lite build.",
 "- The multitone simulation differs from the deployed default 4096-zero-sample, STATUS-only board profile.",
 "- End-to-end HPS/DDR/dashboard operation, CPU/FPGA speedup and electrical energy remain unmeasured.",
 "","## Files","- figures/: 2880 x 1620 PNGs and editable SVGs.","- T_RECAP_Architecture_Figures.pdf: ten presentation pages.",
 "- data/: original VCD waveforms, selected CSV events, reference output and fitted-result snapshot.","- provenance.json: figure-to-source mapping and SHA-256 identities.",
 "- plot_architecture_presentation.py: plot builder.","","## Figure notes"]
 for r in records:md.extend(["",f"### {r['id']}. {r['title']}",r["caption"],"","Sources: "+", ".join(r["sources"])])
 md.extend(["","## Reproduce","From the repository root with NumPy and Matplotlib installed:","","    python scripts/analysis/plot_architecture_presentation.py --repo .","",
 "Recorded captures must exist in runs/architecture_presentation_20260922. The builder validates archived fitter/timing hashes and full output sequences against the qualified reference. It does not modify RTL or rebuild Quartus.",
 "","## Signal and timing conventions","- Signed 12-bit sample codes use LSB units.",
 "- Numerical comparison includes all 1536 output samples.",
 "- Handshake traces sample signals at rising edges before register updates.",
 "- A transfer requires valid and ready together.",
 "- Interface event spans include intervening gaps.",
 "- D=384 samples is reference alignment, separate from service cycles and host/network delay."])
 (out/"README.md").write_text("\n".join(md)+"\n",encoding="utf-8")
 print(json.dumps({"output":str(out),"figures":len(records),"rtl_samples_compared":len(ref)*2,"mismatches":0},indent=2))
if __name__=="__main__":
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--repo",type=Path,default=Path(__file__).resolve().parents[2]);ap.add_argument("--run-dir",type=Path);ap.add_argument("--out",type=Path)
 ar=ap.parse_args();repo=ar.repo.resolve()
 build(repo,(ar.run_dir or repo/"runs/architecture_presentation_20260922").resolve(),(ar.out or repo/"docs/presentation/architecture_20260922").resolve())

