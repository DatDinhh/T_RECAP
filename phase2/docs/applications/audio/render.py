"""Render archived numerical results and a local listening page. No board access."""
from pathlib import Path
import json
import html
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
CASES = {'speech_test_a':'Speech A','speech_test_b':'Speech B','music_test_a':'Piano','music_test_b':'Jazz'}
ROUTES = {'original_pcm16':'Original PCM16','fpga_t0':'FPGA threshold 0','fpga_t100000000':'FPGA threshold 10^8','fpga_t10000000000':'FPGA threshold 10^10'}
COLORS = ['#c7ced9','#b8d5d0','#c8c2e4','#ecc9ad']
def read(name): return json.loads((HERE/name).read_text(encoding='utf-8'))
def save(fig,name):
    fig.savefig(HERE/'figures'/f'{name}.png',dpi=170,bbox_inches='tight')
    fig.savefig(HERE/'figures'/f'{name}.svg',bbox_inches='tight')
    plt.close(fig)

def figures():
    plt.rcParams.update({'font.family':'serif','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    rows=read('data/flac_summary.json')['rows']
    fig,axes=plt.subplots(1,3,figsize=(16,5.4),layout='constrained')
    x=np.arange(4)
    for j,route in enumerate(ROUTES):
        rr=[next(r for r in rows if r['case']==c and r['route']==route) for c in CASES]
        for ax,key in zip(axes,['flac_kib','encode_median_ms','relative_l2_vs_original_pct']):
            vals=np.array([r[key] for r in rr])
            err=None
            if key=='encode_median_ms':
                err=[vals-np.array([r['encode_q25_ms'] for r in rr]),np.array([r['encode_q75_ms'] for r in rr])-vals]
            ax.bar(x+(j-1.5)*.19,vals,.18,color=COLORS[j],edgecolor='#596575',linewidth=.5,label=ROUTES[route],yerr=err,capsize=2,error_kw={'lw':.8})
    for ax,title,y in zip(axes,['Actual FLAC size','Warm-RAM encoding time','Decoded error vs original'],['KiB per 8-second clip','Median ms per clip, bars show IQR','Relative L2 (%)']):
        ax.set(title=title,ylabel=y,xticks=x,xticklabels=list(CASES.values()))
        ax.grid(axis='y',alpha=.16)
        ax.set_axisbelow(True)
    fig.legend(*axes[0].get_legend_handles_labels(),loc='outside lower center',ncol=4,frameon=False)
    fig.suptitle('Four recorded audio clips processed by the unchanged TSH2 FPGA\nFLAC level 5, common PCM format, actual decoded outputs',fontsize=16)
    save(fig,'flac_tradeoff')
    den=read('data/denoising_summary.json')
    fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout='constrained')
    x=np.arange(2)
    axes[0].bar(x-.18,[r['mean_snr_improvement_db'] for r in den],.35,color=COLORS[1],label='Mean noisy-case gain')
    axes[0].bar(x+.18,[r['worst_snr_improvement_db'] for r in den],.35,color=COLORS[3],label='Worst noisy-case gain')
    axes[0].axhline(0,color='#596575',lw=.7)
    axes[0].set(title='Error against the known target',ylabel='SNR change (dB)')
    axes[0].legend(frameon=False,fontsize=9)
    axes[1].bar(x-.18,[r['clean_control_max_l2_pct'] for r in den],.35,color=COLORS[2],label='Whole-clip error')
    axes[1].bar(x+.18,[r['quiet_clean_max_l2_pct'] for r in den],.35,color=COLORS[3],label='Quiet-region error')
    axes[1].set(title='Worst damage when no noise was added',ylabel='Relative L2 (%)')
    axes[1].legend(frameon=False,fontsize=9)
    for ax in axes:
        ax.set_xticks(x,['Speech, threshold 10^10','Music, threshold 3 x 10^9'])
        ax.grid(axis='y',alpha=.16)
        ax.set_axisbelow(True)
    fig.suptitle('Hard-threshold denoising pilot on the software reference\n16 noisy held-out conditions per content type, not physical board results',fontsize=14)
    save(fig,'denoising_tradeoff')

def pages():
    credits=read('data/source_credits.json')
    text=['# Audio sources and licenses','','[Application](README.md) | [Listen](listen.html)','','The upstream audio is separately licensed from T-RECAP software. Each title, source and license below applies to its prepared and processed derivatives. Piano media is restricted to noncommercial use under CC BY-NC 3.0. No endorsement by the artists or dataset authors is implied.','']
    for c in credits:
        text += ['## '+CASES[c['id']],'',c['credit'].strip(),'']
        for ext,s in c['sources'].items():
            text += [f'- [Pinned original {ext} file]({s["url"]}), SHA-256 `{s["sha256"]}`']
        text += ['']
    text += ['## Changes made to the recordings','','FLAC experiment derivatives use the first 8 seconds, mono channel averaging, resampling to 48 kHz, a common fixed gain of 0.5, PCM16 preparation and signed 12-bit quantization. Hardware derivatives additionally apply thresholding and IFFT/WOLA, fixed alignment and expansion back into a PCM16 container. FLAC uses preset 5. No per-output normalization is used.','','Denoising derivatives use a separate frozen level preparation, synthetic noise and the existing fixed-point software algorithm. The listening page labels these separately. Its reference, noisy and processed versions share a common playback conversion within each example.','','The repository provides links to the full original upstream files and includes only the prepared excerpts and their derivatives for this educational comparison.']
    (HERE/'CREDITS.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>T-RECAP audio comparisons</title>',
    '<style>body{margin:32px auto;padding:0 24px;max-width:1300px;background:#111a2a;color:#e7eef6;font:16px/1.6 system-ui}h1,h2,h3{line-height:1.25}a{color:#a8d6ed}section{padding:22px;margin:22px 0;background:#1d2a3e;border-radius:14px}.players{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}audio{width:100%}img{max-width:100%}.note{border-left:4px solid #ecc9ad;padding:16px}pre{white-space:pre-wrap;font:14px/1.5 system-ui}@media(max-width:900px){.players{grid-template-columns:1fr 1fr}}@media(max-width:550px){.players{grid-template-columns:1fr}}</style>',
    '<h1>Listen to the threshold tradeoff</h1><p><a href="README.md">Methods and measured results</a> | <a href="CREDITS.md">Credits and licenses</a></p><p class="note">Keep playback volume fixed. A quieter background can also mean lost detail. These are archived samples, not a live connection to the FPGA.</p><h2>Actual FPGA output followed by FLAC</h2><p>All four versions use the same playback gain. Threshold 0 already includes signed 12-bit input quantization. FLAC decodes exactly to the waveform provided to its encoder.</p>']
    for ident,name in CASES.items():
        parts+=['<section><h2>'+name+'</h2><div class="players">']
        for route,label in ROUTES.items():
            path=f'media/{ident}/{route}'
            parts += [f'<div><h3>{label}</h3><audio controls preload="none" src="{path}.wav"></audio><p><a href="{path}.wav" download>WAV</a> | <a href="{path}.flac" download>FLAC</a></p></div>']
        parts += ['</div></section>']
    parts+=['<img src="figures/decoded_spectrograms.png" alt="Decoded original and three FPGA thresholds"><h2>Separate software denoising pilot</h2><p class="note">The following processed clips are fixed-point software-reference outputs. They are not board captures. All show the same preselected condition with synthetic hiss at 5 dB input SNR. Speech uses threshold 10^10 and music uses 3 x 10^9.</p>']
    for ident,name in CASES.items():
        parts+=['<section><h2>'+name+'</h2><div class="players">']
        for route,label in [('reference','Reference before added noise'),('noisy','Noisy input'),('processed','Software-processed output')]:
            path=f'media/denoising/{ident}/{route}.wav'
            parts += [f'<div><h3>{label}</h3><audio controls preload="none" src="{path}"></audio><p><a href="{path}" download>Download WAV</a></p></div>']
        parts+=['</div></section>']
    parts+=['<h2>Attribution</h2>']
    for c in credits: parts += ['<h3>'+CASES[c['id']]+'</h3><pre>'+html.escape(c['credit'])+'</pre>']
    parts+=['<p>Recordings were excerpted, resampled, level adjusted, quantized and processed as described in the methods. Denoising derivatives also contain synthetic noise. Piano media is CC BY-NC 3.0. The audio is not relicensed under the software license.</p></html>']
    (HERE/'listen.html').write_text('\n'.join(parts)+'\n',encoding='utf-8')

if __name__=='__main__':
    figures()
    pages()
