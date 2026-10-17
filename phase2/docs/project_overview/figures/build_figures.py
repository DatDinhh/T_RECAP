"""Build README figures from retained evidence. No board, server or network access.

Requires Python, NumPy and Matplotlib. Raw recorded audio is deliberately not
distributed with these figures. Pass an authorized local campaign archive.
"""
from pathlib import Path
import argparse, csv, hashlib, json, os, shutil, sys

ap = argparse.ArgumentParser()
ap.add_argument('--workspace', type=Path, required=True)
ap.add_argument('--profile', type=Path, required=True)
ap.add_argument('--evidence', type=Path, required=True)
ap.add_argument('--out', type=Path, required=True)
ap.add_argument('--python-packages', type=Path)
args = ap.parse_args()
ROOT, PROFILE, DATA, OUT = [p.resolve() for p in (args.workspace, args.profile, args.evidence, args.out)]
OUT.mkdir(parents=True, exist_ok=False)
os.environ['MPLCONFIGDIR'] = str(OUT.parent / 'mpl_cache')
if args.python_packages:
    sys.path.insert(0, str(args.python_packages.resolve()))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,
    'axes.spines.top':False,'axes.spines.right':False,'axes.unicode_minus':False,
    'svg.fonttype':'none','svg.hashsalt':'trecap-readme-evidence', 'savefig.facecolor':'white'})

INK='#19384c'; BLUE='#1672a0'; GREEN='#168575'; ORANGE='#ce762c'; GRAY='#85939e'
RELEASE=ROOT/'work/verification_20261017_release'
sources={}; captions={}; parameters={}; stats={}
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def bind(p, artifact=None):
    p=Path(p)
    if artifact is None:
        if p.is_relative_to(ROOT): artifact='archive:workspace/'+p.relative_to(ROOT).as_posix()
        elif p.is_relative_to(PROFILE): artifact='repo:phase2/profiles/tsh2/'+p.relative_to(PROFILE).as_posix()
        elif p.is_relative_to(DATA): artifact='review-data:'+p.relative_to(DATA).as_posix()
        else: raise ValueError('An explicit public artifact alias is required')
    sources[artifact]={'sha256':sha(p),'bytes':p.stat().st_size}
    return artifact
def dump(name,value): (OUT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def finish(fig,name,caption):
    for ext in ('png','svg'):
        fig.savefig(OUT/(name+'.'+ext),dpi=220,bbox_inches='tight',metadata={'Creator':'TRECAP scientific figure script'} if ext=='svg' else {'Software':'Matplotlib'})
    plt.close(fig); captions[name]=caption
def read_csv(name):
    p=DATA/name; bind(p)
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))

# Architecture is a source-bound conceptual diagram, not measured stage timing.
arch_sources=[
 ROOT/'outputs/trecap_stream8_v01/build01/generated/trecap_core_export_observed.sv',
 ROOT/'outputs/trecap_stream8_v01/build01/generated/trecap_spectral_exporter.sv',
 ROOT/'outputs/trecap_stream8_v01/build01/sources/trecap_hps_top.sv',
 ROOT/'outputs/trecap_stream8_v01/build01/sources/trecap_stream_adapter.sv',
 PROFILE/'work/trecap_stream8_v01/CONTRACT.md',
 PROFILE/'work/trecap_stream8_v01/rtl/trecap_stream_adapter.sv',
 PROFILE/'work/trecap_stream8_v01/host/tsh2_client.c',
 PROFILE/'README.md']
for p in arch_sources:bind(p)
assert sha(arch_sources[3])==sha(arch_sources[5])
top=arch_sources[2].read_text()
assert '.clk_50_i(CLOCK_50)' in top and ".avm_write_i(1'b0)" in top

fig,ax=plt.subplots(figsize=(16,9))
ax.set_xlim(0,16); ax.set_ylim(0,9); ax.axis('off')
def box(x,y,w,h,title,detail='',fc='#f7fafc',ec=BLUE,title_size=12):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.025,rounding_size=0.08',
                             facecolor=fc,edgecolor=ec,linewidth=1.3))
    if detail:
        ax.text(x+w/2,y+h*.67,title,ha='center',va='center',fontsize=title_size,fontweight='bold',color=INK)
        ax.text(x+w/2,y+h*.30,detail,ha='center',va='center',fontsize=10.7,color=INK,linespacing=1.3)
    else:ax.text(x+w/2,y+h/2,title,ha='center',va='center',fontsize=title_size,fontweight='bold',color=INK,linespacing=1.25)
def arrow(points,color=INK,dashed=False):
    xs,ys=zip(*points)
    ax.plot(xs[:-1],ys[:-1],color=color,lw=1.4,ls='--' if dashed else '-')
    ax.add_patch(FancyArrowPatch(points[-2],points[-1],arrowstyle='-|>',mutation_scale=12,
                                color=color,lw=1.4,linestyle='--' if dashed else '-'))
ax.text(.3,8.64,'Finite-file audio processing on DE1-SoC',fontsize=21,fontweight='bold',color=INK)
ax.text(.3,8.22,'Conceptual data flow from the admitted TSH2 sources | 48 kHz, signed 12-bit PCM | 8 s finite epochs',fontsize=12,color=GRAY)
box(.4,6.75,3.5,1.05,'Laptop CPU: file input','384,000 PCM samples\nfinite request + threshold',ec=GREEN)
box(5.0,6.75,4.2,1.05,'HPS CPU: TCP service','Buffer in HPS RAM; feed PCM\nthrough lightweight-bridge MMIO',ec=GREEN)
box(10.25,6.75,5.25,1.05,'THR2 configuration','56-bit squared-magnitude threshold\nprogrammable before START; fixed per epoch',ec=GREEN)
arrow([(3.93,7.27),(4.98,7.27)],GREEN)
ax.text(4.45,7.46,'TCP',ha='center',fontsize=10.5,color=GREEN)
ax.add_patch(FancyBboxPatch((.25,1.95),15.4,4.0,boxstyle='round,pad=0.04,rounding_size=0.12',
                          facecolor='#f5f9fc',edgecolor=BLUE,linewidth=1.5))
ax.text(2.05,5.62,'FPGA FABRIC',fontsize=12,fontweight='bold',color=BLUE)
ax.text(15.4,5.62,'Nominal/constrained CLOCK_50: 50 MHz',ha='right',fontsize=11,color=BLUE)
names=['PCM\nFIFO','Analysis\nwindow','FFT\n256 points','Hermitian\ncanonical','THR2\nmask','Spectrum\nbuilder','IFFT\n256 points','Synthesis\nWOLA']
xs=[.5+1.88*i for i in range(8)]; y=4.25; w=1.55; h=.92
for i,(x,name) in enumerate(zip(xs,names)):
    box(x,y,w,h,name,title_size=11.4)
    if i<7:arrow([(x+w,y+h/2),(xs[i+1]-.025,y+h/2)])
arrow([(7.1,6.73),(7.1,6.22),(1.27,6.22),(1.27,5.19)],GREEN)
arrow([(12.85,6.73),(12.85,6.12),(8.795,6.12),(8.795,5.19)],GREEN,True)
ax.text(1.26,3.99,'256 samples',ha='center',fontsize=9.6,color=GRAY)
ax.text(3.15,3.99,'Hop = 128',ha='center',fontsize=9.6,color=GRAY)
box(7.62,2.45,2.5,.92,'Sparse exporter','TSP1 spectral records',title_size=11.6)
box(10.62,2.45,2.0,.92,'Spectral FIFO','1,024 words',title_size=11.2)
box(13.14,2.45,2.1,.92,'Y FIFO','1,024 words',title_size=11.4)
arrow([(8.80,4.23),(8.80,3.39)])
ax.text(8.98,3.75,'canonical-bin taps',ha='left',fontsize=9.8,color=GRAY)
arrow([(10.14,2.91),(10.59,2.91)])
arrow([(14.44,4.23),(14.44,3.39)])
ax.text(.6,3.12,'Spectral export is an observation branch.\nFinite-source admission controls queue pressure.\nY and spectral bytes have separate output FIFOs.',
        va='center',fontsize=11.2,color=INK,linespacing=1.55)
box(9.75,.4,5.45,1.05,'HPS CPU: drain + reply','Interleave output reads with PCM writes;\nreturn reconstructed Y and TSP1 bytes',ec=GREEN)
box(.4,.4,7.55,1.05,'Laptop CPU: receive and inspect','Strict packet decode -> sparse band features -> bounded monitor\nReconstructed waveform and spectra retained for comparison',ec=GREEN)
arrow([(11.62,2.42),(11.62,1.48)],GREEN)
arrow([(14.2,2.42),(14.2,1.48)],GREEN)
arrow([(9.72,.93),(7.98,.93)],GREEN)
ax.text(8.86,1.13,'TCP reply',ha='center',fontsize=10.4,color=GREEN)
ax.text(.4,.03,'Finite-file, unpaced test path. No live codec input or active FPGA-to-DDR streaming path. Diagram does not claim measured stage latency.',
        fontsize=10.5,color=GRAY)
finish(fig,'current_architecture','Source-bound conceptual TSH2 data flow. Laptop and HPS boxes execute on CPUs; the middle boundary is FPGA fabric. The two HPS boxes describe feeding and draining within one service. THR2 is configurable before a finite epoch and fixed during it. This is not a live-codec or FPGA-DDR streaming diagram, and no stage timing is inferred.')

# A diagnostic STFT of actual returned samples, not the DUT's internal FFT taps.
FS=48000; NS=384000; NY=384512; ALIGN=384; NWIN=1024; HOP=256; NFFT=2048
index_path=RELEASE/'hardware/captures01/index.json'; bind(index_path)
index=json.loads(index_path.read_text())
assert index['status']=='PASS_FRESH_58_PHYSICAL_EPOCHS_EXACT' and not index['gold_uploaded']
input_path=ROOT/'outputs/trecap_stream8_v01/fixtures02/input.i32le'; bind(input_path)
x=np.fromfile(input_path,dtype='<i4').astype(np.int64)
assert len(x)==NS and -2048<=x.min() and x.max()<=2047
series=[x]; selected=[]
for threshold in (0,10**8,10**11):
    cases=sorted([c for c in index['cases'] if c['record_id']=='flute8s' and c['threshold']==threshold],key=lambda c:c['trial'])
    assert len(cases)==2
    actual=[]
    for c in cases:
        folder=RELEASE/'hardware/captures01'/c['capture_id']
        ypath=folder/'y.i32le'; rpath=folder/'capture_receipt.json'
        epath=ROOT/'outputs/trecap_stream8_v01/fixtures02'/f'flute8s_thr{threshold}'/'y.i32le'
        assert sha(input_path)==c['input_sha256']
        assert sha(rpath)==c['capture_receipt_sha256']
        assert sha(epath)==c['y_expected_sha256']
        assert ypath.read_bytes()==epath.read_bytes() and c['y_exact']
        for p in (ypath,rpath,epath):bind(p)
        yfull=np.fromfile(ypath,dtype='<i4').astype(np.int64)
        assert len(yfull)==NY
        actual.append(yfull)
        selected.append({'capture_id':c['capture_id'],'epoch':c['epoch'],'trial':c['trial'],
                         'threshold':threshold,'y_sha256':sha(ypath),'reference_sha256':sha(epath),
                         'input_sha256':sha(input_path),'full_reference_error_lsb':0})
    assert np.array_equal(actual[0],actual[1])
    aligned=actual[0][ALIGN:ALIGN+NS]; series.append(aligned)
    delta=aligned-x
    stats[str(threshold)]={'input_support_samples':NS,'max_input_error_lsb':int(np.abs(delta).max()),
        'nrmse_vs_input_percent':float(100*np.sqrt(np.sum(delta.astype(float)**2)/np.sum(x.astype(float)**2))),
        'full_reference_error_lsb':0}
assert np.array_equal(series[0],series[1])
window=.5-.5*np.cos(2*np.pi*np.arange(NWIN)/NWIN)
def amplitude(a):
    frames=np.lib.stride_tricks.sliding_window_view(np.asarray(a,dtype=float),NWIN)[::HOP]
    z=np.abs(np.fft.rfft(frames*window,n=NFFT,axis=1))/(window.sum()*2048.0)
    z[:,1:-1]*=2
    return z
test_n=np.arange(NWIN)
coherent_sine=2048*np.sin(2*np.pi*32*test_n/NWIN)
assert abs(amplitude(coherent_sine)[0,64]-1)<1e-12
assert abs(amplitude(np.full(NWIN,2048.0))[0,0]-1)<1e-12
assert abs(amplitude(2048*(-1.0)**test_n)[0,-1]-1)<1e-12
assert amplitude(np.zeros(NWIN)).max()==0
spectra=[20*np.log10(np.maximum(amplitude(a),1e-5)) for a in series]
assert np.array_equal(spectra[0],spectra[1])
times=(np.arange(spectra[0].shape[0])*HOP+NWIN/2)/FS
freq=np.fft.rfftfreq(NFFT,1/FS)/1000
fig,axes=plt.subplots(2,2,figsize=(13.4,8),sharex=True,sharey=True)
titles=['Input file','Captured FPGA output: THR2 = 0',r'Captured FPGA output: THR2 = $10^8$',r'Captured FPGA output: THR2 = $10^{11}$']
for ax,s,title in zip(axes.flat,spectra,titles):
    im=ax.pcolormesh(times,freq,s.T,shading='nearest',cmap='magma',vmin=-100,vmax=-20,rasterized=True)
    ax.set_title(title,fontsize=12.8,color=INK,pad=10)
    ax.set_xlim(0,8); ax.set_ylim(0,24); ax.set_yticks([0,6,12,18,24])
    ax.set_xticks(np.arange(0,9,2)); ax.tick_params(labelsize=10)
for ax in axes[:,0]:ax.set_ylabel('Frequency (kHz)')
for ax in axes[-1]:ax.set_xlabel('Input-aligned time (s)')
fig.subplots_adjust(left=.065,right=.88,bottom=.14,top=.865,hspace=.27,wspace=.14)
cax=fig.add_axes([.902,.22,.018,.57]); cb=fig.colorbar(im,cax=cax)
cb.set_label('One-sided amplitude (dBFS)',labelpad=10); cb.set_ticks([-100,-80,-60,-40,-20])
fig.suptitle('Recorded flute input and FPGA reconstruction',fontsize=19,fontweight='bold',color=INK,y=.975)
fig.text(.5,.92,'Same STFT and color scale in every panel; no per-panel normalization',ha='center',fontsize=11.5,color=INK)
fig.text(.5,.060,'Diagnostic STFT: periodic Hann 1,024 samples | hop 256 | FFT 2,048 | 48 kHz | no centering or edge padding',ha='center',fontsize=10.6,color=GRAY)
fig.text(.5,.027,'Alignment: captured Y[384:384384] vs input[0:384000]. All three full outputs match their registered reference exactly.',ha='center',fontsize=10.6,color=GRAY)
finish(fig,'flute_captured_spectrograms','Diagnostic STFT of the registered flute input and actual physical FPGA outputs from epochs 49, 51 and 57. Trial 1 at each threshold is byte-identical. Y is aligned by exactly 384 samples; the displayed support is 384,000 samples. Fixed periodic Hann window, hop, FFT, full 0 to 24 kHz frequency range and -100 to -20 dBFS color range are shared across all panels. These spectrograms are computed from time-domain captures, not internal FPGA FFT taps or regenerated reference samples. Threshold-zero input and output STFT arrays are exactly equal. No new board execution was performed.')
parameters['spectrogram']={'sample_rate_hz':FS,'window':'periodic Hann: 0.5 - 0.5*cos(2*pi*n/1024)',
    'window_samples':NWIN,'hop_samples':HOP,'fft_points':NFFT,'analysis_frames':len(times),
    'frame_center_first_s':float(times[0]),'frame_center_last_s':float(times[-1]),
    'centering':False,'edge_padding':False,'fft_zero_padding_samples':NFFT-NWIN,
    'frequency_range_hz':[0,24000],'color_range_dbfs':[-100,-20],
    'dbfs_definition':'20*log10(one-sided amplitude / 2048); coherent window-gain normalization. Interior rFFT bins doubled; DC and Nyquist not doubled.',
    'floor_amplitude_relative_to_full_scale':1e-5,'alignment_samples':ALIGN,
    'alignment_expression':'captured_y[384:384384] compared with input[0:384000]',
    'per_panel_normalization':False,'rendered_trial':0,'capture_records':selected,
    'numerical_controls':'Zero, coherent full-scale sine, full-scale DC and Nyquist normalization checks passed; threshold0 STFT array equality passed.'}
dump('spectrogram_metrics.json',stats)

# Workload sources were independently reconciled from recorded raw paired trials.
bind(DATA/'host_workload_audit.json'); bind(DATA/'source_bindings.json')
flute=read_csv('flute_downstream_paired.csv')
decode=[r for r in flute if r['stage']=='decode_consumer']
consume=[r for r in flute if r['stage']=='consumer']
assert [int(r['threshold']) for r in decode]==[0,10**8,10**9,10**10,10**11]
pos=np.arange(5); labels=['0',r'$10^8$',r'$10^9$',r'$10^{10}$',r'$10^{11}$']
fig,axes=plt.subplots(1,2,figsize=(13.2,5.7),gridspec_kw={'width_ratios':[1.03,1]})
ax=axes[0]
d=np.array([float(r['dense_median_ms']) for r in decode]); s=np.array([float(r['sparse_median_ms']) for r in decode])
ax.bar(pos-.18,d,.35,color=GRAY,label='Same-threshold dense')
ax.bar(pos+.18,s,.35,color=BLUE,label='Captured sparse')
for j in range(5):
    ax.text(j-.18,d[j]+.10,f'{d[j]:.2f}',ha='center',fontsize=9.5)
    ax.text(j+.18,s[j]+.10,f'{s[j]:.2f}',ha='center',fontsize=9.5)
ax.set_ylim(0,7.4); ax.set_ylabel('Median elapsed time (ms / 8 s clip)')
ax.set_title('Strict decode + 16-band features',fontsize=13,color=INK)
ax.legend(frameon=False,fontsize=9.7,loc='upper right')
ax=axes[1]
for offset,rows,color,label in [(-.06,decode,BLUE,'Decode + features'),(.06,consume,GREEN,'Feature accumulator only')]:
    y=np.array([float(r['paired_median_dense_over_sparse']) for r in rows]); lo=np.array([float(r['paired_ratio_q1']) for r in rows]); hi=np.array([float(r['paired_ratio_q3']) for r in rows])
    ax.errorbar(pos+offset,y,yerr=[y-lo,hi-y],fmt='o-',color=color,capsize=4,lw=1.6,label=label)
ax.axhline(1,color=GRAY,ls='--',lw=1.3)
ax.text(4.3,1.12,'Equal time',ha='right',fontsize=9.5,color=GRAY)
ax.set_ylim(0,9); ax.set_ylabel('Paired dense / sparse elapsed time')
ax.set_title('Measured paired ratios and IQR',fontsize=13,color=INK)
ax.legend(frameon=False,loc='upper left',fontsize=9.8)
for ax in axes:
    ax.set_xticks(pos,labels); ax.set_xlabel('THR2'); ax.grid(axis='y',color='#e4e9ed'); ax.set_axisbelow(True)
fig.suptitle('CPU workload on replayed physical FPGA spectra',fontsize=18,fontweight='bold',color=INK,y=.99)
fig.text(.5,.104,'Intel Core i7-8750H, Windows 11 | 30 paired warm-RAM trials per threshold | whiskers: descriptive within-session IQR',ha='center',fontsize=10.4,color=GRAY)
fig.text(.5,.055,'Threshold 0 is an adverse control: sparse decode + features takes 20.78% more paired time. At THR2 = 1e8, paired saving is 77.21%.',ha='center',fontsize=10.4,color=GRAY)
fig.text(.5,.008,'Historical host replay, not laptop-vs-FPGA speedup. No network, FFT/IFFT, AI inference or new board/timing execution.',ha='center',fontsize=10.4,color=GRAY)
fig.tight_layout(rect=(0,.16,1,.92),w_pad=2.5)
finish(fig,'host_workload_flute','Historical warm-RAM host replay of physically captured FPGA sparse packets against host-derived same-threshold dense controls. Both implementations produce identical features. Left: medians of elapsed decode plus feature time. Right: medians and descriptive quartiles of the 30 paired dense/sparse ratios, not ratios of the displayed medians or confidence intervals. Threshold zero is an unfavorable sparse control. This does not measure FPGA-versus-laptop speedup, network, FFT/IFFT or AI inference. CPU identity applies only to this historical campaign.')
parameters['host_workload_flute']={'plot_data':'flute_downstream_paired.csv','origin':'historical_physical_FPGA_sparse_packets_replayed_on_CPU','trials_per_threshold_per_stage':30,'clip_seconds':8,'cpu':'Intel Core i7-8750H','os':'Windows 11','error_bars':'within-session descriptive paired-ratio IQR, not confidence intervals','timing_scope':'warm-RAM batch elapsed time','no_new_execution':True}

monitor=read_csv('monitor_receiver_paired.csv')
categories=[r['category'].replace('_',' ').title() for r in monitor]
fig,axes=plt.subplots(1,2,figsize=(12.5,5.5),gridspec_kw={'width_ratios':[1.16,1]})
pos=np.arange(4)
for offset,key,color,label in [(-.18,'dense_receiver_median_ms',GRAY,'Dense receiver'),(.18,'sparse_receiver_median_ms',GREEN,'Sparse receiver')]:
    v=[float(r[key]) for r in monitor]
    axes[0].barh(pos+offset,v,height=.34,color=color,label=label)
    for j,value in enumerate(v):axes[0].text(value+.08,j+offset,f'{value:.2f}',va='center',fontsize=10)
axes[0].set_yticks(pos,categories);axes[0].invert_yaxis();axes[0].set_xlim(0,7.5)
axes[0].set_xlabel('Median elapsed time (ms / 5 s clip)');axes[0].set_title('Complete receiver',fontsize=13,color=INK)
handles,legend_labels=axes[0].get_legend_handles_labels()
fig.legend(handles,legend_labels,frameon=False,fontsize=10,loc='upper center',bbox_to_anchor=(.29,.89),ncol=2)
y=np.array([float(r['paired_dense_over_sparse_median']) for r in monitor]);lo=np.array([float(r['paired_ratio_q1']) for r in monitor]);hi=np.array([float(r['paired_ratio_q3']) for r in monitor])
axes[1].errorbar(y,pos,xerr=[y-lo,hi-y],fmt='o',capsize=4,color=GREEN,ms=7)
axes[1].set_yticks(pos,categories);axes[1].invert_yaxis();axes[1].set_xlim(.95,1.77)
axes[1].axvline(1,color=GRAY,ls='--');axes[1].set_xlabel('Paired dense / sparse elapsed time')
axes[1].set_title('Median ratio and descriptive IQR',fontsize=13,color=INK)
for j,value in enumerate(y):axes[1].text(hi[j]+.025,j,f'{value:.3f}x',va='center',fontsize=10,color=INK)
for ax in axes:ax.grid(axis='x',color='#e4e9ed');ax.set_axisbelow(True)
fig.suptitle('Monitor receiver timing on software-reference spectra',fontsize=18,fontweight='bold',color=INK,y=.98)
fig.text(.5,.105,'THR2 = 1e7 | 30 paired trials per held-out recording | recorded Windows host session; CPU model not retained',ha='center',fontsize=10.4,color=GRAY)
fig.text(.5,.045,'Cached receiver routes exclude DSP production, transport, disk and context construction. This is separate from physical-board verification.',ha='center',fontsize=10.2,color=GRAY)
fig.tight_layout(rect=(0,.16,1,.91),w_pad=2.5)
finish(fig,'host_workload_monitor_replay','Separate monitor revision02 software-reference timing campaign on four held-out five-second recordings. Plot shows complete receiver routes, 30 paired trials per recording and descriptive paired-ratio IQR. The median across the four per-recording paired median ratios is 1.31073049. The CPU model was not recorded; it must not be borrowed from the flute benchmark. Physical board output verification happened separately. No new timing or hardware execution.')
parameters['host_workload_monitor_replay']={'plot_data':'monitor_receiver_paired.csv','origin':'software_reference_spectra_Windows_host_timing_session','trials_per_recording':30,'clip_seconds':5,'threshold':10**7,'cpu_identity':'not_recorded','os':'Windows','error_bars':'within-recording descriptive paired-ratio IQR, not confidence intervals','median_across_recording_median_ratios':float(np.median(y)),'no_new_execution':True}

# Preserve accepted DV and signal plots byte-for-byte; use new README captions.
reuse={
 'flute_waveform.png':('hardware03/flute_waveform_comparison.png','Recorded five-threshold physical flute waveform comparison. Original plot unchanged; removes 384 leading returned samples and uses common amplitude scales.'),
 'flute_error_agreement.png':('hardware03/flute_error_agreement.png','Recorded input distortion versus exact threshold-specific reference agreement. Original numerical plot unchanged.'),
 'flute_packet_sizes.png':('hardware03/flute_packet_sizes.png','Recorded sparse TSP1 size versus the compact dense TSP1 baseline, not versus WAV or PCM. Original numerical plot unchanged.'),
 'dv_topology.png':('static04/verification_topology.png','Conceptual boundaries of oracle, host checking and physical capture. Original accepted diagram unchanged.'),
 'dv_handshake.png':('traces02/rtl_handshake_backpressure.png','Actual ModelSim ready/valid stall trace from the retained full-length threshold-zero simulation. Original plot unchanged; 10 ns simulation clock is distinct from nominal 20 ns board clock.'),
 'dv_reset.png':('traces02/rtl_reset_response.png','Actual ModelSim clear/reset excerpts during FFT and WOLA operation. Original plot unchanged; full recovery is checked by the separate scoreboard.'),
 'dv_rounding.png':('static04/rounding_boundary.png','Recorded old and repaired C++ responses for four rounded-shift boundary witnesses. Original plot unchanged.'),
}
reused=[]
for name,(rel,caption) in reuse.items():
    src=RELEASE/'figures'/rel; artifact=bind(src)
    shutil.copyfile(src,OUT/name);assert sha(src)==sha(OUT/name)
    reused.append({'published':name,'source_artifact':artifact,'sha256':sha(src),'transformation':'none; byte-for-byte PNG copy'})
    captions[name.removesuffix('.png')]=caption
for rel in ('figures/manifest.json','figures/vcd_final_binding01.json','figures/hardware03/provenance.json',
            'rtl/full384000_dense0/report.json','rtl/reset_waveform/report.json'):
    bind(RELEASE/rel)
provenance={'schema':'trecap-readme-scientific-figures-v1','status':'PASS_SOURCE_AND_NUMERICAL_CHECKS',
    'new_hardware_execution':False,'new_timing_execution':False,
    'script_sha256':sha(__file__),'runtime':{'python':sys.version.split()[0],'numpy':np.__version__,'matplotlib':matplotlib.__version__},
    'source_artifacts':sources,'plot_parameters':parameters,'captions':captions,'reused_pngs':reused,
    'publication_scope':'Derived plots, source code and summary metrics only. No raw audio, capture waveform arrays, private paths, network identities or runtime UUIDs are exported.',
    'outputs':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(OUT.iterdir()) if p.suffix in ('.png','.svg','.json')}}
dump('figure_provenance.json',provenance)
for p in OUT.glob('*.svg'):
    text=p.read_text(encoding='utf-8');assert '\u2013' not in text and '\u2014' not in text,p.name
print(json.dumps({'status':provenance['status'],'figures':len(captions),'output_files':len(provenance['outputs'])+1,'spectrogram_frames':len(times)},indent=2))
