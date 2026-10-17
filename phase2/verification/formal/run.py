#!/usr/bin/env python3
"""Run source-admitted local RTL proofs. Requires a separately installed OSS CAD Suite."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_sources(repo):
    admission = read(HERE / "admission.json")
    source_names=[s['path'] for s in admission['sources']]
    copy_names=[s['copy_name'] for s in admission['sources']]
    if len(set(source_names))!=len(source_names) or len(set(copy_names))!=len(copy_names):
        raise ValueError('Duplicate admitted source or copy name')
    for item in admission["sources"]:
        rel=Path(item['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Unsafe admitted source path')
        file = repo / item["path"]
        if sha(file) != item["sha256"]:
            raise ValueError("Source admission mismatch: " + item["path"])
    return admission


def check_package(repo):
    admission = check_sources(repo)
    manifest = read(HERE / "package_manifest.json")
    files = manifest["files"]
    names = [item["path"] for item in files]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate package file")
    cases=read(HERE/'cases.json')['cases']
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Duplicate case identity')
    required={'run.py','README.md','cases.json','admission.json','toolchain.json','export_evidence.py','evidence/index.json'}
    required |= {'harness/'+c['harness'] for c in cases}
    index=read(HERE/'evidence/index.json')
    required |= {'evidence/'+e['path'] for e in index['files']}
    if set(names)!=required:
        raise ValueError('Package manifest must bind the complete expected source and evidence inventory')
    for item in files:
        rel = Path(item["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Unsafe package path")
        file = HERE / rel
        if sha(file) != item["sha256"] or file.stat().st_size != item["bytes"]:
            raise ValueError("Package identity mismatch: " + item["path"])
    for item in index['files']:
        file=HERE/'evidence'/item['path']
        if sha(file)!=item['sha256'] or file.stat().st_size!=item['bytes']:
            raise ValueError('Derived evidence index mismatch: '+item['path'])
    summary=read(HERE/'evidence/summary.json')
    if summary['status']!='PASS' or summary['executed']!=len(cases) or summary['requested']!=len(cases):
        raise ValueError('Authoritative campaign is incomplete or not accepted')
    if [r['case'] for r in summary['results']]!=cases:
        raise ValueError('Executed case definitions do not match this package')
    exports={item['path']:item for item in index['files']}
    for record in summary['results']:
        case=record['case']
        expected=case.get('expected','PASS')
        if record['acceptance']!='PASS' or record['observed_status']!=expected or record['expected_status']!=expected or record['host_deadline_exceeded'] or not record['input_identity_unchanged']:
            raise ValueError('Case outcome or deadline mismatch: '+case['id'])
        if (expected=='PASS' and record['exit_code']!=0) or (expected=='FAIL' and record['exit_code']==0):
            raise ValueError('Case exit code mismatch: '+case['id'])
        log=(HERE/'evidence'/case['id']/'stdout.txt').read_text(encoding='utf-8')
        if expected=='FAIL':
            signature=case['expected_assertion']
            if not record['negative_signature_matched'] or not record['traces'] or not any(signature in line and ('failed assertion' in line.lower() or 'assert failed' in line.lower()) for line in log.splitlines()):
                raise ValueError('Intended negative control not evidenced: '+case['id'])
        elif case['mode']=='prove':
            signature='Property proved' if case['engine']=='abc pdr' else 'successful proof by k-induction'
            if signature not in log:
                raise ValueError('Proof completion signature missing: '+case['id'])
        elif case['mode']=='cover' and not record['traces']:
            raise ValueError('Cover witnesses missing: '+case['id'])
        if record['harness_sha256']!=sha(HERE/'harness'/case['harness']):
            raise ValueError('Case harness binding changed: '+case['id'])
        source_by_copy={s['copy_name']:s for s in admission['sources']}
        if record['sources']!=[source_by_copy[name] for name in case['files']]:
            raise ValueError('Case source binding changed: '+case['id'])
        for name,key in [('case.sby','configuration_sha256'),('stdout.txt','stdout_sha256'),('stderr.txt','stderr_sha256')]:
            if exports[case['id']+'/'+name]['original_sha256']!=record[key]:
                raise ValueError('Original case receipt binding changed: '+case['id'])
        for trace in record['traces']:
            item=exports[case['id']+'/'+trace['path']]
            file=HERE/'evidence'/item['path']
            if item['original_sha256']!=trace['sha256'] or '$enddefinitions' not in file.read_text(encoding='utf-8'):
                raise ValueError('Counterexample/cover VCD binding changed: '+case['id'])
    for name,digest in summary['input_identity'].items():
        if sha(HERE/name)!=digest:
            raise ValueError('Proof input identity changed: '+name)
    print(json.dumps({"status": "PASS", "source_files": len(admission["sources"]), "package_files": len(files), "scope": "Integrity only; no formal proof executed"}))


def configuration(case):
    top = case["top"]
    params = " ".join("-set " + key + " " + str(value) for key, value in case["parameters"].items())
    files = " ".join(case["files"] + [case["harness"]])
    if case.get("frontend") == "slang":
        defines=' '.join('-D '+d for d in case.get('defines',[]))
        reader = "plugin -i slang\nread_slang -D FORMAL -D SYNTHESIS " + defines + " --top " + top + " " + files
        if params:
            raise ValueError("Slang cases must use harness default parameters")
    else:
        reader = "read_verilog -formal -sv -D SYNTHESIS " + files
    script = reader + "\n"
    if params:
        script += "chparam " + params + " " + top + "\n"
    script += "prep -top " + top + "\nasync2sync\ndffunmap\n"
    return "[options]\nmode " + case["mode"] + "\ndepth " + str(case["depth"]) + "\ntimeout " + str(case.get("timeout", 120)) + "\n\n[engines]\n" + case["engine"] + "\n\n[script]\n" + script + "\n[files]\n" + "\n".join(case["files"] + [case["harness"]]) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True, help="phase2 root containing verification/tsh2 and profiles/tsh2")
    parser.add_argument("--tool-bin", type=Path, help="OSS CAD Suite bin directory")
    parser.add_argument("--output", type=Path, help="New immutable attempt directory")
    parser.add_argument("--case", action="append", help="Case IDs; default executes all registered cases")
    parser.add_argument("--check-package", action="store_true")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    if args.check_package:
        check_package(repo)
        return
    if args.tool_bin is None or args.output is None:
        parser.error("Proof runs require --tool-bin and --output")
    admission = check_sources(repo)
    cases = read(HERE / "cases.json")["cases"]
    if args.case:
        missing = set(args.case) - {c["id"] for c in cases}
        if missing:
            parser.error("Unknown case: " + ",".join(sorted(missing)))
        cases = [c for c in cases if c["id"] in args.case]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    input_names = ['run.py', 'cases.json', 'admission.json', 'toolchain.json'] + sorted({'harness/' + c['harness'] for c in cases})
    input_hashes = {p:sha(HERE/p) for p in input_names}
    write(out / 'input_identity.json', {'files':input_hashes, 'sources':admission['sources']})
    tool_bin = args.tool_bin.resolve()
    env = os.environ.copy()
    env["PATH"] = str(tool_bin) + os.pathsep + env.get("PATH", "")
    env["LC_ALL"] = "C"
    tools = {}
    for executable, arguments in [("yosys", ["-V"]), ("sby", ["--version"]), ("z3", ["--version"]), ("boolector", ["--version"]), ('yosys-abc',['-c','version'])]:
        file = tool_bin / executable
        result = subprocess.run([str(file), *arguments], capture_output=True, text=True, env=env, timeout=30)
        tools[executable] = {"sha256": sha(file), "version": (result.stdout + result.stderr).strip(), "exit_code": result.returncode}
        if result.returncode != 0:
            write(out / 'tool_identity.json', tools)
            raise RuntimeError('Tool qualification failed: ' + executable)
    tools['suite'] = read(HERE / 'toolchain.json')
    plugin=tool_bin.parent/'share/yosys/plugins/slang.so'
    if plugin.exists(): tools['slang_plugin']={'suite_relative_path':'share/yosys/plugins/slang.so','sha256':sha(plugin)}
    write(out / "tool_identity.json", tools)
    results = []
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        bound = []
        for filename in case["files"]:
            item = next(s for s in admission["sources"] if s["copy_name"] == filename)
            shutil.copyfile(repo / item["path"], directory / filename)
            bound.append(item)
        shutil.copyfile(HERE / "harness" / case["harness"], directory / case["harness"])
        (directory / "case.sby").write_text(configuration(case), encoding="utf-8", newline="\n")
        command = [str(tool_bin / "sby"), "-d", "result", "case.sby"]
        start = time.monotonic()
        timed_out = False
        cleanup = 'not required'
        with (directory / "stdout.txt").open("w", encoding="utf-8") as stdout, (directory / "stderr.txt").open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(command, cwd=directory, env=env, stdout=stdout, stderr=stderr, start_new_session=(os.name=='posix'))
            try:
                process.wait(timeout=case.get('timeout',120)+60)
            except subprocess.TimeoutExpired:
                timed_out=True
                if os.name=='posix':
                    os.killpg(process.pid, signal.SIGKILL)
                    cleanup='owned POSIX process group killed'
                else:
                    killed=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,text=True)
                    cleanup='Windows owned process-tree cleanup exit ' + str(killed.returncode)
                    if killed.returncode: process.kill()
                process.wait(timeout=15)
        status_file = directory / "result/status"
        status = 'TIMEOUT' if timed_out else status_file.read_text().split()[0] if status_file.exists() else "ERROR"
        expected = case.get("expected", "PASS")
        traces = [{"path": p.relative_to(directory).as_posix(), "sha256": sha(p), "bytes": p.stat().st_size} for p in sorted((directory / "result").rglob("*.vcd"))]
        transcript=(directory/'stdout.txt').read_text(encoding='utf-8',errors='replace')
        control_signature=case.get('expected_assertion')
        negative_signature_matched=bool(control_signature and any(control_signature in line and ('failed assertion' in line.lower() or 'assert failed' in line.lower()) for line in transcript.splitlines()))
        accepted = status == expected and ((status == "PASS" and process.returncode == 0) or (status == "FAIL" and process.returncode != 0 and len(traces)>0 and negative_signature_matched))
        unchanged=all(sha(HERE/p)==h for p,h in input_hashes.items())
        check_sources(repo)
        accepted=accepted and unchanged
        record = {"case": case, "observed_status": status, "expected_status": expected, "acceptance": "PASS" if accepted else "FAIL", "exit_code": process.returncode, 'host_deadline_exceeded':timed_out, 'cleanup':cleanup, 'input_identity_unchanged':unchanged, 'negative_signature_matched':negative_signature_matched, "elapsed_seconds": round(time.monotonic()-start, 3), "command": command, "sources": bound, "harness_sha256": sha(directory/case["harness"]), "configuration_sha256": sha(directory/"case.sby"), "traces": traces, "stdout_sha256": sha(directory/"stdout.txt"), "stderr_sha256": sha(directory/"stderr.txt")}
        write(directory / "receipt.json", record)
        results.append(record)
        print(json.dumps({"id":case["id"],"status":status,"expected":expected,"acceptance":record["acceptance"],"seconds":record["elapsed_seconds"]}), flush=True)
        overall='RUNNING' if len(results)<len(cases) else 'PASS' if all(r['acceptance']=='PASS' for r in results) else 'FAIL'
        write(out / "summary.json", {"status":overall, "executed":len(results), "requested":len(cases), "results":results, "tools":tools, 'input_identity':input_hashes})
    raise SystemExit(0 if all(r["acceptance"]=="PASS" for r in results) else 1)


if __name__ == "__main__":
    main()
