"""Portable source-bound RF verification. This runner never accesses hardware."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PHASE2 = HERE.parents[1]
SNAPSHOT = PHASE2/'profiles/trf1/snapshot'
SCHEMAS = {
    'adapter': ('rf_iq_adapter_tb', 'PASS_RF_ADAPTER'),
    'limit': ('rf_limit_tb', 'PASS_RF_LIMIT'),
    'wrapper': ('rf_file_source_tb', 'RF_FILE_SOURCE_PASS'),
    'integration': ('rf_board_adapter_tb', 'PASS_RF_BOARD_ADAPTER'),
    'admission': ('rf_board_admission_tb', 'PASS_RF_BOARD_ADMISSION'),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8', newline='\n')


def checked_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def safe_member(root, relative):
    candidate = (root/relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError('Manifest path escapes root')
    return candidate


def check_package():
    manifest = checked_json(HERE/'package_manifest.json')
    for relative, expected in manifest['files'].items():
        if digest(safe_member(HERE, relative)) != expected:
            raise ValueError('Package source mismatch: '+relative)
    snapshot = checked_json(SNAPSHOT/'manifest.json')
    if digest(SNAPSHOT/'manifest.json') != manifest['snapshot_manifest_sha256']:
        raise ValueError('Snapshot manifest mismatch')
    for relative, expected in snapshot['files'].items():
        if digest(safe_member(SNAPSHOT, relative)) != expected:
            raise ValueError('Snapshot source mismatch: '+relative)
    for public, frozen in manifest['profile_bindings'].items():
        if digest(safe_member(PHASE2, public)) != digest(safe_member(SNAPSHOT, frozen)):
            raise ValueError('Editable/snapshot source mismatch: '+public)
    for relative, expected in manifest['model_bindings'].items():
        if digest(safe_member(PHASE2, relative)) != expected:
            raise ValueError('Independent reference mismatch: '+relative)
    if any('recorded_' in p.name for p in (HERE/'vectors').iterdir()):
        raise ValueError('Public fixtures must be synthetic')
    return dict(status='PASS_PACKAGE_INTEGRITY', files=len(manifest['files']),
                snapshot_files=len(snapshot['files']), source_id=snapshot['source_id'],
                rtl_simulation_performed=False)


def tool(sim_bin, name):
    suffix = '.exe' if os.name == 'nt' else ''
    result = (sim_bin/(name+suffix)) if sim_bin else Path(shutil.which(name) or '')
    if not result.is_file():
        raise ValueError('Simulator not found. Supply --sim-bin with vlib, vlog and vsim')
    return result.resolve()


def run_suite(suite, out, sim_bin, timeout):
    identity = check_package()
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    top, marker = SCHEMAS[suite]
    snapshot = checked_json(SNAPSHOT/'manifest.json')
    report = dict(schema='rf-verification-execution-v1', suite=suite, status='RUNNING',
                  source_id=identity['source_id'], hardware_used=False,
                  package_manifest_sha256=digest(HERE/'package_manifest.json'),
                  commands=[], observations=[])
    tools = {name: tool(sim_bin, name) for name in ('vlib', 'vmap', 'vlog', 'vsim')}
    report['tools'] = {name: dict(sha256=digest(path), executable=path.name) for name, path in tools.items()}
    public_replacements = [(str(out), '<RUN>'), (out.as_posix(), '<RUN>'),
                           (str(PHASE2), '<PHASE2>'), (PHASE2.as_posix(), '<PHASE2>')]
    public_replacements += [(str(p.parent), '<SIM_BIN>') for p in tools.values()]
    public_replacements += [(p.parent.as_posix(), '<SIM_BIN>') for p in tools.values()]

    def sanitize(text):
        text = text.replace('\r\n', '\n').replace('\r', '')
        for old, new in sorted(set(public_replacements), key=lambda x: -len(x[0])):
            text = text.replace(old, new)
        return text

    def invoke(stage, argv, expected_failure=False):
        argv = [str(x).replace('\\', '/') for x in argv]
        began = time.monotonic()
        result = subprocess.run(argv, cwd=out, capture_output=True, timeout=timeout)
        raw = result.stdout + result.stderr
        text = raw.decode('utf-8', errors='replace')
        public = sanitize(text)
        (out/(stage+'.txt')).write_text(public, encoding='utf-8', newline='\n')
        report['commands'].append(dict(stage=stage, argv=[sanitize(x) for x in argv],
            returncode=result.returncode, elapsed_s=time.monotonic()-began,
            raw_output_sha256=hashlib.sha256(raw).hexdigest(),
            public_output_sha256=digest(out/(stage+'.txt'))))
        save(out/'report.json', report)
        if expected_failure:
            if result.returncode == 0 or 'GOLD_MISMATCH' not in text:
                raise RuntimeError('Negative scoreboard control did not fail as expected')
        elif result.returncode != 0:
            raise RuntimeError(stage+' failed: '+public[-2000:])
        return text

    try:
        # Build copies live only in the fresh run directory. No original transcript is overwritten.
        for relative in snapshot['files']:
            target = out/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SNAPSHOT/relative, target)
        shutil.copyfile(HERE/'package_manifest.json', out/'executed_package_manifest.json')
        shutil.copyfile(SNAPSHOT/'manifest.json', out/'executed_snapshot_manifest.json')
        for folder in ('vectors', 'vectors_limit', 'fixtures'):
            shutil.copytree(HERE/folder, out/folder)
        shutil.copytree(HERE/'benches', out/'benches')
        executed = {}
        for folder in ('benches', 'vectors', 'vectors_limit', 'fixtures'):
            executed.update({p.relative_to(out).as_posix(): digest(p) for p in (out/folder).rglob('*') if p.is_file()})
        expected_package = checked_json(out/'executed_package_manifest.json')['files']
        for relative, actual in executed.items():
            if expected_package.get(relative) != actual:
                raise RuntimeError('Copied fixture or bench differs from admitted package: '+relative)
        report['executed_test_sha256'] = executed
        (out/'source_id.svh').write_text("localparam [255:0] TEST_SOURCE_ID=256'h"+identity['source_id']+';\n')
        macro = out/'run.do'
        macro.write_text('onerror {quit -code 2}\nonbreak {}\nrun -all\n'
            'set completed [string trim [examine -radix unsigned /'+top+'/checker_done]]\n'
            'puts "DV_CHECKER_DONE=$completed"\n'
            'if {$completed eq "1"} {quit -code 0} else {quit -code 1}\n')
        if suite in ('integration', 'admission'):
            sources = snapshot['ordered_systemverilog_files'][:]
            if suite == 'integration':
                sources += ['benches/trecap_stream_adapter.sv']
            compile_flags = ['-warning', '2892', '+define+SYNTHESIS']
        else:
            sources = ['sources/trecap_rf_iq_adapter.sv']
            if suite == 'wrapper':
                sources += ['sources/trecap_rf_file_source.sv']
            compile_flags = ['-warning', '2892']
        sources += ['benches/'+top+'.sv']
        invoke('vlib', [tools['vlib'], 'work'])
        invoke('vmap', [tools['vmap'], '-c'])
        invoke('compile', [tools['vlog'], '-sv', '-work', 'work']+compile_flags+
               ['+incdir+.', '+incdir+sources', '+incdir+source/rtl/include',
                '+incdir+source/rtl/include/generated', '+incdir+source/rtl/interfaces']+sources)
        seeds = (1, 7, 20261103) if suite == 'adapter' else (20261103,)
        for seed in seeds:
            plus = ['+SEED='+str(seed)]
            if suite == 'adapter' and seed == 1:
                plus += ['+VCD=observed.vcd']
            if suite == 'admission':
                plus += ['+VCD=observed.vcd']
            if suite == 'integration':
                plus += ['+OUT=.', '+CASES=fixtures/cases.txt']
            text = invoke('seed_'+str(seed), [tools['vsim'], '-c', '-onfinish', 'stop',
                '-voptargs=+acc', 'work.'+top]+plus+['-do', 'run.do'])
            lines = [line.strip().lstrip('#').strip() for line in text.splitlines() if marker in line]
            if len(lines) != 1 or 'DV_CHECKER_DONE=1' not in text:
                raise RuntimeError('Explicit completion gate missing or ambiguous')
            if re.search(r'\*\* (?:Fatal|Error):', text):
                raise RuntimeError('Unexpected simulator error')
            counters = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', lines[0])}
            report['observations'].append(dict(seed=seed, marker=lines[0], counters=counters))
        if suite == 'adapter':
            invoke('negative_expected_mismatch', [tools['vsim'], '-c', '-onfinish', 'stop',
                   '-voptargs=+acc', 'work.'+top, '+SEED=1', '+NEGATIVE', '-do', 'run.do'], True)
            report['negative_control'] = 'PASS_EXPECTED_GOLD_MISMATCH'
        if (out/'observed.vcd').exists():
            # Filename and simulator comment metadata are retained unless an absolute path appears.
            original = (out/'observed.vcd').read_bytes()
            normalized = sanitize(original.decode('utf-8')).encode('utf-8')
            (out/'observed.vcd').write_bytes(normalized)
            report['waveform'] = dict(path='observed.vcd', raw_sha256=hashlib.sha256(original).hexdigest(),
                                      public_sha256=digest(out/'observed.vcd'))
        for relative, expected in snapshot['files'].items():
            if digest(out/relative) != expected:
                raise RuntimeError('Executed source drift: '+relative)
        for relative, expected in report['executed_test_sha256'].items():
            if digest(out/relative) != expected:
                raise RuntimeError('Executed fixture or bench changed: '+relative)
        if digest(HERE/'package_manifest.json') != report['package_manifest_sha256']:
            raise RuntimeError('Package manifest changed during execution')
        if digest(out/'executed_package_manifest.json') != report['package_manifest_sha256']:
            raise RuntimeError('Executed package admission record changed')
        if digest(SNAPSHOT/'manifest.json') != digest(out/'executed_snapshot_manifest.json'):
            raise RuntimeError('Snapshot manifest changed during execution')
        check_package()
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error=sanitize(str(error)))
        raise
    finally:
        report['artifacts'] = {p.name: digest(p) for p in sorted(out.iterdir())
            if p.is_file() and (p.suffix in ('.txt', '.csv', '.vcd', '.do') or p.name.startswith('executed_'))}
        save(out/'report.json', report)
        print(json.dumps(dict(suite=suite, status=report['status'], report=str(out/'report.json'))), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-package', action='store_true')
    parser.add_argument('--suite', choices=tuple(SCHEMAS)+('all',))
    parser.add_argument('--sim-bin', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 1800:
        parser.error('timeout must be between 1 and 1800 seconds per simulator process')
    if args.check_package:
        print(json.dumps(check_package()))
    if args.suite:
        if args.out is None:
            parser.error('--suite needs a fresh --out directory')
        if args.suite == 'all':
            args.out.mkdir(parents=True, exist_ok=False)
            reports = [run_suite(name, args.out/name, args.sim_bin, args.timeout) for name in SCHEMAS]
            save(args.out/'summary.json', dict(status='PASS', suites={r['suite']: r['status'] for r in reports}))
        else:
            run_suite(args.suite, args.out, args.sim_bin, args.timeout)
    elif not args.check_package:
        parser.error('select --check-package or --suite')


if __name__ == '__main__':
    main()
