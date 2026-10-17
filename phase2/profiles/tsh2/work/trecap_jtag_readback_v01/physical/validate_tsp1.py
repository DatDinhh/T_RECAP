"""Strict finite TSP1 decoder, exact frozen-ROM comparison and 16-band consumer.

Content validation alone does not establish physical provenance; bind the saved
bytes to the separate admitted JTAG capture receipt before claiming readback.
"""
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,struct,sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
ORACLE=ROOT/'work/trecap_sparse_consumer_v01/audit_packets.py'
FIX=ROOT/'outputs/trecap_sparse_consumer_v01/fixtures01/cases'
MASK64=(1<<64)-1

def require(ok,msg):
    if not ok:raise ValueError(msg)
def sha(data):return hashlib.sha256(data).hexdigest()
def fnv(data):
    value=14695981039346656037
    for byte in data:value=((value^byte)*1099511628211)&MASK64
    return value

def decode_record(data,frame,threshold,sparse):
    require(48<=len(data)<=1080,'record length bounds')
    magic,version,encoding,config,payload,actualframe,thr,count,flags,reserved=struct.unpack('<IHHIIQQHHI',data[:40])
    require((magic,version,encoding,config)==(0x31505354,1,int(sparse),0x10001),'header identity/configuration')
    require(actualframe==frame and thr==threshold,'frame/threshold mismatch')
    require(flags==1 and reserved==0,'flags/reserved')
    require(1<=count<=129 and (sparse or count==129),'count bounds')
    require(payload==(8*count if sparse else 903),'payload/count mismatch')
    require(len(data)==((48+payload+7)&~7),'exact record length')
    require(all(x==0 for x in data[48+payload:]),'nonzero padding')
    require(int.from_bytes(data[40:48],'little')==fnv(data[:40]+data[48:]),'checksum mismatch')
    if sparse:
        words=[int.from_bytes(data[48+8*i:56+8*i],'little') for i in range(count)]
        pairs=[(word&255,word>>8) for word in words]
        require(pairs[0][0]==0,'missing protected DC')
        require(all(0<=k<=128 for k,v in pairs),'bin index bounds')
        require(all(pairs[i][0]<pairs[i+1][0] for i in range(count-1)),'nonincreasing/duplicate bins')
        require(all(k==0 or v>=threshold for k,v in pairs),'sparse threshold violation')
        require(threshold!=0 or count==129,'threshold zero must retain every bin')
    else:
        pairs=[(k,int.from_bytes(data[48+7*k:55+7*k],'little')) for k in range(129)]
        require(all(k==0 or v==0 or v>=threshold for k,v in pairs),'dense threshold violation')
    features=[0]*16
    for k,v in pairs:features[16*k//129]+=v*(1 if k in (0,128) else 2)
    return features

def expected(threshold,sparse):
    require(threshold in (0,100_000_000_000),'Only frozen ROM thresholds 0 and 1e11 are qualified')
    spec=importlib.util.spec_from_file_location('frozen_packet_oracle',ORACLE);oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    bins=FIX/'multitone1024_thr0/bin_stats.csv'
    with bins.open() as f:rows=list(csv.DictReader(f))
    require(len(rows)==9*129,'frozen ROM frame count')
    packets=[]
    for frame in range(9):
        group=rows[129*frame:129*(frame+1)]
        require([int(r['bin_idx']) for r in group]==list(range(129)),'frozen ROM bin order')
        values=[int(r['mag2']) for r in group]
        packets.append(oracle.record(frame,threshold,values,[k==0 or v>=threshold for k,v in enumerate(values)],sparse))
    featurepath=FIX/f'multitone1024_thr{threshold}/expected_features.csv'
    with featurepath.open() as f:rows=list(csv.DictReader(f))
    require([int(r['frame_idx']) for r in rows]==list(range(9)),'frozen feature order')
    features=[[int(r[f'band{k}']) for k in range(16)] for r in rows]
    return packets,features,{'oracle':str(ORACLE),'oracle_sha256':sha(ORACLE.read_bytes()),'bins':str(bins),'bins_sha256':sha(bins.read_bytes()),'features':str(featurepath),'features_sha256':sha(featurepath.read_bytes())}

def validate_capture(data,threshold,sparse):
    require(type(sparse)==bool,'sparse must be bool')
    require(0<len(data)<=9720,'finite capture length bounds')
    gold,expectedfeatures,sources=expected(threshold,sparse)
    offset=0;records=[];features=[]
    for frame in range(9):
        require(len(data)-offset>=48,'truncated header')
        payload=int.from_bytes(data[offset+12:offset+16],'little')
        require(payload<=1032,'payload exceeds one record')
        size=(48+payload+7)&~7
        require(offset+size<=len(data),'truncated record')
        packet=data[offset:offset+size]
        feature=decode_record(packet,frame,threshold,sparse)
        require(packet==gold[frame],f'frame {frame} exact bytes differ from independent gold')
        require(feature==expectedfeatures[frame],f'frame {frame} consumer features differ')
        records.append({'frame':frame,'offset':offset,'bytes':size,'sha256':sha(packet)})
        features.append(feature);offset+=size
    require(offset==len(data),'trailing bytes/extra record')
    return {'status':'EXACT_CONTENT_PASS','threshold':threshold,'sparse':sparse,'record_count':9,'checked_bytes':len(data),'feature_components':144,
            'capture_sha256':sha(data),'records':records,'features':features,'sources':sources,
            'validator_sha256':sha(Path(__file__).read_bytes()),
            'scope':'Strict TSP1 bytes and 16-band features for the fixed multitone ROM; physical provenance requires separate admitted readback receipt. No flute or threshold1e8 claim.'}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--capture',type=Path,required=True);ap.add_argument('--threshold',type=int,choices=(0,100_000_000_000),required=True);ap.add_argument('--sparse',type=int,choices=(0,1),required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    require(not a.out.exists(),'Fresh result directory required')
    result=validate_capture(a.capture.read_bytes(),a.threshold,bool(a.sparse));a.out.mkdir(parents=True)
    (a.out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    with (a.out/'features.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['frame_idx']+[f'band{k}' for k in range(16)])
        for frame,feature in enumerate(result['features']):writer.writerow([frame,*feature])
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','features','sources')}))
