"""Exercise protocol2 admission without accessing hardware."""
from pathlib import Path
import argparse,sys,unittest

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate-repo',required=True,type=Path)
args=parser.parse_args()
repo=args.candidate_repo.resolve()
sys.dont_write_bytecode=True
sys.path.insert(0,str(repo/'scripts/measurement'))
import run_zero_campaign as candidate
import test_run_campaign as inherited

legacy_fixtures=inherited.fixtures
def fixtures():
    events,anchors=legacy_fixtures()
    for index,event in enumerate(events[:-1]):
        mode=(2,3,3,2)[index%4]
        raw=int(event['probe_hex'],16)
        words=[(raw>>(32*i))&0xffffffff for i in range(15)]
        words[1]=(2<<24)|0x82|0x20|(0x800 if mode==3 else 0)
        words[2]=(16384<<16)|mode
        event['probe_hex']=f'{sum(w<<(32*i) for i,w in enumerate(words)):0120x}'
        event['condition']='masked_baseline' if mode==2 else 'masked_isolated'
        event['threshold2']=100_000_000_000
    return events,anchors

inherited.runner=candidate
inherited.fixtures=fixtures

class IsolationAdmission(unittest.TestCase):
    def test_wrong_protocol_or_isolation_status(self):
        for trial,word,mask,value in ((0,1,0xff000000,0x01000000),
                                     (0,1,0x800,0x800),(1,1,0x800,0),
                                     (1,2,3,2)):
            events,anchors=fixtures()
            raw=int(events[trial]['probe_hex'],16)
            raw=(raw&~(mask<<(32*word)))|(value<<(32*word))
            events[trial]['probe_hex']=f'{raw:0120x}'
            with self.assertRaises(ValueError):
                candidate.build_trials(events,anchors,inherited.FREQUENCY,16384,3)

    def test_schedule_mismatch(self):
        events,anchors=fixtures()
        events[1]['cycles']+=1
        raw=int(events[1]['probe_hex'],16)
        raw+=1<<(32*8)
        events[1]['probe_hex']=f'{raw:0120x}'
        with self.assertRaisesRegex(ValueError,'changed cycle count'):
            candidate.build_trials(events,anchors,inherited.FREQUENCY,16384,3)

suite=unittest.TestSuite()
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(inherited.AdmissionChecks))
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(IsolationAdmission))
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
