"""Export derived public verification evidence without modifying archived inputs.

Run with --workspace-root PATH --source-root PATH --output NEW_DIRECTORY.
Run --check DIRECTORY to recheck a portable export without the archive.
No network, hardware, subprocess, Git, or project code is executed.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import io
import json
import re

SECRET_PATTERNS={
    'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b'),
    'aws_key':re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'slack_token':re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
}
PERSONAL=re.compile(r'(?i)(?:[a-z]:[\\/]+Users[\\/]+|/(?:home|Users)/)[^\s"<>]+')
UUID=re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
MAC=re.compile(r'(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])')
PRIVATE_IP=re.compile(r'\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01])|169\.254)(?:\.\d{1,3}){2,3}\b')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def scan(text):
    bad=[name for name,p in SECRET_PATTERNS.items() if p.search(text)]
    if PERSONAL.search(text):bad.append('personal_path')
    if UUID.search(text):bad.append('runtime_uuid')
    if MAC.search(text):bad.append('network_mac')
    return bad
def check(output):
    output=Path(output);manifest=read(output/'manifest.json')
    assert manifest['schema']=='trecap-public-derived-evidence-v1'
    for row in manifest['exports']:
        p=output/row['path'];assert p.is_file() and sha(p)==row['export_sha256'],row['path']
        assert not scan(p.read_text(encoding='utf-8')),row['path']
    assert manifest['counts']['physical_epochs']==58
    with (output/'hardware/cases.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==58 and sum(int(x['Y_samples']) for x in rows)==22301696
    assert sum(int(x['frames']) for x in rows)==174058
    assert sum(int(x['packet_bytes']) for x in rows)==107200224
    assert all(x['Y_exact']=='True' and x['packet_exact']=='True' for x in rows)
    assert all(int(x['fault_mask'])==int(x['drops'])==0 for x in rows)
    assert len(read(output/'qualification/rtl_summary.json')['data']['fresh_suites'])==14
    assert not scan((output/'manifest.json').read_text())
    return {'status':'PASS_PUBLIC_EXPORT_INTEGRITY','files':len(manifest['exports']),
            'bytes':sum((output/r['path']).stat().st_size for r in manifest['exports']),
            'physical_cases':58,'RTL_suites':14,'manifest_sha256':sha(output/'manifest.json')}
def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace-root',type=Path);p.add_argument('--source-root',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--check',type=Path);a=p.parse_args()
    if a.check:print(json.dumps(check(a.check)));return
    assert a.workspace_root and a.source_root and a.output
    root=a.workspace_root.resolve();project=a.source_root.resolve();release=root/'work/verification_20261017_release';out=a.output.resolve()
    assert not out.exists(),'Use a new directory; immutable archive and prior exports are never overwritten.'
    assert not out.is_relative_to(release),'Never export over campaign evidence.'
    out.mkdir(parents=True)
    sources={};exports=[]
    def string(value):
        s=value.replace('\\','/')
        # Longest aliases first so ignored source-build outputs cannot look like maintained source.
        aliases=[(str(project/'build').replace('\\','/'),'archive:source-build'),
                 (str(root).replace('\\','/'),'archive:workspace'),
                 (str(project).replace('\\','/'),'repo:phase2')]
        for old,new in aliases:s=re.sub(re.escape(old),lambda m:new,s,flags=re.I)
        s=re.sub(r'(?i)\b[a-z]:/[^\s"<>;,\)]+',lambda m:'external-tool:'+m.group(0).rsplit('/',1)[-1],s)
        s=UUID.sub('RUNTIME_SESSION_REDACTED',s);s=MAC.sub('LAB_MAC_REDACTED',s)
        s=PRIVATE_IP.sub('LAB_ENDPOINT_REDACTED',s)
        return s
    def clean(value):
        if isinstance(value,str):return string(value)
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,dict):
            result={}
            for k,v in value.items():
                nk=string(k)
                assert nk not in result,'Sanitized key collision; export must be reviewed.'
                result[nk]=clean(v)
            return result
        return value
    def source(path):
        path=Path(path).resolve();h=sha(path);sources[str(path)]=h
        return {'artifact_id':string(str(path)),'original_sha256':h}
    def emit(rel,content,source_rows,kind):
        assert not scan(content),(rel,scan(content))
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,encoding='utf-8',newline='\n')
        exports.append({'path':rel,'kind':kind,'bytes':target.stat().st_size,
                        'export_sha256':sha(target),'original_sources':source_rows,
                        'derived_export':True})
    def js(rel,obj,paths):
        rows=[source(x) for x in paths]
        wrapped={'derived_export':True,'source_artifacts':rows,
                 'transformation':'Personal absolute paths are replaced by documented artifact IDs; runtime UUID/MAC/private endpoints are removed. Numeric observations and original artifact hashes are preserved.',
                 'data':clean(obj)}
        emit(rel,json.dumps(wrapped,indent=2)+'\n',rows,'derived_JSON')
    def copyjson(src,dst):
        path=release/src;js(dst,read(path),[path])
    # Positive and intentional-negative checks qualify the export scanner itself.
    assert scan('ghp_'+'X'*36)==['github_token']
    assert scan('-----BEGIN '+'PRIVATE KEY-----')==['private_key']
    assert scan('live_monitor_result.json')==[]
    assert not scan(string(str(root/'work/example.json')))
    for src,dst in [
        ('assurance/final_disposition.json','acceptance/final_disposition.json'),
        ('assurance/original_requirement_dispositions.json','acceptance/original_requirement_dispositions.json'),
        ('assurance/release_plan_revision03.json','acceptance/registered_plan.json'),
        ('reference/summary.json','qualification/reference_summary.json'),
        ('reference/arithmetic_attempt01/report.json','qualification/reference_arithmetic.json'),
        ('reference/corner_attempt01/report.json','qualification/reference_corners.json'),
        ('rtl/summary.json','qualification/rtl_summary.json'),
        ('rtl/coverage.json','coverage/rtl_coverage.json'),
        ('software/findings.json','qualification/host_tests.json'),
        ('native/findings.json','qualification/native_tests.json'),
        ('assurance/clock_reset_review.json','qualification/clock_reset_review.json'),
        ('assurance/rtl_audit01/summary.json','assurance/full_RTL_audit.json'),
        ('figures/hardware03/flute_metrics.json','metrics/flute_metrics.json')]:copyjson(src,dst)
    rtl=read(release/'rtl/summary.json')
    for suite in rtl['fresh_suites']:
        path=root/suite['report'];assert sha(path)==suite['sha256']
        js('qualification/rtl_suites/'+suite['name']+'.json',read(path),[path])
    source_manifest=root/'outputs/trecap_stream8_v01/build01/source_manifest.json'
    js('source_bindings/fitted_source_manifest.json',read(source_manifest),[source_manifest])
    auditpath=release/'assurance/audit01/summary.json';audit=read(auditpath)
    brief={k:v for k,v in audit.items() if k not in ('hash_checks','cases','quality')}
    js('hardware/audit_summary.json',brief,[auditpath])
    js('hardware/case_audit_details.json',audit['cases'],[auditpath])
    js('metrics/monitor_quality.json',audit['quality'],[auditpath])
    indexpath=release/'hardware/captures01/index.json';index=read(indexpath)
    rows=[];registers=[]
    for c in index['cases']:
        reg=c['final_register_snapshot']['registers'];folder=Path(c['folder'])
        actual_y=source(folder/'y.i32le');actual_wire=source(folder/'sparse.tsp1');final_receipt=source(folder/'final.json')
        assert actual_y['original_sha256']==c['y_expected_sha256']
        assert actual_wire['original_sha256']==c['wire_expected_sha256']
        rows.append({'capture_id':c['capture_id'],'record_id':c['record_id'],'category':c['category'],
                     'threshold':c['threshold'],'trial':c['trial'],'epoch':c['epoch'],'input_samples':reg['0x024'],
                     'Y_samples':c['y_samples'],'frames':reg['0x054'],'packet_bytes':c['wire_bytes'],
                     'Y_exact':c['y_exact'],'packet_exact':c['wire_exact'],'fault_mask':reg['0x00c'],'drops':reg['0x050'],
                     'input_fifo':reg['0x030'],'Y_fifo':reg['0x034'],'packet_fifo':reg['0x038'],
                     'Y_read':reg['0x068'],'packet_words_read':reg['0x064'],'processed_input':reg['0x058'],
                     'elapsed_cycles_including_host_stalls':reg['0x04c'],**c['timing'],
                     'input_sha256':c['input_sha256'],'Y_sha256':actual_y['original_sha256'],
                     'packet_sha256':actual_wire['original_sha256'],'capture_receipt_sha256':c['capture_receipt_sha256'],
                     'raw_final_receipt_sha256':final_receipt['original_sha256']})
        registers.append({'capture_id':c['capture_id'],'raw_final_receipt':final_receipt,
                          'observed_final_registers':c['final_register_snapshot']})
    assert len(rows)==58
    buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    emit('hardware/cases.csv',buf.getvalue(),[source(indexpath)],'derived_CSV_exact_case_metrics')
    js('hardware/final_registers.json',registers,[indexpath])
    js('hardware/capture_summary.json',{k:v for k,v in index.items() if k not in ('cases','input_bindings')},[indexpath])
    attribution_path=root/'outputs/trecap_monitor_board_v01/inputs01/index.json';inputs=read(attribution_path)
    attribution=[]
    for record in inputs['records']:
        src=record.get('source',{})
        if record.get('kind')=='natural':attribution.append({'record_id':record['id'],'source':src})
    js('data_provenance/monitor_attribution.json',attribution,[attribution_path])
    js('data_provenance/dataset_terms.json',{
        'reviewed_utc_date':'2026-10-17',
        'flute':{'attribution':'Lawrence Fritts / University of Iowa Musical Instrument Samples',
                 'input_source_url':'https://theremin.music.uiowa.edu/sound%20files/MIS/Woodwinds/flute/Flute.nonvib.mf.C5B5.aiff',
                 'terms_url':'https://theremin.music.uiowa.edu/MIS.html',
                 'observed_terms':'The official page permits downloading and using the samples for projects without restrictions.',
                 'input_preprocessing':'First8seconds; frozen48kHz signed12 input. Input SHA256 is retained in hardware/cases.csv.',
                 'raw_audio_in_this_package':False},
        'ESC50':{'terms_url':'https://github.com/karolpiczak/ESC-50/blob/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/README.md',
                 'observed_terms':'The corpus is CC BY-NC; ESC-10 is a CC BY subset. Selected original-source clip labels are separate attribution facts, not a replacement license for the corpus.',
                 'raw_audio_in_this_package':False}},[attribution_path,root/'work/trecap_audio_listen_v01/make_demo.py'])
    # Raw VCD state changes are preserved; only nonfunctional header metadata changes.
    for src,dst in [('figures/traces02/full_stream_first_window.vcd','waveforms/startup.vcd'),
                    ('rtl/reset_waveform/reset_recovery.vcd','waveforms/reset_recovery.vcd'),
                    ('rtl/final_y_completion_metrics_attempt02/final_y_stall.vcd','waveforms/final_y_stall.vcd')]:
        path=release/src;text=path.read_text()
        transformed=re.sub(r'\$(date|version)\b.*?\$end',lambda m:'$'+m.group(1)+'\nPublic derived trace; original metadata and SHA retained in manifest.\n$end',text,flags=re.S)
        assert text.split('$enddefinitions $end',1)[1]==transformed.split('$enddefinitions $end',1)[1]
        emit(dst,transformed,[source(path)],'derived_VCD_metadata_only')
    readme='''# Published verification evidence

This directory is a derived public evidence export for the registered TSH2 finite-file campaign. It contains 58 physical case records, all 14 fresh RTL suite receipts, observed event coverage, reference qualification, source identities, original requirement dispositions and representative simulation waveforms.

Every manifest row records original artifact SHA256 values separately from the SHA256 of the exported bytes. Exported JSON is wrapped under `data`; it is not a byte-identical copy of an original receipt. Personal paths become `archive:workspace/...`, `archive:source-build/...`, `repo:phase2/...` or `external-tool:<filename>` identifiers. Archive identifiers describe retained local evidence, not files promised by this repository. Runtime boot UUIDs, MACs and private endpoint addresses are removed. Numeric observations, test names, thresholds, counts, timestamps, hashes and failed-attempt dispositions remain intact. A filename beginning `live_` is not considered a credential.

The waveform files preserve every state-change record. Only `$date` and `$version` header metadata were normalized. These are simulation traces at a 10 ns testbench clock; they do not measure physical board latency. Reset plots cover representative cancellation windows; exact restart scoreboards are recorded separately.

Raw UART transcripts, board host inventories, full audio/packet captures, vendor-generated IP, compiled binaries, SDKs and simulator databases are not included. The immutable local archive retains them. This package provides auditability of reported results and a compact case ledger, not every raw sample needed to independently rerun the 58-capture audit. The separate portable DV runner supplies public synthetic tests.

The four natural monitor records retain their source attribution and source-license labels from the frozen ESC-50 manifest. [ESC-50's pinned README](https://github.com/karolpiczak/ESC-50/blob/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/README.md) labels the corpus CC BY-NC and the ESC-10 subset CC BY. Selected original-source attribution labels do not relicense the whole corpus. The flute source is Lawrence Fritts / University of Iowa Musical Instrument Samples; its [official page](https://theremin.music.uiowa.edu/MIS.html) permits downloading and using samples for projects without restrictions. Its exact source URL, preprocessing and input SHA256 are retained. No raw audio is redistributed in this compact package. Statistics do not imply a new held-out dataset, machine-learning training, diagnostic accuracy, energy savings or system speedup.

Run `python export_public_evidence.py --check PATH_TO_THIS_DIRECTORY` to verify exported hashes, field totals, all 58 cases and credential/path safeguards without the private archive. Re-export requires `--workspace-root`, `--source-root` and a new `--output` directory containing the archived campaign. The exporter performs only local file reads/writes and never operates hardware or Git.
'''
    emit('README.md',readme,[],'publication_scope_document')
    script=Path(__file__).resolve();emit('export_public_evidence.py',script.read_text(),[{'artifact_id':'publication:export_public_evidence.py','original_sha256':sha(script)}],'export_tool')
    assert all(sha(Path(p))==h for p,h in sources.items()),'Original evidence changed during export.'
    manifest={'schema':'trecap-public-derived-evidence-v1','status':'DERIVED_EXPORT_NOT_NEW_EXECUTION','originals_unchanged':True,
              'counts':{'physical_epochs':58,'Y_samples':22301696,'frames':174058,'packet_bytes':107200224,'RTL_suites':14},
              'exports':exports,'original_files_checked_unchanged':len(sources),
              'hardware_access':False,'network_access':False,'Git_mutation':False,
              'scanner_selftests':['Synthetic GitHub-token marker rejected','Synthetic private-key marker rejected','Benign live_monitor filename accepted','Personal workspace path normalized'],
              'limitations':['This is derived documentation/data, not a new simulation or board run.','No raw audio or vendor source redistributed.','Public scalar metrics do not establish all original architecture requirements.']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    result=check(out)
    print(json.dumps(result))
if __name__=='__main__':main()
