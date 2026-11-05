"""Check that independent source, fixture and model corruption is rejected."""
from pathlib import Path
import argparse, importlib.util, json, shutil

HERE = Path(__file__).resolve().parent
PHASE2 = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    phase = out/'copy/phase2'
    package = phase/'verification/rf_iq'
    shutil.copytree(HERE, package, ignore=shutil.ignore_patterns('evidence', '__pycache__'))
    shutil.copytree(PHASE2/'profiles/trf1', phase/'profiles/trf1', ignore=shutil.ignore_patterns('__pycache__'))
    spec = importlib.util.spec_from_file_location('rf_checker_qualification', package/'run.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.check_package()
    outcomes = []
    changes = [
        ('snapshot RTL', 'profiles/trf1/snapshot/sources/trecap_rf_iq_adapter.sv'),
        ('editable RTL', 'profiles/trf1/adapter/rtl/trecap_rf_iq_adapter.sv'),
        ('independent reference', 'profiles/trf1/adapter/model/reference.py'),
        ('testbench', 'verification/rf_iq/benches/rf_iq_adapter_tb.sv'),
        ('expected numerical fixture', 'verification/rf_iq/vectors/single_min.output.hex'),
    ]
    for label, relative in changes:
        target = phase/relative
        original = target.read_bytes()
        target.write_bytes(original+b'\n')
        try:
            runner.check_package()
        except ValueError as error:
            outcomes.append(dict(mutation=label, status='PASS_EXPECTED_REJECTION', reason=str(error)))
        else:
            raise AssertionError('Corruption went undetected: '+label)
        finally:
            target.write_bytes(original)
    runner.check_package()
    result = dict(status='PASS', scope='Package integrity checker qualification. No RTL simulation.',
                  negative_controls=len(outcomes), results=outcomes)
    (out/'report.json').write_text(json.dumps(result, indent=2)+'\n', newline='\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
