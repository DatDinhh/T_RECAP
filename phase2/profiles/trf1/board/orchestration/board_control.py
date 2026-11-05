"""Serialized RF hardware trial operations, volatile board RAM only."""
from pathlib import Path
import argparse
import os
import shutil
import hashlib
import json
import re
import socket
import subprocess
import tarfile
from datetime import datetime, timezone

ROOT = Path(os.environ.get('TRECAP_RF_WORKSPACE', '.')).resolve()
HERE = Path(__file__).resolve().parent
HARDWARE = HERE / 'hardware'
OUT = ROOT / 'outputs/trecap_rf_board_v01'
RUNNER = ROOT / 'work/ai_audio_frontend_v01/platform/run_uart_plan.ps1'
PWSH = Path(os.environ.get('TRECAP_PWSH', shutil.which('pwsh') or 'pwsh'))
BB = '/opt/fma-net/busybox'
IP = '169.254.196.128'
PROC = 'for p in /proc/[0-9]*; do printf "%s " "$p"; cat "$p/comm"; cat "$p/cmdline"; printf "\\n"; done'


def now(): return datetime.now(timezone.utc).isoformat()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p, value): Path(p).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(test, why):
    if not test: raise RuntimeError(why)


def command(text, marker, seconds=15, reject=''):
    need(re.fullmatch(r'[a-z0-9_]+', marker), 'Marker grammar')
    need(1 <= seconds <= 60, 'Bounded UART step')
    token = 'RF_' + marker.upper() + '_RC'
    line = text + f'; rc=$?; printf "\\n{token}=%s\\n" "$rc"'
    need(len(line) <= 1024, 'UART command bound')
    return {'command': line, 'completion_regex': fr'(?m)^{token}=[0-9]+\r*$',
            'expect_regex': fr'(?m)^{token}=0\r*$',
            'reject_regex': fr'(?m)^{token}=[1-9][0-9]*\r*$|Bus error|Segmentation fault|applet not found' + ('|' + reject if reject else ''),
            'timeout_seconds': seconds}


def execute_plan(plan, receipt):
    plan, receipt = Path(plan), Path(receipt)
    need(plan.is_file() and not receipt.exists(), 'Existing plan and fresh receipt required')
    p = read(plan)
    timeout = 20 + sum(s['timeout_seconds'] for s in p['commands'])
    proc = subprocess.run([str(PWSH), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(RUNNER),
                           '-PlanPath', str(plan), '-OutputPath', str(receipt)], capture_output=True,
                          encoding='utf-8', errors='replace', timeout=timeout)
    need(receipt.exists(), 'UART receipt absent: ' + proc.stderr[-800:])
    result = read(receipt)
    need(proc.returncode == 0 and result['status'] == 'PASS' and result['closed'],
         'UART failed, inspect ' + str(receipt))
    return result


def uart(folder, name, steps):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    plan, receipt = folder / (name+'_plan.json'), folder / (name+'.json')
    need(not plan.exists() and not receipt.exists(), 'Fresh UART evidence required')
    save(plan, {'scope': 'User-authorized raw RF trial on TRF1. RAM-only transport and capture. No SD, flash, or Windows network modification.', 'commands': steps})
    return execute_plan(plan, receipt)


def body(receipt): return '\n'.join(r['response_body'] for r in receipt['records'])
def boot(receipt):
    ids = set(re.findall(r'(?m)^([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\r?$', body(receipt)))
    need(len(ids) == 1, 'One observed boot UUID required')
    return ids.pop()


def idle(text):
    rows = text.replace('\x00', ' ').splitlines()
    need(not any(len(s.split()) >= 4 and s.split()[0].rstrip(':').isdigit() and s.split()[3] == '0A' for s in rows), 'Unexpected TCP listener')
    need(not any(re.search(r'(?:service\.arm|tsh2_client|trf1_client|activity_led\.arm|/capture\.sh|nc -l|timeout -s)', s) for s in rows), 'Another board capture is active')


def finished_transfer(path):
    """Allow the background shell to record nc's exit after socket EOF."""
    need(re.fullmatch(r'/tmp/trecap-rf-[a-f0-9]{8,16}(?:-results\.tar\.gz\.send|\.receive)\.rc', path), 'Bounded transfer receipt path')
    return f'i=0; while test ! -f {path} && test "$i" -lt 3; do {BB} sleep 1; i=$((i+1)); done; test -f {path} && test "$(cat {path})" = 0'


def upload(folder, archive, base, expected_boot):
    folder, archive = Path(folder), Path(archive)
    need(re.fullmatch(r'/tmp/trecap-rf-[a-f0-9]{8,16}', base), 'Bounded RAM path')
    pre = uart(folder, 'preflight', [command('cat /proc/sys/kernel/random/boot_id; cat /proc/mounts', 'boot', reject='/dev/mmc|/dev/sd|overlay|nfs'), command(PROC+'; cat /proc/net/tcp; cat /proc/net/tcp6', 'idle')])
    need(boot(pre) == expected_boot, 'Boot unchanged before transfer')
    idle(pre['records'][1]['response_body'])
    with tarfile.open(archive, 'r:gz') as tar:
        names = set()
        for m in tar.getmembers():
            need(m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts, 'Safe package member')
            need(m.name.startswith(base.split('/')[-1]+'/') and m.name not in names, 'Unique package member under target')
            names.add(m.name)
    start = f'if test ! -e {base}.tar.gz && test ! -e {base}; then ( {BB} timeout -s KILL 45 {BB} nc -l -p 18080 > {base}.tar.gz; r=$?; printf "%s\\n" "$r" > {base}.receive.rc ) </dev/null > {base}.receive.log 2>&1 & p=$!; {BB} sleep 1; kill -0 "$p"; else false; fi'
    uart(folder, 'upload_start', [command(start, 'receive')])
    with socket.create_connection((IP, 18080), timeout=5) as s:
        s.settimeout(20)
        s.sendall(archive.read_bytes())
        s.shutdown(socket.SHUT_WR)
        need(s.recv(1) == b'', 'No unexpected upload response')
    uart(folder, 'upload_extract', [command(finished_transfer(base+'.receive.rc') + f' && printf "{sha(archive)}  {base}.tar.gz\\n" | {BB} sha256sum -c - && test ! -e {base} && {BB} tar -xzf {base}.tar.gz -C /tmp', 'extract')])


def download(folder, remote_archive, expected_sha, expected_files):
    folder = Path(folder)
    need(re.fullmatch(r'/tmp/trecap-rf-[a-f0-9]{8,16}-results\.tar\.gz', remote_archive), 'Bounded capture archive')
    need(re.fullmatch(r'[a-f0-9]{64}', expected_sha), 'Observed archive hash')
    local = folder / 'capture.tar.gz'
    need(not local.exists(), 'Fresh download')
    start = f'( {BB} timeout -s KILL 45 {BB} nc -l -p 18081 < {remote_archive}; r=$?; printf "%s\\n" "$r" > {remote_archive}.send.rc ) > {remote_archive}.send.log 2>&1 & p=$!; {BB} sleep 1; kill -0 "$p"'
    uart(folder, 'download_start', [command(start, 'send')])
    with socket.create_connection((IP, 18081), timeout=5) as s, local.open('xb') as f:
        s.settimeout(30)
        total = 0
        while True:
            chunk = s.recv(1 << 20)
            if not chunk: break
            total += len(chunk)
            need(total <= 32 << 20, 'Bounded capture download')
            f.write(chunk)
        s.shutdown(socket.SHUT_WR)
    need(sha(local) == expected_sha, 'UART/network archive SHA agreement')
    dest = folder / 'captured'
    dest.mkdir(exist_ok=False)
    with tarfile.open(local, 'r:gz') as tar:
        members = tar.getmembers()
        need(sorted(m.name for m in members) == sorted(expected_files), 'Exact allowlisted capture members')
        for m in members:
            need(m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts and m.size <= 4 << 20, 'Safe bounded capture member')
            p = dest / m.name
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('xb') as f: f.write(tar.extractfile(m).read())
    uart(folder, 'final_idle', [command(finished_transfer(remote_archive+'.send.rc') + ' && cat /proc/sys/kernel/random/boot_id', 'sent'), command(PROC+'; cat /proc/net/tcp; cat /proc/net/tcp6', 'idle')])
    idle(read(folder/'final_idle.json')['records'][1]['response_body'])
    return dest


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['03_preprogram','04_dt','05_boot','06_full_shell','07_runtime','08_network'])
    a = ap.parse_args()
    r = execute_plan(HARDWARE/(a.stage+'_plan.json'), HARDWARE/(a.stage+'_receipt.json'))
    print(json.dumps({'stage': a.stage, 'status': r['status'], 'closed': r['closed'], 'records': len(r['records'])}))
