"""Execute one prepared raw-IQ package on an already admitted TRF1 board."""
from pathlib import Path
import argparse
import json
import re
from board_control import ROOT, HERE, OUT, HARDWARE, BB, read, save, sha, need, uart, boot, body, upload, download, now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', type=Path, required=True)
    ap.add_argument('--program', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    package = read(a.package)
    program = read(a.program)
    need(package['status'] == 'PREPARED_NOT_EXECUTED' and package['no_gold_on_board'], 'Raw-only prepared package')
    need(program['status'] == 'PASS_VOLATILE_PROGRAMMED_PENDING_LINUX_RUNTIME', 'Qualified image was programmed')
    need(program['source_id'] == package['source_id'], 'Package/program SOURCE_ID agreement')
    need(package['boot_id'] == boot(read(HARDWARE/'07_runtime_receipt.json')), 'Current admitted boot')
    need(read(HARDWARE/'08_network_receipt.json')['status'] == 'PASS', 'Network admitted')
    need(sha(package['archive']) == package['archive_sha256'], 'Prepared transfer bytes unchanged')
    network = read(HARDWARE/'pc_network.json')
    need(any(r['IPAddress']=='169.254.196.127' and r['PrefixLength']==16 and r['AddressState']==4 for r in network['addresses']), 'Existing direct-link PC address')
    receipt = {'status':'STARTED', 'started_utc':now(), 'source_id':program['source_id'], 'sof_sha256':program['sof_sha256'],
               'boot_id':package['boot_id'], 'hardware_execution':True, 'raw_cu8_sent':False, 'gold_uploaded':False,
               'transfer_attempted':False, 'raw_cu8_upload_verified':False,
               'package_manifest':str(a.package.resolve()),'package_manifest_sha256':sha(a.package),
               'program_receipt':str(a.program.resolve()),'program_receipt_sha256':sha(a.program), 'completed_cases':[]}
    save(a.out/'receipt.json', receipt)
    try:
        receipt['transfer_attempted']=True
        save(a.out/'receipt.json', receipt)
        upload(a.out, Path(package['archive']), package['target'], package['boot_id'])
        receipt.update(raw_cu8_sent=True,raw_cu8_upload_verified=True)
        save(a.out/'receipt.json', receipt)
        from board_control import command
        for label, step in [('initialize',package['initialize'])]+[(c['name'],c) for c in package['cases']]:
            result=uart(a.out,label,[command(step['command'], label, step['uart_timeout_seconds'])])
            if label != 'initialize':
                receipt['completed_cases'].append(label)
                save(a.out/'receipt.json', receipt)
            print(json.dumps({'stage':label,'status':result['status']}),flush=True)
        packed = uart(a.out,'pack',[command(package['pack']['command'],'pack',package['pack']['uart_timeout_seconds'])])
        hashes = re.findall(r'(?m)^([0-9a-f]{64})  '+re.escape(package['result_archive'])+r'\r?$',body(packed))
        need(len(hashes)==1,'One observed RAM result archive SHA')
        captured = download(a.out,package['result_archive'],hashes[0],package['result_files'])
        lines=(captured/'RESULTS.sha256').read_text().splitlines()
        names=set()
        for line in lines:
            match=re.fullmatch(r'([a-f0-9]{64})  ([a-zA-Z0-9_.-]+)',line)
            need(match is not None,'Strict capture hash manifest')
            digest,name=match.groups()
            need(name not in names and sha(captured/name)==digest,'Unique matching captured file SHA')
            names.add(name)
        need(names==set(package['result_files'])-{'RESULTS.sha256'},'Complete result hash coverage')
        need((captured/'initialize.rc').read_text().strip()=='0','Initialized successfully')
        for name in ['boot_before.txt','boot_after.txt']+[c['name']+'.boot_after.txt' for c in package['cases']]:
            need((captured/name).read_text().strip()==package['boot_id'],'Same boot throughout')
        for name in ['system_before.json','system_after.json']+[c['name']+'.system_'+side+'.json' for c in package['cases'] for side in ['before','after']]:
            sys=read(captured/name)
            need(sys['status']=='PASS_HPS_SYSTEM_STATE_ONLY' and sys['bridge_reset']==5 and sys['manager_mode']==4,'Admitted system state throughout')
        for c in package['cases']:
            name=c['name']
            need((captured/(name+'.rc')).read_text().strip()=='0' and (captured/(name+'.stderr')).stat().st_size==0,'Successful client exit')
            shell=read(captured/(name+'.case.json'))
            need(shell['status']=='PASS_CAPTURE_PENDING_PC_VALIDATION' and shell['source_id']==program['source_id'] and shell['boot_id']==package['boot_id'],'Bound case shell receipt')
            need(all(shell[k]==0 for k in ['before_probe_rc','client_rc','after_probe_rc','boot_after_rc']),'Successful bracketed case checks')
            client=read(captured/(name+'.json'))
            need(client['source_id']==program['source_id'] and client['boot_id']==package['boot_id'],'Bound client receipt')
        need(boot(read(a.out/'final_idle.json'))==package['boot_id'],'Final board boot unchanged')
        receipt.update(status='PASS_FIVE_HARDWARE_CAPTURES_PENDING_NUMERICAL_VALIDATION',captured_directory=str(captured),
                       archive_sha256=hashes[0],result_manifest_sha256=sha(captured/'RESULTS.sha256'))
    except Exception as exc:
        receipt.update(status='FAIL_OR_INCOMPLETE_NO_AUTOMATIC_MMIO_RECOVERY',error=str(exc))
        raise
    finally:
        receipt['ended_utc']=now()
        receipt['evidence_sha256']={str(p):sha(p) for p in a.out.glob('*.json') if p.name!='receipt.json'}
        save(a.out/'receipt.json',receipt)
    print(json.dumps({'status':receipt['status'],'captured_directory':receipt['captured_directory']}),flush=True)


if __name__=='__main__': main()
