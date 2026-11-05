"""Export a sanitized projection after auditing local historical RF artifacts.

The source workspace is private input. Raw recordings, returned sample streams,
machine paths and UART transcripts are deliberately not copied to this bundle.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace.resolve()
    evidence = HERE / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(path, expected, label=None):
        path = Path(path)
        if not path.is_absolute():
            path = root / path
        actual = sha(path)
        logical = label or path.relative_to(root).as_posix()
        checks.append(dict(artifact=logical, sha256=actual, matched=actual == expected))
        if actual != expected:
            raise ValueError('Historical hash mismatch: ' + logical)
        return actual

    def read(rel):
        path = root / rel
        return json.loads(path.read_text()), dict(artifact=rel, sha256=sha(path))

    analysis, analysis_origin = read('outputs/trecap_rf_board_v01/analysis02/report.json')
    capture, capture_origin = read('outputs/trecap_rf_board_v01/capture01/receipt.json')
    program, program_origin = read('outputs/trecap_rf_board_v01/program01/receipt.json')
    build, build_origin = read('outputs/trecap_rf_board_v01/build02/final_assessment.json')
    assembly, assembly_origin = read('outputs/trecap_rf_board_v01/build02/assembly_receipt.json')
    sample, sample_origin = read('outputs/trecap_rf_board_v01/sample01/manifest.json')
    timing, timing_origin = read('outputs/trecap_rf_board_v01/build02/timing_assessment.json')
    for origin, expected in [(capture_origin, analysis['capture_receipt_sha256']),
                             (program_origin, analysis['program_receipt_sha256']),
                             (sample_origin, analysis['sample_manifest_sha256'])]:
        check(origin['artifact'], expected)
    for receipt, field in [(build, 'evidence_sha256'), (capture, 'evidence_sha256'), (program, 'admission_sha256')]:
        for path, expected in receipt[field].items():
            check(path, expected)
    check(capture['package_manifest'], capture['package_manifest_sha256'])
    check('outputs/trecap_rf_board_v01/capture01/capture.tar.gz', capture['archive_sha256'])
    check(assembly['sof_path'], assembly['sof_sha256'])
    captured = root / capture['captured_directory']
    check(captured / 'RESULTS.sha256', capture['result_manifest_sha256'])
    for line in (captured / 'RESULTS.sha256').read_text().splitlines():
        expected, name = line.split('  ', 1)
        check(captured / name, expected)
    for case in analysis['cases']:
        for suffix, field in [('.json', 'receipt_sha256'), ('.y.i32le', 'y_sha256'), ('.tsp1', 'tsp1_sha256')]:
            check(captured / (case['name'] + suffix), case[field])
    for source in sample['sources']:
        check(source['path'], source['sha256'])
    for case in sample['cases']:
        check(case['y_path'], case['y_sha256'])
        check(case['packet_path'], case['packet_sha256'])
    source_id = analysis['source_id']
    assert all(x['source_id'] == source_id for x in (capture, program, build, timing))
    assert assembly['sof_sha256'] == analysis['sof_sha256'] == capture['sof_sha256'] == program['sof_sha256']
    assert analysis['boot_id'] == capture['boot_id']
    fit = root / 'outputs/trecap_rf_board_v01/build02/output_files/audio_hps.fit.rpt'
    fit_text = fit.read_text(errors='strict')
    for token in ['7,196 / 32,070', '9385', '329,088 / 4,065,280', '48 / 397', '36 / 87', '138 / 457']:
        assert token in fit_text, token
    projection = dict(
        schema='trecap-rf-historical-evidence-projection-v1',
        artifact_kind='sanitized_projection_not_raw_capture',
        provenance_note='Selected factual fields from locally retained historical receipts. Original artifact SHA-256 identities are preserved. This is not a fresh hardware run or an independent signature.',
        source_id=source_id, sof_sha256=analysis['sof_sha256'], boot_id=analysis['boot_id'],
        originals=[analysis_origin,capture_origin,program_origin,build_origin,assembly_origin,sample_origin,timing_origin],
        physical_run=dict(started_utc=capture['started_utc'],ended_utc=capture['ended_utc'],status=analysis['status'],
                          raw_cu8_sent=capture['raw_cu8_sent'],gold_uploaded=capture['gold_uploaded'],
                          input_pairs=sample['pair_count'],input_bytes=sample['input_bytes'],
                          gain_shift=sample['gain_shift'],complex_sample_rate_hz=sample['sample_rate_iq_hz'],
                          real_sample_rate_hz=sample['real_sample_rate_hz'],duration_seconds=analysis['duration_s'],
                          valid_real_samples=sample['valid_real_samples'],transaction_samples=sample['transaction_samples'],
                          raw_source_url=analysis['raw_source_url'],raw_source_sha256=analysis['raw_source_sha256'],
                          valid_prefix_frames=sample['valid_prefix_frames'],cases=analysis['cases']),
        implementation=dict(device=build['device'],clock_hz=build['clock_hz'],status=assembly['status'],
                            resource_report_sha256=sha(fit),resources=dict(alms=7196,registers=9385,block_memory_bits=329088,m10k_blocks=48,dsp_blocks=36,active_pins=138),
                            fabric_timing=[{k:v for k,v in row.items() if k in ('corner','clock','check','slack_ns')} for row in build['fabric_and_afi_paths'] if row['clock']=='CLOCK_50'],
                            expected_clocks=len(build['clocks']),independent_timing_records=len(timing['independent_path_records']),
                            calibrated_ddr_records=len(build['calibrated_ddr']),hps_scalar_pins=build['pins']['HPS_scalar_count'],
                            handoff_matches_parent=assembly['hps_handoff_matches_parent']),
        limitations=analysis['limitations']+['Hardware evidence records an earlier session. It does not describe the board image currently active.',
                                         'Raw RF samples and returned waveform/packet captures are intentionally excluded from this publication.'],
        local_hash_audit=dict(status='PASS',checks=len(checks),records=checks))
    (evidence/'historical_projection.json').write_text(json.dumps(projection,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','local_hash_checks':len(checks),'source_id':source_id,'projection':'evidence/historical_projection.json'}))


if __name__ == '__main__':
    main()
