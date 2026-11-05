"""Verify committed RF execution receipts against sources, traces and logs."""
from pathlib import Path
import csv, hashlib, json, re
from run import check_package, SCHEMAS, HERE, PHASE2, SNAPSHOT


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify():
    check_package()
    evidence = HERE/'evidence'
    manifest = read(evidence/'manifest.json')
    assert manifest['checker_sha256'] == sha(Path(__file__)), 'evidence checker changed'
    for relative, expected in manifest['files'].items():
        path = (evidence/relative).resolve()
        assert path.is_relative_to(evidence.resolve()), 'evidence path escape'
        assert sha(path) == expected, 'evidence artifact mismatch: '+relative
    summary = read(evidence/'summary.json')
    assert summary['status'] == 'PASS'
    reports = {}
    for suite, (top, marker) in SCHEMAS.items():
        folder = evidence/suite
        report = read(folder/'report.json')
        assert report['status'] == 'PASS' and not report['hardware_used']
        assert report['source_id'] == read(SNAPSHOT/'manifest.json')['source_id']
        assert report['package_manifest_sha256'] == sha(HERE/'package_manifest.json')
        assert sha(folder/'executed_package_manifest.json') == report['package_manifest_sha256']
        assert sha(folder/'executed_snapshot_manifest.json') == sha(SNAPSHOT/'manifest.json')
        for relative, expected in report['executed_test_sha256'].items():
            assert sha(HERE/relative) == expected, 'executed test source mismatch: '+relative
        for relative, expected in report['artifacts'].items():
            assert sha(folder/relative) == expected, 'receipt artifact mismatch: '+relative
        for command in report['commands']:
            text = (folder/(command['stage']+'.txt')).read_text()
            assert sha(folder/(command['stage']+'.txt')) == command['public_output_sha256']
            if command['stage'] == 'negative_expected_mismatch':
                assert command['returncode'] != 0 and 'GOLD_MISMATCH' in text
            else:
                assert command['returncode'] == 0
                assert not re.search(r'\*\* (?:Error|Fatal):', text)
        for observation in report['observations']:
            text = (folder/('seed_'+str(observation['seed'])+'.txt')).read_text()
            lines = [x.strip().lstrip('#').strip() for x in text.splitlines() if marker in x]
            assert lines == [observation['marker']]
            assert 'DV_CHECKER_DONE=1' in text
            counters = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', lines[0])}
            assert counters == observation['counters']
        reports[suite] = report
    adapter = reports['adapter']
    assert [x['seed'] for x in adapter['observations']] == [1, 7, 20261103]
    for observation in adapter['observations']:
        c = observation['counters']
        assert c['cases'] == 40 and c['samples'] == 11080 and c['aborts'] == 4
        assert min(c[k] for k in ('stalls', 'source_gaps', 'long_stalls')) > 0
    assert adapter['negative_control'] == 'PASS_EXPECTED_GOLD_MISMATCH'
    assert reports['limit']['observations'][0]['counters']['samples'] == 384000
    assert reports['wrapper']['observations'][0]['counters']['completed'] == 4
    assert reports['wrapper']['observations'][0]['counters']['aborted'] == 2
    admission = reports['admission']['observations'][0]['counters']
    for flag in ('ready_bad_word', 'busy_config', 'watchdog_recovery', 'pending_prefetch_reset', 'held_prefetch_clear'):
        assert admission[flag] == 1
    integration = reports['integration']['observations'][0]['counters']
    assert integration['epochs'] == 32 and integration['negatives'] == 18
    for counter in ('iqfull', 'spectralfull', 'yfull', 'rfstalls'):
        assert integration[counter] > 0
    with (evidence/'integration/epochs.csv').open(newline='') as stream:
        epochs = list(csv.DictReader(stream))
    assert len(epochs) == 32
    for a, b in zip(epochs[::2], epochs[1::2]):
        assert a['rf_mode'] == '0' and b['rf_mode'] == '1'
        assert a['case'] == b['case']
        for field in ('pairs', 'gain', 'threshold', 'sparse', 'y_samples', 'spectral_bytes', 'clips'):
            assert a[field] == b[field], field
        assert int(a['y_samples']) == 2560
    assert sum(int(x['y_samples']) for x in epochs) == summary['integration_y_samples']
    reference = read(evidence/'reference_check.json')
    assert reference['status'] == 'PASS' and reference['fixtures'] == 42 and reference['samples'] == 405304
    qualification = read(evidence/'package_qualification.json')
    assert qualification['status'] == 'PASS' and qualification['negative_controls'] == 5
    for name in ('adapter', 'admission'):
        wave = reports[name]['waveform']
        assert sha(evidence/name/wave['path']) == wave['public_sha256']
        assert '$enddefinitions' in (evidence/name/wave['path']).read_text()
    return dict(status='PASS_RF_EVIDENCE', suites=len(reports),
                published_artifacts=len(manifest['files']), adapter_transactions=120,
                adapter_samples=33240, maximum_samples=384000,
                integration_epochs=32, integration_y_samples=summary['integration_y_samples'])


if __name__ == '__main__':
    print(json.dumps(verify()))
