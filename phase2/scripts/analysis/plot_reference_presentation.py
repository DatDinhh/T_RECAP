#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reproduce T-RECAP presentation plots from real C++ reference-model outputs."""
from __future__ import annotations
import argparse, csv, hashlib, html, json, math, platform, shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import ListedColormap, LinearSegmentedColormap

THRESHOLDS=[0,4096,10**6,10**8,10**9,10**10,10**11,10**12,10**13,10**14,2**56-1]
MULTI="near_threshold_multitone_Ns1024_thr64"
M,G,T,GRAY="#8C1D40","#FFC627","#246B77","#777A80"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":13,"axes.titlesize":16,
 "axes.labelsize":13,"xtick.labelsize":11,"ytick.labelsize":11,
 "axes.spines.top":False,"axes.spines.right":False,"axes.edgecolor":"#AAA4A7",
 "axes.labelcolor":"#252525","text.color":"#252525","axes.titlecolor":M,
 "figure.facecolor":"white","axes.facecolor":"white","grid.color":"#E4E1E3",
 "grid.linewidth":.7,"lines.linewidth":1.8,"legend.frameon":False,
 "svg.fonttype":"none","pdf.fonttype":42,"savefig.facecolor":"white",
 "axes.formatter.useoffset":False})
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def js(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def memh(p,width=12):
 a=np.array([int(v,16) for v in Path(p).read_text().split()],dtype=np.int64)
 assert np.all((a>=0)&(a<2**width)),p
 return np.where(a>=2**(width-1),a-2**width,a)
def csvrows(p):
 with Path(p).open(newline="") as f:return [{k:int(v) for k,v in r.items()} for r in csv.DictReader(f)]
def specs():
 return [(MULTI,t,f"multitone_thr2_{t}") for t in THRESHOLDS]+[
 ("impulse_Ns1024_thr0",0,"impulse_thr2_0"),("zero_Ns4096_thr0",0,"zero_thr2_0")]
def load(repo,root,vector,thr,key):
 d=root/key; cfg=js(d/"config.json")["configuration"]
 assert int(cfg["THR2"])==thr
 x=memh(repo/"artifacts/test_vectors"/vector/"x_in.memh"); y=memh(d/"y_out.memh")
 ns,ny,D,frames=map(int,(cfg["Ns"],cfg["Ny"],cfg["D"],cfg["frames"]))
 assert len(x)==ns and len(y)==ny and frames==(ns+254)//128 and ny==128*frames+384 and D==384
 ref=np.zeros(ny,dtype=np.int64);ref[D:D+ns]=x;err=ref-y
 met=js(d/"metrics.json");em=met["time_domain_errors"]
 assert int(em["error_sample_count"])==ny
 assert sum(abs(int(v)) for v in err)==int(em["sum_abs_err"])
 assert sum(int(v)**2 for v in err)==int(em["sum_sq_err"])
 assert max(abs(int(v)) for v in err)==int(em["max_abs_err"])
 fr=csvrows(d/"frame_stats.csv");bins=csvrows(d/"bin_stats.csv")
 assert len(fr)==frames and len(bins)==frames*129
 su,sp=met["suppression_totals"],met["spectral_totals"];den=int(sp["eligible_total_mag2"])
 summary={"case":key,"vector":vector,"THR2":thr,"Ns":ns,"Ny":ny,"D":D,"frames":frames,
 "eligible_suppression_percent":100*int(su["eligible_suppressed_bins"])/int(su["eligible_unique_bins"]),
 "eligible_spectral_mag2_retained_percent":100*int(sp["eligible_kept_mag2"])/den if den else None,
 "rmse_full_stream_lsb":math.sqrt(int(em["sum_sq_err"])/ny),"max_abs_error_lsb":int(em["max_abs_err"]),
 "sum_sq_error":int(em["sum_sq_err"]),"input_sha256":sha(repo/"artifacts/test_vectors"/vector/"x_in.memh"),
 "output_sha256":sha(d/"y_out.memh")}
 return dict(key=key,vector=vector,thr=thr,cfg=cfg,x=x,y=y,ref=ref,err=err,metrics=met,fr=fr,bins=bins,summary=summary)
def layout(title,sub,rows=1,ratios=None):
 fig,ax=plt.subplots(rows,1,figsize=(16,9),gridspec_kw={"height_ratios":ratios} if ratios else None,squeeze=False)
 ax=ax[:,0];fig.subplots_adjust(left=.095,right=.955,bottom=.115,top=.79,hspace=.47)
 fig.text(.055,.945,"T-RECAP  /  REFERENCE MODEL",color=M,fontsize=12,weight="bold")
 fig.text(.965,.945,"Team #2",ha="right",color=M,fontsize=12)
 fig.text(.055,.882,title,fontsize=25,weight="bold",color=M)
 fig.text(.055,.837,sub,fontsize=12.5,color=GRAY)
 fig.text(.055,.035,"Reference-model simulation. Sample codes are not volts. No electrical-energy measurement.",fontsize=11,color=GRAY)
 for a in ax:a.grid(True,alpha=.9);a.set_axisbelow(True)
 return fig,ax
def edges(ax,c):
 D,ns,ny=c["cfg"]["D"],c["cfg"]["Ns"],c["cfg"]["Ny"]
 ax.axvspan(0,D,color=GRAY,alpha=.10,zorder=0);ax.axvspan(D+ns,ny-1,color=GRAY,alpha=.10,zorder=0)
 ax.axvline(D,color=GRAY,lw=1,ls=":");ax.axvline(D+ns,color=GRAY,lw=1,ls=":")
def matrix(c,field):
 return np.array([r[field] for r in c["bins"]],dtype=float).reshape(c["cfg"]["frames"],129)
def figures(repo,out,cases):
 result=[];base=cases["multitone_thr2_4096"];medium=cases["multitone_thr2_100000000000"];strong=cases["multitone_thr2_10000000000000"]
 pdf=PdfPages(out/"T_RECAP_Reference_Model_Figures.pdf",metadata={"Title":"T-RECAP Reference Model Figures","Author":"Team #2","Subject":"Fixed-point simulation and threshold sweep"})
 def save(fig,key,title,caption):
  fig.text(.965,.035,f"{len(result)+1:02} / 07",ha="right",fontsize=10,color=GRAY)
  fig.canvas.draw();fig.savefig(out/"figures"/(key+".png"),dpi=180);fig.savefig(out/"figures"/(key+".svg"));pdf.savefig(fig)
  result.append(dict(id=key,title=title,caption=caption));plt.close(fig)
 # Waveform and delay: all emitted samples remain visible.
 fig,ax=layout("Reconstruction with a 384-sample delay","Imported multitone input, freshly rerun  |  THR2 = 4096  |  Ns = 1024, Ny = 1536",3,[1,1,.6])
 n=np.arange(len(base["y"]));raw=np.zeros(len(n));raw[:len(base["x"])]=base["x"]
 ax[0].plot(n,raw,color=GRAY,label="Input x[n], zero-extended");ax[0].set_ylabel("Input code (LSB)");ax[0].legend(loc="upper right",fontsize=11)
 ax[1].plot(n,base["ref"],color=G,lw=3,label="Delayed input x[n-384]")
 ax[1].plot(n,base["y"],color=M,lw=1.2,ls="--",label="Reference output y[n]");edges(ax[1],base)
 ax[1].set_ylabel("Output code (LSB)");ax[1].set_ylim(-750,1050);ax[1].legend(loc="upper right",ncols=2,fontsize=11)
 ax[2].plot(n,base["err"],color=M);ax[2].set_ylim(-1,1);ax[2].set_ylabel("Error (LSB)");ax[2].set_xlabel("Sample index n")
 ax[2].text(.02,.77,"x[n-384] - y[n] = 0 for all 1536 emitted samples in this test",transform=ax[2].transAxes,fontsize=12,color=M)
 for a in ax:a.set_xlim(0,len(n)-1)
 save(fig,"01_waveform_and_delay","Waveform and causal delay","The model reproduces this multitone vector exactly after aligning the input by 384 samples. The comparison includes startup and the complete tail. This is one test, not a universal zero-error claim.")
 # Exact model-exported spectrum; no substitute NumPy FFT.
 fig,ax=layout("What the spectral mask removes","Interior frame m = 4  |  THR2 = 10^11 in raw magnitude-squared units  |  DC remains protected",2,[2,1])
 rows=medium["bins"][4*129:5*129];k=np.arange(129)
 mag=np.array([r["mag2"] for r in rows],float);mask=np.array([r["mask"] for r in rows],bool)
 ax[0].plot(k,np.maximum(mag,1),color=GRAY,lw=1,alpha=.55)
 ax[0].scatter(k[~mask],np.maximum(mag[~mask],1),c=M,s=40,label="Retained canonical bins",zorder=3)
 ax[0].scatter(k[mask],np.maximum(mag[mask],1),c="#AA7E00",s=30,marker="x",label="Suppressed bins (set to zero)",zorder=3)
 ax[0].axhline(medium["thr"],color=T,ls="--",label="THR2");ax[0].set_yscale("log")
 ax[0].set_ylabel("Canonical magnitude squared (raw)");ax[0].legend(loc="upper right",ncols=3,fontsize=11)
 ax[1].bar(k,mask.astype(int),color=G,width=.9,edgecolor="#D4A319",linewidth=.25)
 ax[1].set_yticks([0,1],["Keep","Suppress"]);ax[1].set_ylim(-.08,1.23);ax[1].set_ylabel("Final mask");ax[1].set_xlabel("Unique FFT bin k (0 to 128)")
 ax[1].annotate("Protected DC",xy=(0,0),xytext=(10,.45),arrowprops={"arrowstyle":"->","color":M},color=M)
 for a in ax:a.set_xlim(-1,129)
 save(fig,"02_spectrum_and_mask","Spectrum and threshold decision","These are canonical pre-mask FFT bins from the C++ model, not an FFT of the entire output stream. An eligible bin is suppressed when magnitude squared is strictly less than THR2. The lower panel shows the actual final mask. Zero magnitudes use a display floor of 1 on the log plot.")
 # Aligned zoom plus full-stream errors, with actual data at two thresholds.
 fig,ax=layout("Higher thresholds change the reconstructed signal","Same input and coefficients  |  Upper plot aligns output by D = 384  |  Lower plot includes the full emitted stream",2)
 j=np.arange(256,384);D=384
 ax[0].plot(j,base["x"][j],color=GRAY,lw=2.3,label="Input (baseline output is identical)")
 ax[0].plot(j,medium["y"][j+D],color=M,label="THR2 = 10^11",ls="--")
 ax[0].plot(j,strong["y"][j+D],color="#B08100",label="THR2 = 10^13",ls="-.")
 ax[0].set_xlabel("Input sample index j, compared with y[j+384]");ax[0].set_ylabel("Sample code (LSB)");ax[0].set_ylim(-750,950);ax[0].legend(loc="upper right",fontsize=11,ncols=3)
 ax[1].plot(medium["err"],color=M,label=f"10^11: full-stream RMSE {medium['summary']['rmse_full_stream_lsb']:.2f} LSB")
 ax[1].plot(strong["err"],color="#B08100",alpha=.85,label=f"10^13: full-stream RMSE {strong['summary']['rmse_full_stream_lsb']:.2f} LSB")
 edges(ax[1],base);ax[1].set_xlabel("Output sample index n (including startup and tail)")
 ax[1].set_ylabel("x[n-384] - y[n] (LSB)");ax[1].set_xlim(0,len(base["y"])-1);ax[1].set_ylim(-700,950);ax[1].legend(loc="upper right",fontsize=11,ncols=2)
 save(fig,"03_threshold_waveforms_and_error","Threshold impact on waveforms","Increasing THR2 changes the output and can spread error around the finite input boundaries. Shaded areas in the lower panel lie outside the delayed input support. They remain part of the error calculation.")
 # Threshold sweep uses a symlog numerical x-axis to include zero.
 fig,ax=layout("Threshold sweep: suppression versus reconstruction error","11 fresh C++ runs on the same 1024-sample input  |  Metrics cover all 9 frames or all 1536 output samples",3)
 s=[cases[f"multitone_thr2_{t}"]["summary"] for t in THRESHOLDS];tx=np.array(THRESHOLDS,dtype=float)
 ys=[[r["eligible_suppression_percent"] for r in s],[r["eligible_spectral_mag2_retained_percent"] for r in s],[r["rmse_full_stream_lsb"] for r in s]]
 labels=["Eligible bins\nsuppressed (%)","Eligible spectral\nretention (%)","Full-stream\nRMSE (LSB)"]
 for a,y,c,l in zip(ax,ys,[M,T,M],labels):
  a.plot(tx,y,"o-",color=c,ms=6);a.set_xscale("symlog",linthresh=4096,linscale=.35);a.set_ylabel(l)
  a.set_xticks([0,1e4,1e8,1e12,1e16],["0",r"$10^4$",r"$10^8$",r"$10^{12}$",r"$10^{16}$"])
  a.axvline(4096,color="#B08100",ls=":",lw=1.4);a.set_xlim(0,1e17)
 ax[0].set_ylim(-3,106);ax[1].set_ylim(-3,106)
 ax[0].text(.025,.82,"Dotted line: imported baseline THR2 = 4096",transform=ax[0].transAxes,fontsize=11,color=GRAY)
 ax[1].text(.025,.13,"Retention = weighted eligible magnitude squared kept / total",transform=ax[1].transAxes,fontsize=11,color=GRAY)
 ax[2].set_xlabel("THR2, raw magnitude-squared threshold (symlog axis to include zero)")
 save(fig,"04_threshold_tradeoff","Threshold tradeoff","At THR2=10^11, this vector suppresses 93.06% of eligible unique-bin instances and retains 99.21% of weighted eligible spectral magnitude squared, with 22.71 LSB full-stream RMSE. Spectral retention is a representation metric, not electrical energy saved.")
 # Heatmaps of the exact canonical magnitudes and binary masks.
 fig,ax=layout("Frame-by-frame spectrum and suppression","Same multitone run, THR2 = 10^11  |  Frames 0 and 8 contain zero-padded input boundaries",2)
 mag=matrix(medium,"mag2");mask=matrix(medium,"mask")
 cmap=LinearSegmentedColormap.from_list("maroon_gold",["#FCF9FA","#DBBBC7",M,G])
 im=ax[0].imshow(np.log10(np.maximum(mag,1)),origin="lower",aspect="auto",cmap=cmap,interpolation="nearest",extent=[-.5,128.5,-.5,8.5])
 fig.colorbar(im,ax=ax[0],pad=.02,fraction=.026,label="log10(raw magnitude squared)")
 im=ax[1].imshow(mask,origin="lower",aspect="auto",cmap=ListedColormap(["#F3F1F2",M]),vmin=0,vmax=1,interpolation="nearest",extent=[-.5,128.5,-.5,8.5])
 cb=fig.colorbar(im,ax=ax[1],pad=.02,fraction=.026,ticks=[0,1]);cb.ax.set_yticklabels(["Keep","Suppress"])
 for a in ax:a.set_ylabel("STFT frame m");a.set_xlabel("Unique FFT bin k");a.grid(False);a.set_yticks([0,2,4,6,8])
 save(fig,"05_spectrum_and_mask_heatmap","Spectrum and mask across frames","The upper heatmap uses canonical pre-mask magnitudes with a log-display floor of 1. The lower heatmap shows exact binary mask decisions. Protected DC at k=0 stays kept. Frame index is not a hardware-clock or measured-time axis.")
 # Quantized coefficients, decoded from the frozen artifact.
 q=np.array([int(v,16) for v in (repo/"artifacts/coefficients/window_qw.memh").read_text().split()],dtype=np.int64)
 assert len(q)==256 and q[0]==0
 w=q.astype(float)/2**15;phase=np.arange(128);overlap=w[:128]**2+w[128:]**2
 fig,ax=layout("Frozen window coefficients and 50% overlap","Actual window_qw.memh table  |  Periodic square-root Hann, F = 15  |  FFT length 256, hop 128",2)
 ax[0].plot(np.arange(256),w,color=M,label="Quantized window Qw / 2^15");ax[0].axvline(128,color="#B08100",ls="--",label="Hop H = 128")
 ax[0].set_ylabel("Window coefficient");ax[0].set_xlabel("Window sample i");ax[0].legend(loc="upper right",fontsize=11)
 ax[1].plot(phase,overlap,color=M,label="Squared-window overlap sum");ax[1].axhline(1,color="#B08100",ls="--",label="Ideal unquantized value")
 ax[1].set_ylabel("w[i]^2 + w[i+128]^2");ax[1].set_xlabel("Overlap phase i (0 to 127)");ax[1].ticklabel_format(axis="y",style="plain",useOffset=False)
 ax[1].set_ylim(.99994,1.00006);ax[1].legend(loc="lower right",fontsize=11);ax[1].text(.02,.82,f"Maximum deviation from 1: {np.max(np.abs(overlap-1)):.3g}",transform=ax[1].transAxes,color=M)
 save(fig,"06_window_and_overlap","Window and overlap-add coefficients","The top plot decodes the frozen coefficient table. The lower plot shows the quantized squared-window overlap sum, which is close to but not mathematically identical to one. This coefficient property supports reconstruction but is not a standalone proof for all signals.")
 # Impulse data, not an idealized drawn impulse.
 imp=cases["impulse_thr2_0"];ix=np.flatnonzero(imp["x"]);iy=np.flatnonzero(imp["y"])
 assert len(ix)==1 and len(iy)==1 and iy[0]-ix[0]==384
 fig,ax=layout("Impulse response confirms the sample-domain delay","Fresh impulse reference run  |  THR2 = 0  |  No spectral suppression",2)
 ax[0].axhline(0,color=GRAY,lw=.8);ax[0].vlines(ix,0,imp["x"][ix],colors=T,lw=3);ax[0].scatter(ix,imp["x"][ix],color=T,s=65,label="Input impulse")
 ax[0].vlines(iy,0,imp["y"][iy],colors=M,lw=3);ax[0].scatter(iy,imp["y"][iy],color=M,s=65,label="Reference output")
 amp=float(max(imp["x"]));yy=amp*.58
 ax[0].annotate("",xy=(iy[0],yy),xytext=(ix[0],yy),arrowprops={"arrowstyle":"<->","color":M,"lw":1.7})
 ax[0].text((iy[0]+ix[0])/2,amp*.65,"384 samples",ha="center",color=M,weight="bold")
 ax[0].set_xlim(-30,imp["cfg"]["Ny"]);ax[0].set_ylim(-.05*amp,1.22*amp);ax[0].set_ylabel("Sample code (LSB)")
 ax[0].set_xlabel("Sample index n");ax[0].legend(loc="upper right",fontsize=11)
 ax[1].plot(imp["err"],color=M);ax[1].set_ylim(-1,1);ax[1].set_xlabel("Output sample index n");ax[1].set_ylabel("Aligned error (LSB)")
 ax[1].text(.025,.78,"Aligned error = 0 over the complete 1536-sample output",transform=ax[1].transAxes,color=M)
 save(fig,"07_impulse_delay","Impulse diagnostic","The input and output impulses are separated by exactly 384 samples. At an assumed 48 ksample/s replay rate this design delay corresponds to 8 ms. This plot uses sample indices and does not measure hardware timing.")
 pdf.close();return result
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--repo",type=Path,default=Path(__file__).resolve().parents[2])
 ap.add_argument("--run-dir",type=Path);ap.add_argument("--out",type=Path);ap.add_argument("--reference-exe",type=Path);ap.add_argument("--run-reference",action="store_true")
 args=ap.parse_args();repo=args.repo.resolve();root=(args.run_dir or repo/"runs/reference_presentation_20260922").resolve()
 out=(args.out or repo/"docs/presentation/reference_model_20260922").resolve();exe=(args.reference_exe or repo/"build/host/reference_model/Release/phase2_golden_model.exe").resolve()
 if args.run_reference:
  if root.exists() and any(root.iterdir()):raise RuntimeError("Choose a new or empty run directory")
  root.mkdir(parents=True,exist_ok=True)
  for vector,thr,key in specs():
   cmd=[str(exe),"--vector-dir",str(repo/"artifacts/test_vectors"/vector),"--coeff-dir",str(repo/"artifacts/coefficients"),"--output-dir",str(root/key),"--thr2",str(thr),"--collect-bin-stats"]
   r=subprocess.run(cmd,capture_output=True,text=True);(root/(key+".log")).write_text(r.stdout+r.stderr,encoding="utf-8")
   if r.returncode:raise RuntimeError(r.stdout+r.stderr)
 out.mkdir(parents=True,exist_ok=True);(out/"figures").mkdir(exist_ok=True)
 cases={key:load(repo,root,vector,thr,key) for vector,thr,key in specs()};plots=figures(repo,out,cases)
 with (out/"metrics_summary.csv").open("w",newline="",encoding="utf-8") as f:
  wr=csv.DictWriter(f,fieldnames=list(next(iter(cases.values()))["summary"]));wr.writeheader();wr.writerows(c["summary"] for c in cases.values())
 inputs={}
 for vector in sorted({s[0] for s in specs()}):
  for fn in ["config.json","x_in.memh"]:
   p=repo/"artifacts/test_vectors"/vector/fn;d=out/"data/inputs"/vector/fn;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,d);inputs[p.relative_to(repo).as_posix()]=sha(p)
 for p in sorted((repo/"artifacts/coefficients").glob("*.memh")):
  d=out/"data/coefficients"/p.name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,d);inputs[p.relative_to(repo).as_posix()]=sha(p)
 outputs={}
 for key in cases:
  for fn in ["y_out.memh","frame_stats.csv","bin_stats.csv","metrics.json","config.json","source_config.json"]:
   p=root/key/fn;d=out/"data/reference_outputs"/key/fn;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,d);outputs[d.relative_to(out).as_posix()]=sha(d)
 refs=repo/"sw/reference_model";source=[]
 for folder in ["src","include","tools"]:
  source += [p for p in (refs/folder).rglob("*") if p.is_file() and p.suffix in [".cpp",".hpp",".h"]]
 source += [refs/"CMakeLists.txt",repo/"spec/generated/core_config.json"]
 manifest={"schema":"trecap_reference_presentation_v1","created_utc":datetime.now(timezone.utc).isoformat(),
 "status":"reference-model simulation, not RTL or hardware measurement","model_source_root":"sw/reference_model",
 "executable_sha256":sha(exe),"source_files_sha256":{p.relative_to(repo).as_posix():sha(p) for p in sorted(set(source))},
 "input_files_sha256":inputs,"output_files_sha256":outputs,"configuration":{"N":12,"L":256,"H":128,"F":15,"D":384,"sample_rate_hz":None},
 "threshold_sweep_raw":THRESHOLDS,"error_definition":"x[n-D]-y[n], x zero-extended; denominator Ny includes startup and tail",
 "spectral_retention_definition":"weighted eligible pre-mask mag2 kept / total; interior weights 2, Nyquist 1; DC protected",
 "versions":{"python":platform.python_version(),"numpy":np.__version__,"matplotlib":matplotlib.__version__},"figures":plots}
 (out/"provenance.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
 if (root/"validation_report.json").is_file():shutil.copyfile(root/"validation_report.json",out/"validation_report.json")
 shutil.copyfile(Path(__file__),out/"plot_reference_presentation.py")
 chunks=[]
 for f in plots:
  chunks.append(f'<section id="{f["id"]}"><h2>{html.escape(f["title"])}</h2><img src="figures/{f["id"]}.svg" alt="{html.escape(f["title"])}"><p>{html.escape(f["caption"])}</p><a href="figures/{f["id"]}.png">PNG</a> &nbsp; <a href="figures/{f["id"]}.svg">SVG</a></section>')
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T-RECAP reference-model figures</title><style>body{margin:0;background:#f5f3f4;color:#252525;font:17px/1.6 system-ui,sans-serif}header{background:#8c1d40;color:white;padding:32px max(4vw,24px)}header strong{color:#ffc627}main{max-width:1250px;margin:auto;padding:24px}section{background:white;margin:24px 0;padding:25px}h1{margin:0}h2,a{color:#8c1d40}img{width:100%;display:block}p{max-width:1050px}.note{border-left:5px solid #ffc627;padding:12px 20px;background:#fff}nav{display:flex;gap:22px;flex-wrap:wrap}a{font-weight:600}</style><header><strong>TEAM #2</strong><h1>T-RECAP Reference Model</h1><p>Fixed-point waveform reconstruction and threshold tradeoffs</p></header><main><p class="note">All figures use freshly executed C++ reference-model outputs. They do not establish FPGA correctness, hardware speedup, or electrical energy savings.</p><nav><a href="T_RECAP_Reference_Model_Figures.pdf">Open all 7 figures as PDF</a><a href="metrics_summary.csv">Metrics CSV</a><a href="README.md">Methods and speaking notes</a></nav>'''+''.join(chunks)+'</main></html>'
 (out/"index.html").write_text(page,encoding="utf-8")
 notes=["# T-RECAP reference-model presentation figures","","Team #2","","## Scope",
 "We ran the maintained C++ fixed-point reference model on the checked-in input and coefficient artifacts. This package contains 11 threshold settings for the same multitone input, one impulse run, and one zero-input run. These are software reference results, not final golden results, FPGA captures, or electrical measurements.","",
 "The original multitone directory ends in thr64, but its configuration uses the raw squared threshold THR2=4096. Plot labels follow configuration metadata.","",
 "## Present these first","For a short TA discussion, use figure 01 (alignment), figure 02 (mask decision), and figure 04 (tradeoff). The other figures support a longer explanation.","",
 "## Files","- index.html: local gallery.","- T_RECAP_Reference_Model_Figures.pdf: seven full-page figures.","- figures/*.png: 2880 by 1620 pixels for slide insertion.","- figures/*.svg: vector plots.","- metrics_summary.csv: results for every run.","- data/: exact input, coefficient and model-output snapshots.","- provenance.json: source, executable and data hashes.","- validation_report.json: independent artifact consistency checks, when available.","",
 "## Figure explanations"]
 for i,f in enumerate(plots,1):notes += [f"### {i}. {f['title']}",f["caption"],""]
 notes += ["## Quantitative checkpoints","| Raw THR2 | Eligible bins suppressed | Eligible spectral magnitude squared retained | Full-stream RMSE (LSB) | Max absolute error (LSB) |","| --- | ---: | ---: | ---: | ---: |"]
 for thr in [4096,10**6,10**11,10**13]:
  r=cases[f"multitone_thr2_{thr}"]["summary"]
  notes.append(f"| {thr} | {r['eligible_suppression_percent']:.4f}% | {r['eligible_spectral_mag2_retained_percent']:.8f}% | {r['rmse_full_stream_lsb']:.6f} | {r['max_abs_error_lsb']} |")
 notes += ["","## Methods and limits",
 "- Fixed baseline: signed 12-bit samples, FFT length 256, hop 128, F=15, causal delay 384 samples, protected DC, unprotected Nyquist.",
 "- Compare y[n] with x[n-384], zero-extended outside the original input. Errors include every emitted output sample, including startup and tail.",
 "- The multitone and impulse runs have Ns=1024, 9 active frames and Ny=1536. The zero run has Ns=4096, 33 frames and Ny=4608.",
 "- Plot axes use sample indices and FFT bins because vector metadata does not specify a sampling frequency.",
 "- Canonical bin statistics precede masking. A final mask value of 1 suppresses the bin. THR2 is an unsigned raw magnitude-squared threshold, not a voltage or dB level.",
 "- Suppression counts unique eligible bin instances. Retained spectral magnitude squared weights mirrored interior bins by two. Zero-input spectral retention is undefined and appears blank in the summary.",
 "- These results demonstrate this signal and model. They do not establish general denoising usefulness or a universal quality bound.",
 "- Spectral-bin suppression does not measure electrical energy saved. The baseline reference executes its fixed FFT/IFFT computation.",
 "- Spectrum plots use model-exported bin statistics rather than substituting NumPy FFT results.","",
 "## Reproduce","From the project root, build the reference target and choose a fresh run directory:","",
 "    cmake --build build/host --config Release --target phase2_golden_model",
 "    python scripts/analysis/plot_reference_presentation.py --repo . --run-reference --run-dir runs/reference_presentation_new --out docs/presentation/reference_model_new","",
 "Python requires NumPy and Matplotlib. To render recorded runs without executing the model again, omit --run-reference and point --run-dir at the recorded run directory. The script recomputes waveform error metrics before plotting. When running the copied script from this figure package, always pass --repo explicitly.","",
 "## Source contracts","- sw/reference_model/README.md","- sw/reference_model/docs/stft_wola_contract.md","- spec/schemas/bin_stats.schema.md","- spec/schemas/frame_stats.schema.md","- docs/evaluation/benchmark_plan.md",""]
 (out/"README.md").write_text("\n".join(notes),encoding="utf-8")
 print(json.dumps({"output":str(out),"figures":len(plots),"runs":len(cases)},indent=2))
if __name__=="__main__":main()

