"""Offline exact-content positives and mutation negatives; never hardware."""
from pathlib import Path
import argparse,copy,json,sys
sys.dont_write_bytecode=True
import validate as v
def main():
    p=argparse.ArgumentParser();p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();v.need(not a.out.exists(),'fresh tests');gold=v.load_fixtures(a.fixtures);checks=[]
    for c,s in v.case_order(gold['cases']):
        mode='sparse' if s else 'dense';wire=Path(c['packets'][mode]['path']).read_bytes();y=Path(c['y_i32le']).read_bytes();r=v.validate_content(wire,y,c,s);checks.append({'name':v.name(c,s),'result':'PASS_EXACT_GOLD','bytes':r['bytes'],'y_samples':r['y_samples'],'records':r['records']})
    c=gold['cases'][1];wire=Path(c['packets']['sparse']['path']).read_bytes();y=Path(c['y_i32le']).read_bytes()
    def reject(name,call):
        try:call()
        except (ValueError,AssertionError,StopIteration):checks.append({'name':name,'result':'PASS_REJECTED'});return
        raise AssertionError('Accepted '+name)
    for label,w in [('truncated',wire[:-1]),('trailing',wire+b'\0'),('firstbyte',bytes([wire[0]^1])+wire[1:]),('lastbyte',wire[:-1]+bytes([wire[-1]^1]))]:reject(label,lambda w=w:v.validate_content(w,y,c,True))
    reject('wrong_mode',lambda:v.validate_content(wire,y,c,False));bad=copy.deepcopy(c);bad['threshold']+=1;reject('wrong_threshold',lambda:v.validate_content(wire,y,bad,True))
    reject('Y_truncated',lambda:v.validate_content(wire,y[:-4],c,True));reject('Y_last_sample',lambda:v.validate_content(wire,y[:-1]+bytes([y[-1]^1]),c,True))
    meta={'source_id':'1'*64};boot='01234567-89ab-cdef-0123-456789abcdef';receipt=dict(schema='tsh2-stream-client-v1',status='CAPTURED_PENDING_PC_VALIDATION',source_id=meta['source_id'],boot_id=boot,threshold=c['threshold'],sparse=1,epoch=1,input_count=384000,y_count=384512,frames=3001,drops=0,bytes=len(wire),performance_comparison=False,fabric_cycles_including_host_stalls=12345,poll_iterations=20000)
    v.validate_receipt(receipt,c,True,meta,boot,1,len(wire));checks.append({'name':'receipt_positive','result':'PASS'})
    for key,value in [('source_id','0'*64),('boot_id','wrong'),('epoch',2),('input_count',1024),('y_count',1536),('frames',9),('drops',1),('fabric_cycles_including_host_stalls',3000000001),('poll_iterations',2000000),('performance_comparison',True)]:
        r=dict(receipt);r[key]=value;reject('receipt_'+key,lambda r=r:v.validate_receipt(r,c,True,meta,boot,1,len(wire)))
    a.out.mkdir(parents=True);report={'status':'PASS_OFFLINE_VALIDATOR_TESTS','tests':len(checks),'checks':checks,'hardware_access':False,'fixtures_sha256':v.filehash(a.fixtures),'validator_sha256':v.filehash(Path(v.__file__)),'tests_sha256':v.filehash(__file__)};v.writejson(a.out/'report.json',report);print(json.dumps({k:w for k,w in report.items() if k!='checks'}))
if __name__=='__main__':main()
