#!/usr/bin/env python3
"""Frozen-baseline IFFT isolation verification. Writes only a new run directory.

No hardware tools; native ModelSim only. All arithmetic vectors use Python integers,
ties-away rounding, and explicit saturation. Safe full frames are additionally
cross-checked with the repository's independent recursive integer oracle.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import subprocess
import sys
import time

SEED = 0x5A17B00B
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def round_away(v, shift):
    q, r = divmod(abs(v), 1 << shift)
    return (-1 if v < 0 else 1) * (q + (2*r >= (1 << shift)))
def clip(v, width):
    y = min((1 << (width-1))-1, max(-(1 << (width-1)), v))
    return y, y != v
def butterfly(a, b, w, norm=0, ow=36):
    tr,s0 = clip(round_away(b[0]*w[0]-b[1]*w[1],15),36)
    ti,s1 = clip(round_away(b[0]*w[1]+b[1]*w[0],15),36)
    vals = [a[0]+tr,a[1]+ti,a[0]-tr,a[1]-ti]
    qs = [clip(round_away(x,norm),ow) for x in vals]
    return [q[0] for q in qs], (s0 or s1 or any(q[1] for q in qs))
def packed(items):
    v = 0
    for value,width in items: v = (v << width) | (value & ((1 << width)-1))
    return v
def write_mem(path, values, bits):
    path.write_text(''.join(f'{v:0{(bits+3)//4}x}\n' for v in values), encoding='ascii')
def signed_rom(path, width):
    vals = [int(s.split('//')[0].strip(),16) for s in path.read_text().splitlines() if s.split('//')[0].strip()]
    return [x-(1<<width) if x&(1<<(width-1)) else x for x in vals]
def make_vectors(repo, run):
    rng = random.Random(SEED); lo=-(1<<35); hi=(1<<35)-1
    cases = [((hi,lo),(0,0),(65535,-65536)), ((lo,hi),(hi,lo),(65535,-65536))]
    extremes = [0,1,-1,16383,16384,16385,-16383,-16384,-16385,hi,lo,hi-1,lo+1]
    tws = [(0,0),(32768,0),(0,32768),(-32768,0),(0,-32768),(16384,16384),(65535,-65536),(-65536,65535),(1,-1)]
    for i,x in enumerate(extremes):
        for j,w in enumerate(tws):
            cases.append(((x,extremes[(i+j)%len(extremes)]),(x,x if j%2 else -x if x!=lo else hi),w))
            cases.append(((x,-x if x!=lo else hi),(0,0),w))
    while len(cases)<2304:
        i=len(cases)
        a=(rng.randint(lo,hi),rng.randint(lo,hi))
        if i%4==0:b=(0,0)
        elif i%4==1:b=(rng.choice(extremes),0)
        elif i%4==2:b=(rng.randint(lo,hi),rng.randint(lo,hi))
        else:b=(rng.choice([-3,-1,1,3]),rng.choice([-3,-1,1,3]))
        w=tws[i%len(tws)] if i%3 else (rng.randint(-65536,65535),rng.randint(-65536,65535))
        cases.append((a,b,w))
    write_mem(run/'stage_input.memh',[packed([(x,36) for x in (*a,*b)]+[(x,17) for x in w]) for a,b,w in cases],178)
    stage_stats={}
    for norm,ow,name in [(0,36,'stage_gold.memh'),(1,28,'stage_norm_gold.memh')]:
        gs=[butterfly(a,b,w,norm,ow) for a,b,w in cases]
        write_mem(run/name,[packed([(sat,1)]+[(x,ow) for x in vals]) for vals,sat in gs],4*ow+1)
        stage_stats[name]={'vectors':len(gs),'saturated':sum(x[1] for x in gs),'zero_b':sum(b==(0,0) for a,b,w in cases)}
    wr=signed_rom(repo/'artifacts/coefficients/twiddle_inv_re.memh',17)
    wi=signed_rom(repo/'artifacts/coefficients/twiddle_inv_im.memh',17)
    table=list(zip(wr,wi)); lim=(1<<27)-1
    frames=[[(0,0)]*256,
            [(lim,0)]+[(0,0)]*255,
            [(0,0)]*37+[(1234567,-7654321)]+[(0,0)]*(255-37),
            [(lim if k%2 else -lim,0) for k in range(256)],
            [(lim,lim) for k in range(256)],
            [(rng.randint(-4000000,4000000),rng.randint(-4000000,4000000)) if k%3==0 else (0,0) for k in range(256)]]
    # Sign-aligned real/imag spectra stress large inverse sums without relying on floats for expected arithmetic.
    frames.append([(lim if math.cos(2*math.pi*13*k/256)>=0 else -lim, -lim if math.sin(2*math.pi*13*k/256)>=0 else lim) for k in range(256)])
    frames.append([(-(1<<27) if k%2==0 else lim, lim if k%3 else -(1<<27)) for k in range(256)])
    while len(frames)<20:
        n=len(frames)
        frames.append([(rng.randint(-(1<<27),lim),rng.randint(-(1<<27),lim)) if rng.randrange(8)>n%7 else (0,0) for k in range(256)])
    def recursive(items):
        if len(items)==1:return items,False
        ev,es=recursive(items[::2]);od,os=recursive(items[1::2]);low=[];high=[];sat=es or os
        for k,(a,b) in enumerate(zip(ev,od)):
            vals,s=butterfly(a,b,table[k*256//len(items)]);sat|=s
            low.append(tuple(vals[:2]));high.append(tuple(vals[2:]))
        return low+high,sat
    spec=importlib.util.spec_from_file_location('study_independent_oracle',repo/'scripts/verification/reference_integer_oracle.py')
    oracle=importlib.util.module_from_spec(spec);sys.modules[spec.name]=oracle;spec.loader.exec_module(oracle)
    results=[recursive(f) for f in frames];cross=0
    for f,(y,sat) in zip(frames,results):
        if not sat:
            assert y==oracle.transform(f,table,True),'recursive oracle disagreement'
            cross+=1
    write_mem(run/'ifft_input.memh',[packed([(r,28),(i,28)]) for f in frames for r,i in f],56)
    write_mem(run/'ifft_gold.memh',[packed([(r,36),(i,36)]) for y,s in results for r,i in y],72)
    write_mem(run/'ifft_sat.memh',[int(s) for y,s in results],1)
    return {'seed':SEED,'stage':stage_stats,'ifft_frames':len(frames),'independent_safe_frames':cross,'ifft_saturated_frames':sum(s for y,s in results)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-repo',required=True,type=Path)
    p.add_argument('--candidate-overlay',required=True,type=Path)
    p.add_argument('--candidate-repo',type=Path)
    p.add_argument('--simulator-dir',required=True,type=Path)
    p.add_argument('--run-dir',required=True,type=Path)
    p.add_argument('--profile-csv',type=Path)
    p.add_argument('--timeout-s',type=int,default=300)
    p.add_argument('--skip-profile',action='store_true')
    args=p.parse_args();repo=args.baseline_repo.resolve();overlay=args.candidate_overlay.resolve();run=args.run_dir.resolve();here=Path(__file__).resolve().parent
    if run.exists():p.error('--run-dir must not exist')
    run.mkdir(parents=True)
    manifest={'schema':'ifft-zero-study-verification-1','status':'running','baseline':str(repo),'overlay':str(overlay),'commands':[],'inputs':{},'started_unix':time.time()}
    def inventory(path):
        path=path.resolve();manifest['inputs'][str(path)]={'sha256':sha(path),'bytes':path.stat().st_size};return path.as_posix()
    def save(): (run/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    def call(label,argv,cwd):
        rec={'name':label,'argv':argv,'cwd':str(cwd)};manifest['commands'].append(rec);save();t=time.monotonic()
        with (run/(label+'.log')).open('w') as f:
            done=subprocess.run(argv,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=args.timeout_s)
        rec.update(returncode=done.returncode,elapsed_s=time.monotonic()-t)
        log=(run/(label+'.log')).read_text(errors='replace');save()
        if done.returncode or re.search(r'(?im)^\s*(?:#\s*)?\*\*\s*(?:Error|Fatal)\b',log) or any(int(x) for x in re.findall(r'Errors:\s*(\d+)',log)):
            raise RuntimeError(label+' failed; see '+str(run/(label+'.log')))
        print(label+' passed',flush=True);return log
    tools={n:inventory(args.simulator_dir/(n+'.exe')) for n in ['vlib','vmap','vlog','vsim']}
    def library(name):
        lib=(run/name).as_posix();call(name+'_vlib',[tools['vlib'],lib],run);return lib
    def filelist(root,use_overlay):
        out=[]
        for line in (root/'filelists/rtl_core_plus_fft.f').read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if line.startswith('+incdir+'):
                out.append('+incdir+'+(root/line[len('+incdir+'):]).as_posix());continue
            path=overlay/line if use_overlay and (overlay/line).is_file() else root/line
            out.append(inventory(path))
        return out
    ini=(run/'modelsim.ini').as_posix()
    def compile_lib(lib,label,sources,defines=[]):call(label,[tools['vlog'],'-sv','-warning','2892','-modelsimini',ini,'-work',lib,*defines,*sources],repo)
    def simulate(lib,top,label):
        log=call(label,[tools['vsim'],'-c','-modelsimini',ini,'-lib',lib,top,'-onfinish','stop','-l',(run/(label+'.transcript.log')).as_posix(),'-wlf',(run/(label+'.wlf')).as_posix(),'+VECTORS='+run.as_posix(),'+PROFILE='+str(run/(label+'.csv')).replace('\\','/'),'-do','onerror {quit -code 1}; run -all; quit -code 0'],repo)
        banner={'stage_lockstep_tb':'STUDY_STAGE_PASS','ifft_lockstep_tb':'STUDY_IFFT_PASS','core_profile_tb':'STUDY_PROFILE_PASS'}[top]
        if len(re.findall(r'^# '+banner+r'\b',log,re.M))!=1:raise RuntimeError(label+' missing unique PASS banner')
        manifest[label+'_pass_lines']=[x.lstrip('# ') for x in log.splitlines() if '_PASS' in x];save()
    try:
        manifest['vectors']=make_vectors(repo,run)
        for fn in ['run_verification.py','stage_lockstep_tb.sv','ifft_lockstep_tb.sv','core_profile_tb.sv']:
            if (here/fn).is_file():inventory(here/fn)
        for path in (repo/'artifacts').rglob('*.memh'):inventory(path)
        inventory(repo/'scripts/verification/reference_integer_oracle.py')
        for src,target,name in [('trecap_fft_stage.sv','baseline_stage.sv','baseline_fft_stage'),('trecap_ifft256.sv','baseline_ifft.sv','baseline_ifft256')]:
            path=repo/'rtl/fft'/src;inventory(path);body=path.read_text()
            body=re.sub(r'\btrecap_fft_stage\b','baseline_fft_stage',body)
            if src=='trecap_ifft256.sv':body=re.sub(r'\btrecap_ifft256\b',name,body)
            (run/target).write_text(body)
        call('vmap',[tools['vmap'],'-c'],run)
        lib=library('work');sources=filelist(repo,True)+[inventory(run/'baseline_stage.sv'),inventory(run/'baseline_ifft.sv'),inventory(here/'stage_lockstep_tb.sv'),inventory(here/'ifft_lockstep_tb.sv')]
        compile_lib(lib,'compile_lockstep',sources)
        simulate(lib,'stage_lockstep_tb','stage');simulate(lib,'ifft_lockstep_tb','ifft')
        if not args.skip_profile:
            base=library('baseline_core');compile_lib(base,'compile_baseline_profile',filelist(repo,False)+[inventory(repo/'platform/de1soc/measurement/trecap_measurement_engine.sv'),inventory(here/'core_profile_tb.sv')]);simulate(base,'core_profile_tb','baseline_profile')
            if args.candidate_repo:
                cand=library('candidate_core');compile_lib(cand,'compile_candidate_profile',filelist(repo,True)+[inventory(args.candidate_repo/'platform/de1soc/measurement/trecap_measurement_engine.sv'),inventory(here/'core_profile_tb.sv')],['+define+STUDY_CANDIDATE']);simulate(cand,'core_profile_tb','candidate_profile')
            if args.profile_csv:
                inventory(args.profile_csv);manifest['profile_comparison']=compare_profile(args.profile_csv,run/'baseline_profile.csv')
                if args.candidate_repo:manifest['candidate_profile_comparison']=compare_profile(args.profile_csv,run/'candidate_profile.csv')
        changed=[p for p,v in manifest['inputs'].items() if sha(Path(p))!=v['sha256']]
        if changed:raise RuntimeError('inputs changed during run: '+str(changed))
        manifest.update(status='passed',inputs_unchanged=True)
    except Exception as e:
        manifest.update(status='failed',error=str(e));print(str(e),file=sys.stderr)
    manifest['finished_unix']=time.time();save();print(json.dumps({'status':manifest['status'],'manifest':str(run/'manifest.json')}))
    return int(manifest['status']!='passed')

def compare_profile(reference,actual):
    fields=['total_butterflies','a_complex_zero','b_complex_zero','both_complex_zero','neither_complex_zero']
    oracle={}
    with reference.open() as f:
        for r in csv.DictReader(f):
            if r['signal']=='measured_multitone' and int(r['threshold2']) in (0,100000000000):
                oracle[(int(r['threshold2']),int(r['frame']),int(r['stage']))]=tuple(int(r[k]) for k in fields)
    seen=0
    with actual.open() as f:
        for r in csv.DictReader(f):
            key=(int(r['threshold2']),int(r['frame']),int(r['stage']))
            if tuple(int(r[k]) for k in fields)!=oracle[key]:raise AssertionError('RTL/Python zero profile mismatch '+str(r))
            seen+=1
    if seen<144:raise AssertionError('incomplete RTL profile '+str(seen))
    return {'rows_equal':seen,'fields':fields,'threshold2':[0,100000000000]}
if __name__=='__main__':sys.exit(main())
