#!/usr/bin/env python3
"""Normalize proof receipts for publication, preserving hashes of original bytes."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--attempt',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repo-root',type=Path,required=True)
    p.add_argument('--tool-root',type=Path,required=True)
    p.add_argument('--history',type=Path,action='append',default=[])
    args=p.parse_args()
    attempt=args.attempt.resolve()
    destination=args.output.resolve()
    destination.mkdir(parents=True,exist_ok=False)
    replacements=[(str(attempt.parent),'archive:formal/attempts'),(str(args.tool_root.resolve()),'external-tool:oss-cad-suite'),(str(args.repo_root.resolve()),'repo:phase2')]
    entries=[]

    def emit(source,relative,artifact_id):
        raw=source.read_bytes()
        text=raw.decode('utf-8')
        for old,new in replacements:
            text=text.replace(old,new).replace(old.replace('\\','/'),new)
        exported=text.replace('\r\n','\n').encode('utf-8')
        target=destination/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(exported)
        entries.append({'path':relative,'source_artifact_id':artifact_id,'original_sha256':sha(raw),'sha256':sha(exported),'bytes':len(exported),'transformation':'UTF-8 LF; invocation-specific absolute roots replaced by portable aliases; all results and trace values preserved'})

    files=[attempt/name for name in ['summary.json','tool_identity.json','input_identity.json']]
    summary=json.loads((attempt/'summary.json').read_text())
    for result in summary['results']:
        directory=attempt/result['case']['id']
        files += [directory/name for name in ['receipt.json','case.sby','stdout.txt','stderr.txt','result/status','result/logfile.txt','result/PASS','result/FAIL'] if (directory/name).exists()]
        files += sorted((directory/'result').glob('engine_*/*.txt'))
        files += sorted((directory/'result').glob('engine_*/*.vcd'))
    for file in files:
        relative=file.relative_to(attempt).as_posix()
        emit(file,relative,'archive:formal/attempts/'+attempt.name+'/'+relative)
    history=[]
    for old in args.history:
        old=old.resolve()
        candidates=[]
        if (old/'summary.json').exists():
            old_summary=json.loads((old/'summary.json').read_text())
            candidates.append(old/'summary.json')
            for result in old_summary['results']:
                if result['acceptance'] != 'PASS':
                    for name in ['receipt.json','stdout.txt','stderr.txt']:
                        candidates.append(old/result['case']['id']/name)
                    candidates += sorted((old/result['case']['id']/'result').glob('engine_*/*.vcd'))
            history.append({'attempt':old.name,'status':old_summary['status'],'executed':old_summary['executed'],'requested':old_summary['requested'],'summary_original_sha256':sha((old/'summary.json').read_bytes())})
        elif (old/'receipt.json').exists():
            candidates=[old/'receipt.json',old/'stdout.txt',old/'stderr.txt']
            history.append({'attempt':old.name,'receipt_original_sha256':sha((old/'receipt.json').read_bytes())})
        for file in candidates:
            relative='history/'+old.name+'/'+file.relative_to(old).as_posix()
            emit(file,relative,'archive:formal/attempts/'+old.name+'/'+file.relative_to(old).as_posix())
    index={'schema':'trecap-normalized-formal-evidence-v1','authoritative_attempt':attempt.name,'status':summary['status'],'original_summary_sha256':sha((attempt/'summary.json').read_bytes()),'path_aliases':{'archive:formal/attempts':'private immutable local run receipts','external-tool:oss-cad-suite':'separately obtained verified tool suite','repo:phase2':'source repository phase2 root'},'not_original_bytes':'Original hashes and derived export hashes are separately recorded; normalization does not constitute a new proof run','superseded_attempts':history,'files':entries}
    (destination/'index.json').write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','exported_files':len(entries),'index_sha256':sha((destination/'index.json').read_bytes())}))


if __name__=='__main__': main()
