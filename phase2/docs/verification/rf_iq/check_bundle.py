"""Check the report's published artifacts without tools, network or hardware."""
from pathlib import Path
import argparse
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ATLAS = HERE.parent.parent/'architecture/rf_iq'
VIEWS = ['01-system','02-signal-representation','03-adapter-hardware','04-finite-file-completion',
         '05-waveform-and-spectral-outputs','06-host-and-registers','07-state-and-backpressure','08-clock-reset-verification']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal',action='store_true',help='Authoring step: refresh the manifest after review')
    args=parser.parse_args()
    files=['README.md','rf_verification_supplement.tex','rf_verification_supplement.pdf','fresh_results.tex',
           'check_bundle.py','export_historical.py','make_figures.py','make_fresh_projection.py',
           'evidence/historical_projection.json','evidence/fresh_projection.json',
           'evidence/waveform_source.json','evidence/waveform_trace.csv','evidence/historical_figure_source.json',
           'figures/rtl_backpressure.png','figures/rtl_backpressure.pdf','figures/historical_tradeoff.png','figures/historical_tradeoff.pdf',
           'figures/system_boundary.png','figures/system_boundary.pdf','figures/adapter_schedule.png','figures/adapter_schedule.pdf']
    files += ['../../architecture/rf_iq/'+v+'.png' for v in VIEWS]
    manifest=HERE/'bundle_manifest.json'
    if args.seal:
        data={'schema':'trecap-rf-report-bundle-v1','purpose':'Published artifact consistency, not a signature or a hardware attestation',
              'files':{name:sha(HERE/name) for name in files}}
        manifest.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    data=json.loads(manifest.read_text())
    assert set(files)==set(data['files']), 'Manifest inventory differs from required report artifacts'
    for name,expected in data['files'].items():
        assert sha(HERE/name)==expected, 'Bundle mismatch: '+name
    history=json.loads((HERE/'evidence/historical_projection.json').read_text())
    fresh=json.loads((HERE/'evidence/fresh_projection.json').read_text())
    waveform=json.loads((HERE/'evidence/waveform_source.json').read_text())
    assert history['artifact_kind']=='sanitized_projection_not_raw_capture'
    assert history['local_hash_audit']['status']=='PASS'
    assert history['local_hash_audit']['checks']==len(history['local_hash_audit']['records'])
    assert all(row['matched'] for row in history['local_hash_audit']['records'])
    assert len(history['physical_run']['cases'])==5
    assert all(row['y_bit_exact'] and row['tsp1_bit_exact'] for row in history['physical_run']['cases'])
    assert fresh['status']=='PASS' and fresh['hardware_used'] is False
    assert all(row['status']=='PASS' for row in fresh['layers'])
    assert waveform['trace_sha256']==sha(HERE/'evidence/waveform_trace.csv')
    assert waveform['source_vcd_sha256']==fresh['adapter_vcd_sha256']
    for name in ['README.md','rf_verification_supplement.tex','fresh_results.tex']:
        text=(HERE/name).read_text(encoding='utf-8')
        assert not any(c in text for c in ['\u2013','\u2014']), 'Non-ASCII dash in '+name
        assert not any(phrase in text for phrase in ['layout-stage draft','Final receipt pending','undergoing final review']), 'Unfinished draft in '+name
    for name in ['evidence/historical_projection.json','evidence/fresh_projection.json']:
        text=(HERE/name).read_text()
        assert not re.search(r'(?<![A-Za-z])[A-Za-z]:[\\/]',text), 'Absolute host path in '+name
    print(json.dumps({'status':'PASS','published_files_checked':len(files),'fresh_layers':len(fresh['layers']),
                      'historical_local_hash_checks':history['local_hash_audit']['checks'],
                      'hardware_access':False}))


if __name__=='__main__':
    main()
