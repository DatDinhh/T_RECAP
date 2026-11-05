"""Build report tables from completed fresh receipts without rerunning tests."""
from pathlib import Path
import argparse
import hashlib
import json
import re

HERE=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,action='append',required=True)
    parser.add_argument('--host-dir',type=Path,required=True)
    args=parser.parse_args()
    layers=[]
    by_suite={}
    for path in args.report:
        data=json.loads(path.read_text())
        assert data['status']=='PASS' and data['hardware_used'] is False
        for name,expected in data['artifacts'].items():
            assert sha(path.parent/name)==expected, name
        layer={k:data[k] for k in ['suite','status','source_id','hardware_used','package_manifest_sha256','observations','tools'] if k in data}
        layer.update(report_sha256=sha(path),published_evidence='phase2/verification/rf_iq/evidence/'+data['suite']+'/report.json')
        if 'negative_control' in data: layer['negative_control']=data['negative_control']
        if 'waveform' in data: layer['waveform']=data['waveform']
        layers.append(layer)
        by_suite[data['suite']]=layer
    assert set(by_suite)=={'adapter','limit','wrapper','integration','admission'}
    host={}
    for name in ['native_mock.json','input_tests.json']:
        path=args.host_dir/name
        obj=json.loads(path.read_text())
        assert obj['status'].startswith('PASS') and obj['hardware_access'] is False
        host[name]={'original_sha256':sha(path),'result':obj}
    host_sources=[]
    profile=HERE.parents[2]/'profiles/trf1/board/host'
    for line in (args.host_dir/'source_sha256.txt').read_text().splitlines():
        expected,rawpath=line.split('  ',1)
        name=rawpath.rsplit('/',1)[-1]
        assert sha(profile/name)==expected
        host_sources.append({'published_path':'phase2/profiles/trf1/board/host/'+name,'sha256':expected})
    host['sources']=host_sources
    host['original_source_list_sha256']=sha(args.host_dir/'source_sha256.txt')
    host['runtime']='Native Linux process under WSL with undefined-behavior sanitizer, no MMIO mapping or board access'
    package_evidence=HERE.parents[2]/'verification/rf_iq/evidence'
    reference=json.loads((package_evidence/'reference_check.json').read_text())
    qualification=json.loads((package_evidence/'package_qualification.json').read_text())
    assert reference['status']=='PASS' and qualification['status']=='PASS'
    vcd=by_suite['adapter']['waveform']['public_sha256']
    result={'schema':'trecap-rf-fresh-report-projection-v1','artifact_kind':'sanitized_projection_of_fresh_execution_receipts',
            'status':'PASS','hardware_used':False,'layers':layers,'adapter_vcd_sha256':vcd,'native_host_checks':host,
            'reference_check':{k:reference[k] for k in ['status','fixtures','samples','coefficients_checked','reference_sha256']},
            'reference_check_sha256':sha(package_evidence/'reference_check.json'),
            'package_qualification':qualification,'package_qualification_sha256':sha(package_evidence/'package_qualification.json'),
            'limits':['Simulation results do not imply a fresh FPGA fit or physical run.',
                      'The fresh RF suite has no formal proof or UVM coverage claim.',
                      'Native host mocks do not exercise physical HPS bus timing or ARM execution.']}
    dest=HERE/'evidence/fresh_projection.json'
    dest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    def total(suite,key):
        return sum(row.get('counters',{}).get(key,0) for row in by_suite[suite]['observations'])
    def first(suite):
        return by_suite[suite]['observations'][0].get('counters',{})
    adapter=by_suite['adapter']
    limit=first('limit')
    wrapper=first('wrapper')
    integration=first('integration')
    admission=first('admission')
    rows=[('Adapter',f"{len(adapter['observations'])} seeds, {total('adapter','cases'):,} transactions, {total('adapter','samples'):,} exact samples"),
          ('Maximum record',f"{limit.get('samples',0):,} exact samples and signed clipping/rounding checks"),
          ('Finite wrapper',f"{wrapper.get('completed',0)} completed, {wrapper.get('aborted',0)} aborted, {wrapper.get('checked_samples',0):,} sample checks"),
          ('Actual-core MMIO',f"{integration.get('epochs',0)} epochs, {integration.get('checks',0):,} checks, {integration.get('negatives',0)} fault/abort cases"),
          ('Admission and recovery',f"{admission.get('checks',0):,} checks over {admission.get('cycles',0):,} cycles"),
          ('Native host tests',f"{host['native_mock.json']['result']['tests']} register-mock checks, {host['input_tests.json']['result']['file_cases']} file cases and {host['input_tests.json']['result']['numeric_cases']} numeric cases")]
    text='The fresh publication run passed all five RTL layers. Its adapter negative control also failed as intended when one expected value was deliberately corrupted. Native host tests ran separately under the undefined-behavior sanitizer. No board was accessed by this refresh.\n\n'
    text+='\\begin{table}[H]\\centering\\small\n\\caption{Fresh publication verification. See the machine-readable projection for exact receipt identities.}\n'
    text+='\\begin{tabularx}{\\linewidth}{@{}p{1.65in}Y@{}}\\toprule\nLayer & Executed result \\\\ \\midrule\n'
    text+='\n'.join(label+' & '+value+' \\\\' for label,value in rows)
    text+='\n\\bottomrule\\end{tabularx}\n\\end{table}\n\n'
    text+='The fresh integration cases extend the prior matrix with a one-pair minimum record, legal gains 0 and 2, and the maximum legal 56-bit threshold. The admission extension exercises pending FIFO-prefetch recovery. These are specific executed cases, not an exhaustive cross-product claim.\n'
    text+=f"Independent regeneration checked {reference['fixtures']} numerical fixtures, {reference['samples']:,} samples and all {reference['coefficients_checked']} FIR coefficients. The package checker rejected all {qualification['negative_controls']} deliberately corrupted source or fixture variants.\n"
    (HERE/'fresh_results.tex').write_text(text,encoding='utf-8')
    print(json.dumps({'status':'PASS','layers':len(layers),'projection':str(dest.name),'rows':rows}))


if __name__=='__main__':
    main()
