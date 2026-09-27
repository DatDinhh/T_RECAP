#!/usr/bin/env python3
"""Publish an admitted same-image IFFT-isolation campaign; no hardware access.

Requires Python 3 and Matplotlib. Every path is supplied by the caller or by an
evidence manifest. Reads immutable inputs and writes a fresh output directory.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
from string import Template

BASE = 'masked_baseline'
CAND = 'masked_isolated'
THRESHOLD = 100_000_000_000
MAROON, GOLD, INK = '#8C1D40', '#FFC627', '#29272B'

def require(ok, message):
    if not ok: raise ValueError(message)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))

def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def same_hash(path, expected):
    require(Path(path).is_file(),'Missing evidence: '+str(path))
    require(digest(path)==expected.lower(),'Evidence hash mismatch: '+str(path))

def portable(text):
    require(re.search(r'(?i)(?:[a-z]:[\\/]|/Users/|/home/|OneDrive|PNPDeviceID|VID_[0-9a-f]{4}|PID_[0-9a-f]{4}|\bCOM\d+\b|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',text) is None,'Public artifact contains a host path or device identifier')
    return text

def write_json(path, obj):path.write_text(portable(json.dumps(obj,indent=2,allow_nan=False)+'\n'),encoding='utf-8')

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def write_csv(path,rows):
    require(bool(rows),'Refusing empty table '+str(path))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    portable(path.read_text(encoding='utf-8'))

def near(a,b,message,tol=1e-9):require(math.isclose(a,b,rel_tol=1e-10,abs_tol=tol),message)

def probe_words(text):
    require(re.fullmatch(r'[0-9a-fA-F]{120}',text) is not None,'Malformed 480-bit probe')
    n=int(text,16);return [(n>>(32*i))&0xffffffff for i in range(15)]

def validate(args):
    repo=args.repo.resolve();run=args.run_root.resolve();analysis_path=args.analysis.resolve();csv_path=args.csv.resolve()
    campaign_dir=analysis_path.parent.parent
    campaign_path=campaign_dir/'campaign_manifest.json';campaign=read_json(campaign_path);analysis=read_json(analysis_path)
    require(campaign.get('schema')=='trecap_zero_isolation_campaign_v1','Not an IFFT-isolation campaign')
    require(campaign.get('status')=='PASS_CAPTURE_AND_TRIAL_ADMISSION','Campaign is incomplete or not admitted; publication must not read live CSV data')
    require(analysis.get('schema')=='board-measurement-analysis-1','Unexpected analysis schema')
    require(Path(campaign['repo']).resolve()==repo,'--repo must be the frozen candidate source used for this campaign')
    evidence={'analysis':analysis_path,'campaign_manifest':campaign_path,'meter_csv':csv_path}
    audited=[]
    def audit(role,path,expected=None):
        path=Path(path)
        if expected is not None:same_hash(path,expected)
        else:require(path.is_file(),'Missing evidence '+str(path))
        audited.append({'source_role':role,'sha256':digest(path)});return path
    for category in ('sources_sha256','outputs_sha256'):
        require(bool(campaign.get(category)),'Missing campaign hash inventory: '+category)
        for i,(path,expected) in enumerate(campaign[category].items()):audit(category+'_'+str(i+1),path,expected)
    require(all(c.get('exit_code')==0 for c in campaign['commands']),'Acquisition subprocess did not exit successfully')
    analyzer=repo/'scripts/measurement/analyze_board_measurement.py'
    analyzer_hash=next((h for p,h in campaign['sources_sha256'].items() if Path(p).resolve()==analyzer),None)
    require(analyzer_hash is not None,'Campaign did not hash the analyzer');audit('analyzer',analyzer,analyzer_hash)
    for name,source in analysis['sources'].items():
        audit('analysis_source_'+name,source['path'],source['sha256']);evidence[name]=Path(source['path'])
    same_hash(csv_path,analysis['sources']['meter_csv']['sha256'])
    same_hash(campaign_dir/'trials.json',analysis['sources']['trial_events']['sha256'])
    event_doc=read_json(evidence['trial_events']);trials=analysis['trials']
    require(len(trials)==campaign['trial_count']==12,'Expected twelve measured trials')
    require(len({t['trial_id'] for t in trials})==12,'Duplicate trial ID')
    require([t['condition'] for t in trials]==[BASE,CAND,CAND,BASE]*3,'Expected three ABBA blocks')
    original={t['trial_id']:t for t in event_doc['trials']}
    for index,t in enumerate(trials):
        require(t['pair_id']==(index//2+1),'Unexpected consecutive AB/BA pairing')
        require(t['condition'] in (BASE,CAND) and t['threshold2']==THRESHOLD,'Condition/threshold mismatch')
        require(t['completed'] is True and t['mismatch_count']==0 and t['fault_flags']==0,'Failed live output check')
        require(t['clock_hz']==50_000_000 and t['epochs']==16384,'Unexpected finite batch or clock')
        for key,per in [('input_count',1024),('output_count',1536),('frame_count',9)]:require(t[key]==16384*per,'Incorrect live '+key)
        for key,value in original[t['trial_id']].items():require(t[key]==value,'Analysis altered admitted trial evidence: '+key)
        words=probe_words(t['source_event']['probe_hex']);mode=2 if t['condition']==BASE else 3
        require(words[0]==0x54524350 and words[1]>>24==2,'Unexpected live protocol')
        require(words[1]&1==0 and words[1]&2 and words[1]&12==0 and bool(words[1]&(1<<11))==(mode==3),'Terminal isolation/fault status mismatch')
        require(words[2]&0xffff0003==(16384<<16)|mode,'Terminal command/mode mismatch')
        require(words[3:8]==[16384,16384*1536,0,16384*1024,16384*9] and words[10]==0xffffffff and words[11]==0 and words[12]==1536,'Terminal probe counts mismatch')
        require((words[9]<<32)|words[8]==t['cycles'],'Probe/analyzer cycle mismatch')
        require(t['source_event']['completion_lower_bound_source']=='last_busy_snapshot_request','Missing BUSY-derived completion lower bracket')
    require(len({t['cycles'] for t in trials})==1,'Isolation changed runtime; revise fixed-duration report')
    paired=analysis['paired_statistics']
    require((paired['baseline_condition'],paired['candidate_condition'],paired['n_pairs'])==(BASE,CAND,6),'Expected six isolated-minus-baseline pairs')
    require(len(paired['pairs'])==6 and {str(p['pair_id']) for p in paired['pairs']}=={str(n) for n in range(1,7)},'Duplicate or missing paired-statistic IDs')
    pairs=[]
    for pair_id in range(1,7):
        group={t['condition']:t for t in trials if t['pair_id']==pair_id};require(set(group)=={BASE,CAND},'Incomplete pair')
        a,b=group[BASE],group[CAND];delta=b['interior_board_power_W']-a['interior_board_power_W']
        saved=next(p for p in paired['pairs'] if str(p['pair_id'])==str(pair_id))
        near(delta,saved['delta_interior_power_candidate_minus_baseline_W'],'Paired sign/value mismatch')
        energy=b['board_energy_interpolated_J']-a['board_energy_interpolated_J']
        elo=b['board_energy_bounds_J'][0]-a['board_energy_bounds_J'][1];ehi=b['board_energy_bounds_J'][1]-a['board_energy_bounds_J'][0]
        near(energy,saved['delta_board_energy_candidate_minus_baseline_J'],'Paired energy mismatch')
        for actual,wanted in zip(saved['delta_board_energy_timing_bounds_J'],(elo,ehi)):near(actual,wanted,'Paired energy bound mismatch')
        pairs.append({'pair_id':pair_id,'baseline_trial':a['trial_id'],'isolated_trial':b['trial_id'],'baseline_interior_power_W':a['interior_board_power_W'],'isolated_interior_power_W':b['interior_board_power_W'],'isolated_minus_baseline_mW':delta*1000,'power_timing_lower_mW':(b['interior_board_power_timing_bounds_W'][0]-a['interior_board_power_timing_bounds_W'][1])*1000,'power_timing_upper_mW':(b['interior_board_power_timing_bounds_W'][1]-a['interior_board_power_timing_bounds_W'][0])*1000,'batch_energy_difference_J':energy,'energy_timing_lower_J':elo,'energy_timing_upper_J':ehi})
    stats=paired['delta_interior_power_candidate_minus_baseline_W'];values=[p['isolated_minus_baseline_mW']/1000 for p in pairs]
    mean=statistics.mean(values);half=2.570581835636305*statistics.stdev(values)/math.sqrt(6)
    near(stats['mean'],mean,'Paired mean mismatch')
    for actual,wanted in zip(stats['paired_mean_95pct_t_interval'],(mean-half,mean+half)):near(actual,wanted,'Paired 95% t interval mismatch')
    meter=read_csv(csv_path);require(len(meter)==analysis['meter_rows'] and len(meter)>100,'Meter row count mismatch')
    require(analysis['sequence_gaps']==0,'Analysis reported meter gaps')
    previous=None
    for row in meter:
        require(all(math.isfinite(float(v)) for v in row.values()),'Nonfinite meter record')
        require(row['memory_ok']=='1' and row['accumulation_valid']=='1','Invalid meter accumulator')
        require(all(row[k]=='0' for k in ['math_overflow','energy_overflow','math_overflow_latched','energy_overflow_latched','memory_error_latched']),'Meter diagnostic fault')
        require(float(row['t_end_s'])>=float(row['t_start_s']),'Reversed meter read interval')
        if previous:
            require(int(row['seq'])==int(previous['seq'])+1,'Meter sequence discontinuity')
            require(float(row['t_start_s'])>=float(previous['t_end_s']),'Meter time discontinuity')
            require(float(row['energy_since_start_J'])>=float(previous['energy_since_start_J']),'Energy accumulation decreased')
        previous=row
    capture_path=campaign_dir/'capture.summary.json';capture=read_json(capture_path)
    require(capture['ok'] is True and capture['rows']==len(meter),'Capture summary mismatch')
    metadata_path=Path(capture['metadata_jsonl']);metadata=read_jsonl(metadata_path)
    sessions=[e for e in metadata if e.get('event')=='session_start']
    require(len(sessions)==1 and sessions[0]['accumulators_reset_once'] is True,'Expected one reset meter session')
    config=sessions[0]['configuration']
    required_config={'shunt_ohms':.015,'max_current_A':10.0,'adc_range':0,'averaging_samples':16,'bus_conversion_us':280,'shunt_conversion_us':280,'mode':'CONT_BUS_SHUNT','requested_log_rate_Hz':10}
    for k,v in required_config.items():require(config[k]==v,'Unexpected meter configuration '+k)
    jtag=read_jsonl(campaign_dir/'jtag.jsonl');complete=[e for e in jtag if e.get('event')=='campaign_complete']
    require(len(complete)==1 and complete[0]['completed'] is True and complete[0]['measured_trials']==12,'Missing campaign completion receipt')
    idle=[e for e in jtag if e.get('event')=='idle_begin'][-1];idle_end=[e for e in jtag if e.get('event')=='idle_end'][-1]
    require(idle['duration_ms']==20000 and idle_end['utc_ms']-idle['utc_ms']>=20000 and idle_end['utc_ms']<=complete[0]['utc_ms'],'Missing final 20-second idle')
    final_snapshot=[e for e in jtag if e.get('event')=='snapshot'][-1];last=probe_words(final_snapshot['probe_hex'])
    require(last[1]>>24==2 and last[1]&0xd==0 and last[2]&3==0 and last[11]==0,'Final snapshot is not clean idle')
    require(final_snapshot['after_utc_ms']>=idle_end['utc_ms'],'Final idle snapshot predates idle receipt')
    program_path=run/'program_manifest.json';program=read_json(program_path);admission_path=run/'build_admission.json';admission=read_json(admission_path)
    require(program['status']=='PROGRAMMED' and program['exit_code']==0,'Programming receipt not successful')
    audit('build_admission',admission_path,program['build_admission_sha256']);audit('programmed_sof',program['sof'],program['sof_sha256'])
    require(program['sof_sha256'].lower()==admission['sof_sha256'].lower(),'Program/admission SOF mismatch')
    require(admission['status']=='PASS_REVIEWED_MEASUREMENT_IMAGE' and admission['fabric_clock_hz']==50_000_000 and admission['protocol']==2 and admission['fabric_latches']==0 and admission['user_pins_verified']==12,'Build admission incomplete')
    build=Path(program['sof']).parent.parent;receipt_path=build/'build_receipt.json';receipt=read_json(receipt_path)
    require(receipt['ok'] is True and receipt['sof_sha256'].lower()==program['sof_sha256'].lower(),'Build receipt/SOF mismatch')
    require(Path(receipt['repo_root']).resolve()==repo,'Build used a different source repository')
    corners_path=Path(receipt['timing_corners_csv']);corners=read_csv(corners_path)
    require(len(corners)==16 and len({r['corner'] for r in corners})==4 and all(float(r['slack_ns'])>=0 for r in corners),'Four-corner timing failed')
    for check in ('setup','hold','recovery','removal'):
        vals=[float(r['slack_ns']) for r in corners if r['check']==check];require(len(vals)==4,'Missing timing checks');near(min(vals),admission['fabric_min_'+check+'_slack_ns'],'Timing/admission mismatch')
    fit_path=build/'output_files/trecap_measurement.fit.summary';fit=fit_path.read_text(encoding='utf-8-sig');require('Fitter Status : Successful' in fit,'Fitter unsuccessful')
    resources={}
    for key,label in [('ALMs','Logic utilization (in ALMs)'),('registers','Total registers'),('RAM_blocks','Total RAM Blocks'),('DSP_blocks','Total DSP Blocks')]:
        found=re.search(re.escape(label)+r'\s*:\s*([\d,]+)',fit);require(found is not None,'Missing fitter resource '+label);resources[key]=int(found[1].replace(',',''))
    require(resources==admission['resources']=={'ALMs':5366,'registers':7492,'RAM_blocks':38,'DSP_blocks':30},'Unexpected resource totals')
    source_manifest_path=run/'candidate_source_manifest.json';source_manifest=read_json(source_manifest_path)
    for name,h in source_manifest.items():same_hash(repo/name,h)
    verification=read_json(args.verification_manifest);audit('verification_manifest',args.verification_manifest,admission['verification_manifest_sha256'])
    require(verification['status']=='passed' and verification['inputs_unchanged'] is True,'Verification not passed')
    for path,item in verification['inputs'].items():same_hash(path,item['sha256'])
    for name in ['rtl/fft/trecap_fft_stage.sv','rtl/fft/trecap_ifft256.sv','rtl/core/trecap_core_top.sv','rtl/top/trecap_core_bram_replay_top.sv','platform/de1soc/measurement/trecap_measurement_engine.sv']:
        wanted=digest(repo/name)
        require(any(p.replace('\\','/').endswith('/'+name) and v['sha256']==wanted for p,v in verification['inputs'].items()),'Verification did not test programmed source '+name)
    require(verification['profile_comparison']['rows_equal']==288 and verification['candidate_profile_comparison']['rows_equal']==576,'Expected final two-epoch profile verification')
    reference_path=repo/'artifacts/measurement/multitone/manifest.json';reference=read_json(reference_path)
    require((reference['input_samples'],reference['output_samples'],reference['frames'])==(1024,1536,9),'Reference geometry mismatch')
    same_hash(repo/'artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh',reference['input_sha256'])
    for name,h in reference['coefficient_sha256'].items():same_hash(repo/'artifacts/coefficients'/name,h)
    masked=next(c for c in reference['cases'] if c['name']=='masked')
    require(masked['threshold']==THRESHOLD and masked['cpp_oracle_output_mismatches']==0,'Masked reference invalid')
    same_hash(reference_path.parent/'y_masked.memh',masked['output_sha256'])
    profile_summary=None
    if args.profile_manifest:
        profile=read_json(args.profile_manifest);require(profile['status']=='PASS' and profile['cases']==40 and profile['checked_ifft_frames']==360 and profile['ifft_mismatches']==0,'Profile not passed')
        for name,h in profile['source_sha256'].items():
            candidates=[Path(p) for p,v in verification['inputs'].items() if p.replace('\\','/').endswith('/'+name) and v['sha256']==h]
            require(bool(candidates),'Profile source not anchored in verified inputs '+name);same_hash(candidates[0],h)
        directory=args.profile_manifest.parent;rows=read_csv(directory/'case_summary.csv')
        for signal in profile['signals']:same_hash(directory/signal['input_file'],signal['sha256'])
        for r in rows:require(int(r['ifft_mismatches'])==0,'Profile output mismatch');same_hash(directory/r['output_file'],r['output_sha256'])
        measured=next(r for r in rows if r['signal']=='measured_multitone' and int(r['threshold2'])==THRESHOLD)
        require((int(measured['b_complex_zero']),int(measured['total_butterflies']))==(4352,9216),'Unexpected measured zero opportunity')
        nonzero=[r for r in rows if r['signal']!='zero_control' and int(r['threshold2'])==THRESHOLD]
        require(len(nonzero)==4,'Missing threshold-matched profile workloads')
        profile_summary={'cases':40,'checked_ifft_frames':360,'ifft_mismatches':0,'measured_zero_b':4352,'measured_total_butterflies':9216,'measured_zero_b_percent':4352/9216*100,'fixed_threshold_nonzero_workload_min_percent':min(float(r['b_complex_zero_fraction'])*100 for r in nonzero),'fixed_threshold_nonzero_workload_max_percent':max(float(r['b_complex_zero_fraction'])*100 for r in nonzero),'scope':'Exact zero arithmetic opportunity, not skipped cycles or energy savings'}
        audit('profile_manifest',args.profile_manifest);audit('profile_case_summary',directory/'case_summary.csv')
        evidence['profile_case_summary']=directory/'case_summary.csv'
    fitted_summary=None
    if args.fitted_review:
        fitted=read_json(args.fitted_review);require(fitted['status']=='PASS_BOUNDED_FITTED_ADMISSION' and fitted['source_qsf_and_sof_unchanged'] is True,'Fitted review not passed')
        for path,h in fitted['source_and_report_sha256'].items():same_hash(path,h)
        fitted_summary={k:fitted[k] for k in ['status','minimum_clock50_slack_ns','resources','pins','effective_unused_pin_state'] if k in fitted}
        if 'fitted_structure' in fitted:
            fitted_summary['fitted_structure']={k:v for k,v in fitted['fitted_structure'].items() if k!='evidence_directory'}
            portable(json.dumps(fitted_summary))
        audit('fitted_review',args.fitted_review)
    evidence.update(capture_summary=capture_path,device_metadata=metadata_path,program_manifest=program_path,build_receipt=receipt_path,fit_summary=fit_path,timing_corners=corners_path,candidate_source_manifest=source_manifest_path,reference_manifest=reference_path,jtag_receipts=campaign_dir/'jtag.jsonl')
    for role,path in evidence.items():audit(role,path)
    return {'analysis':analysis,'trials':trials,'pairs':pairs,'stats':stats,'meter':meter,'program':program,'admission':admission,'resources':resources,'verification':verification,'profile':profile_summary,'fitted':fitted_summary,'evidence':evidence,'provenance':audited,'config':required_config,'events':event_doc,'reference_masked':masked,'final_idle':{'duration_ms':20000,'completed':True,'protocol':2,'fault_flags':0},'analyzer_sha256':analyzer_hash}

def direction(bounds):return 'includes zero' if bounds[0]<=0<=bounds[1] else ('is below zero' if bounds[1]<0 else 'is above zero')

def interpret(ci,timing):
    repeat=('The paired repeatability interval includes zero, so these six pairs do not resolve a consistent direction.' if ci[0]<=0<=ci[1] else 'The paired repeatability interval excludes zero for these six pairs.')
    if timing[0]<=0<=timing[1]:conditional='The conditional timing envelope includes zero; a direction of power change is not established after the stated timing allowances.'
    elif timing[1]<0:conditional='The conditional timing envelope is wholly below zero, supporting lower board-input power with isolation under the stated timing assumptions.'
    else:conditional='The conditional timing envelope is wholly above zero, supporting higher board-input power with isolation under the stated timing assumptions.'
    if not(ci[0]<=0<=ci[1]) and not(timing[0]<=0<=timing[1]) and ((ci[1]<0)!=(timing[1]<0)):
        conditional+=' The repeatability interval has the opposite sign; this disagreement requires investigation before a directional claim.'
    return repeat,conditional

def plots(data,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white','pdf.fonttype':42})
    def save(fig,name):
        fig.savefig(out/(name+'.png'),dpi=220);fig.savefig(out/(name+'.pdf'));plt.close(fig)
    pairs=data['pairs'];stats=data['stats'];mean=stats['mean']*1000;ci=[v*1000 for v in stats['paired_mean_95pct_t_interval']];timing=[statistics.mean(r[k] for r in pairs) for k in ('power_timing_lower_mW','power_timing_upper_mW')]
    fig,axes=plt.subplots(2,1,figsize=(9.5,7.4),layout='constrained',gridspec_kw={'height_ratios':[3,1.2]})
    ax=axes[0];ax.axhline(0,color='#777777',ls='--',lw=1);ax.scatter(range(6),[r['isolated_minus_baseline_mW'] for r in pairs],s=65,c=GOLD,edgecolors=MAROON,zorder=3)
    ax.vlines(6,ci[0],ci[1],color=MAROON,lw=2);ax.scatter([6],[mean],c=MAROON,marker='D',s=65)
    ax.set_xticks(range(7),['Pair '+str(p['pair_id']) for p in pairs]+['Mean\n95% t interval']);ax.set_ylabel('Isolated − baseline board power (mW)');ax.set_title('Paired board-power difference',loc='left',color=MAROON,fontweight='bold',fontsize=15);ax.grid(axis='y',alpha=.2)
    ax.set_xlabel('Six consecutive AB/BA pairs; interval describes repeatability only')
    ax=axes[1];ax.axvline(0,color='#777777',ls='--',lw=1);ax.axvspan(*timing,color=GOLD,alpha=.25);ax.hlines(0,*timing,color=MAROON,lw=3);ax.scatter([mean],[0],c=MAROON,marker='D');ax.set_yticks([]);ax.set_ylim(-1,1);ax.set_xlabel('Mean isolated − baseline difference (mW)');ax.set_title(f'Conditional timing envelope [{timing[0]:+.3f}, {timing[1]:+.3f}] mW: {direction(timing)}',loc='left',fontsize=11)
    fig.supxlabel('Timing envelope is not a confidence interval. Both panels exclude calibration uncertainty.',fontsize=9);save(fig,'paired_power_difference')
    fig,ax=plt.subplots(figsize=(11.5,5),layout='constrained');meter=data['meter'];ax.plot([(float(r['t_start_s'])+float(r['t_end_s']))/2 for r in meter],[float(r['power_W']) for r in meter],c=INK,lw=.75)
    colors={BASE:MAROON,CAND:GOLD}
    for i,t in enumerate(data['trials']):
        start,end=t['device_start_bounds_s'][1],t['device_end_bounds_s'][0];ax.axvspan(start,end,color=colors[t['condition']],alpha=.22);ax.text((start+end)/2,.98,str(i+1),ha='center',va='top',transform=ax.get_xaxis_transform(),fontsize=9)
    for name,label in [(BASE,'Masked baseline — isolation off'),(CAND,'Masked isolated — isolation on')]:ax.plot([],[],c=colors[name],lw=6,label=label)
    ax.set(xlabel='Meter session time (s)',ylabel='Whole-board DC-input power (W)');ax.set_title('Same-image isolation campaign',loc='left',color=MAROON,fontweight='bold',fontsize=15);ax.legend(loc='lower center',bbox_to_anchor=(.5,-.27),ncol=2,frameon=False);ax.grid(axis='y',alpha=.2);save(fig,'board_power_timeline')
    fig,axes=plt.subplots(2,1,figsize=(10.5,7.5),layout='constrained')
    for i,t in enumerate(data['trials']):
        color=colors[t['condition']];axes[0].vlines(i,*t['interior_board_power_timing_bounds_W'],color=color,lw=2);axes[0].scatter([i],[t['interior_board_power_W']],color=color,edgecolors=INK,s=40,zorder=3)
        axes[1].vlines(i,*t['board_energy_bounds_J'],color=color,lw=2);axes[1].scatter([i],[t['board_energy_interpolated_J']],color=color,edgecolors=INK,s=40,zorder=3)
    axes[0].set_title('Active power and complete-batch energy',loc='left',color=MAROON,fontweight='bold',fontsize=15);axes[0].set_ylabel('Interior board power (W)');axes[1].set_ylabel('Complete-batch board energy (J)')
    for ax in axes:ax.set_xticks(range(12),[str(i+1) for i in range(12)]);ax.grid(axis='y',alpha=.2)
    axes[1].set_xlabel('Measured trial (maroon: baseline; gold: isolated)');fig.supxlabel('Whiskers: conditional timing bounds. Dots: central estimates. Calibration uncertainty excluded.',fontsize=9);save(fig,'trial_power_energy')

def publish(args,data):
    out=args.out.resolve();require(not out.exists(),'Output exists; select a fresh directory');out.mkdir(parents=True);(out/'data').mkdir()
    trials=data['trials'];pairs=data['pairs'];stats=data['stats'];analysis=data['analysis'];evidence=data['evidence'];v=data['verification']
    conditions=[]
    for name in (BASE,CAND):
        ts=[t for t in trials if t['condition']==name];p=[t['interior_board_power_W'] for t in ts]
        conditions.append({'condition':name,'threshold2':THRESHOLD,'trials':len(ts),'mean_interior_board_power_W':statistics.mean(p),'trial_power_stdev_W':statistics.stdev(p),'mean_batch_energy_estimate_J':statistics.mean(t['board_energy_interpolated_J'] for t in ts),'mean_board_uJ_per_input_estimate':statistics.mean(t['board_J_per_input_interpolated']*1e6 for t in ts),'mean_interior_voltage_V':statistics.mean(t['interior_mean_bus_V'] for t in ts),'mean_interior_current_A':statistics.mean(t['interior_mean_current_A'] for t in ts)})
    rows=[]
    for t in trials:
        row={k:t[k] for k in ['trial_id','pair_id','condition','threshold2','epochs','cycles','duration_nominal_s','input_count','output_count','frame_count','mismatch_count','fault_flags','interior_board_power_W','board_energy_interpolated_J','board_J_per_input_interpolated']}
        for stem,key in [('interior_power_timing','interior_board_power_timing_bounds_W'),('batch_energy_timing','board_energy_bounds_J')]:row[stem+'_lower']=t[key][0];row[stem+'_upper']=t[key][1]
        rows.append(row)
    write_csv(out/'data/condition_summary.csv',conditions);write_csv(out/'data/trials.csv',rows);write_csv(out/'data/paired_power.csv',pairs);write_csv(out/'data/provenance.csv',data['provenance'])
    public={'meter_csv':'meter_samples.csv','clock_sync':'clock_sync.jsonl','trial_events':'trial_events.json'}
    for role,name in public.items():portable(evidence[role].read_text(encoding='utf-8-sig'));shutil.copyfile(evidence[role],out/'data'/name)
    local=json.loads(json.dumps(analysis));original_scope=local['scope'];local['scope']='Whole-board DC input; same programmed image and fixed threshold; masked IFFT isolation off versus on.'
    for role,name in public.items():local['sources'][role]['path']=name
    write_json(out/'data/measurement_analysis.json',local)
    verification_summary={k:v[k] for k in ['status','inputs_unchanged','vectors','stage_pass_lines','ifft_pass_lines','baseline_profile_pass_lines','candidate_profile_pass_lines','profile_comparison','candidate_profile_comparison']}
    write_json(out/'data/verification_summary.json',verification_summary)
    build_summary={'programmed_sof_sha256':data['program']['sof_sha256'].lower(),'status':data['admission']['status'],'fabric_clock_hz':50_000_000,'protocol':2,'timing_minima_ns':{k:data['admission']['fabric_min_'+k+'_slack_ns'] for k in ('setup','hold','recovery','removal')},'resources':data['resources'],'prior_image_resources':{'ALMs':5276,'registers':7451,'RAM_blocks':38,'DSP_blocks':30},'same_image_runtime_comparison_excludes_added_hardware_cost':True,'fabric_latches':0,'user_pins_verified':12,'final_idle':data['final_idle'],'fitted_review':data['fitted']}
    write_json(out/'data/build_verification.json',build_summary);write_json(out/'data/meter_configuration.json',data['config'])
    if data['profile']:
        write_json(out/'data/profile_summary.json',data['profile']);shutil.copyfile(evidence['profile_case_summary'],out/'data/profile_cases.csv');portable((out/'data/profile_cases.csv').read_text())
    plots(data,out)
    mean=stats['mean']*1000;ci=[x*1000 for x in stats['paired_mean_95pct_t_interval']];timing=[statistics.mean(p[k] for p in pairs) for k in ['power_timing_lower_mW','power_timing_upper_mW']];ei=[statistics.mean(p[k] for p in pairs) for k in ['energy_timing_lower_J','energy_timing_upper_J']];repeat,conditional=interpret(ci,timing)
    energy_text=('The mean paired batch-energy timing envelope includes zero; complete-batch energy savings are not established within those timing bounds.' if ei[0]<=0<=ei[1] else 'The mean paired batch-energy timing envelope is wholly '+('below' if ei[1]<0 else 'above')+' zero under the stated timing assumptions; calibration uncertainty remains excluded.')
    a=analysis['assumptions'];session=next(e['device_session'] for e in read_jsonl(evidence['clock_sync']) if e.get('event')=='sync_reply');reference=data['reference_masked']
    opportunity=('The measured workload has 4,352 exactly zero twiddle-multiplied operands among 9,216 accepted IFFT butterflies per epoch (47.22%). At the same threshold, the four nonzero profiled synthetic/measured workloads span '+f"{data['profile']['fixed_threshold_nonzero_workload_min_percent']:.2f}%–{data['profile']['fixed_threshold_nonzero_workload_max_percent']:.2f}%"+'; this is workload-dependent arithmetic opportunity, not an energy-saving percentage. The profile checked 360 frames across 40 signal/threshold cases against the independent oracle.' if data['profile'] else 'The separately verified measured-workload counters identify 4,352 zero twiddle-multiplied operands out of 9,216 IFFT butterflies (47.22%). Across the separately reported nonzero workloads at the same threshold, opportunities range from 1.18% to 83.82%. These counts describe arithmetic opportunity, not energy savings; the optional model profile is not included in this package.')
    values={'mean_mw':f'{mean:+.3f}','ci_lo':f'{ci[0]:+.3f}','ci_hi':f'{ci[1]:+.3f}','difference_percent':f'{stats["mean"]/conditions[0]["mean_interior_board_power_W"]*100:+.4f}','repeatability_text':repeat,'timing_text':conditional,'timing_lo':f'{timing[0]:+.3f}','timing_hi':f'{timing[1]:+.3f}','energy_lo':f'{ei[0]:+.4f}','energy_hi':f'{ei[1]:+.4f}','energy_text':energy_text,'condition_table':'\n'.join(f"| {r['condition']} | {r['mean_interior_board_power_W']:.6f} | {r['mean_batch_energy_estimate_J']:.4f} | {r['mean_board_uJ_per_input_estimate']:.4f} |" for r in conditions),'cycles':f"{trials[0]['cycles']:,}",'duration':f"{trials[0]['duration_nominal_s']:.8f}",'inputs':f"{sum(t['input_count'] for t in trials):,}",'outputs':f"{sum(t['output_count'] for t in trials):,}",'meter_rows':f"{len(data['meter']):,}",'sync_replies':str(analysis['matched_sync_replies']),'sync_rtt':f"{analysis['sync_roundtrip_max_s']:.6f}",'trim_s':str(a['active_interior_trim_s']),'device_ppm':str(a['device_clock_rate_bound_ppm']),'fabric_ppm':str(a['fabric_clock_rate_bound_ppm']),'sensor_guard_ms':f"{a['sensor_effective_time_guard_s']*1000:g}",'launch_guard':str(a['launch_crossing_guard_s']),'host_guard_ms':str(data['events']['clock_mapping']['tcl_timestamp_guard_ms']),'setup_slack':f"{data['admission']['fabric_min_setup_slack_ns']:.3f}",'hold_slack':f"{data['admission']['fabric_min_hold_slack_ns']:.3f}",'opportunity_text':opportunity,'rmse':f"{reference['rmse_full_stream_lsb']:.3f}",'max_error':str(reference['max_abs_error_lsb']),'suppressed_bins':str(reference['suppressed_bins']),'eligible_bins':str(reference['eligible_bins']),'sof_sha256':data['program']['sof_sha256'].lower(),'session':str(session)}
    template=args.template or Path(__file__).with_name('report_template.md');report=Template(template.read_text(encoding='utf-8')).substitute(values);(out/'README.md').write_text(portable(report),encoding='utf-8')
    publication={'schema':'ifft-zero-isolation-publication-1','status':'PASS_EVIDENCE_ADMISSION_AND_REPORT_GENERATION','date':'2026-09-25','conditions':[BASE,CAND],'threshold2':THRESHOLD,'trials':12,'pairs':6,'sof_sha256':data['program']['sof_sha256'].lower(),'paired_power_difference_mW':mean,'paired_repeatability_95pct_interval_mW':ci,'paired_mean_conditional_timing_envelope_mW':timing,'paired_mean_energy_conditional_timing_envelope_J':ei,'calibration_uncertainty_included':False,'runtime_cycle_counts_equal':True,'analyzer_sha256':data['analyzer_sha256'],'analysis_copy_transformation':{'source_paths':'Three source paths changed to data-directory-relative filenames','original_scope':original_scope,'replacement_scope':local['scope'],'numeric_results_and_source_hashes':'Unchanged'},'builder_sha256':digest(Path(__file__)),'template_sha256':digest(template),'files':{p.relative_to(out).as_posix():digest(p) for p in sorted(out.rglob('*')) if p.is_file()}}
    write_json(out/'publication_manifest.json',publication)
    return {'report':str(out/'README.md'),'trials':12,'pairs':6,'status':publication['status']}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['repo','run-root','analysis','csv','out','verification-manifest']:parser.add_argument('--'+name,type=Path,required=True)
    for name in ['profile-manifest','fitted-review','template']:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args();require(not args.out.exists(),'Output exists; choose a fresh directory')
    data=validate(args);print(json.dumps(publish(args,data)))
if __name__=='__main__':main()
