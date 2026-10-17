"""Host-side task summary control, not a format emitted by current RTL."""
import struct
import numpy as np
from common import need

BODY=struct.Struct('<4sHHIHHdd16d')
def fnv(data):
    h=14695981039346656037
    for b in data:h=((h^b)*1099511628211)&((1<<64)-1)
    return h

def encode(m):
    pieces=[]
    for i,end in enumerate(m['ends']):
        bits=sum(int(a)<<j for j,a in enumerate(m['active'][i]))
        b=BODY.pack(b'TSM1',1,int(m['valid'][i]),round(end*48000),
                    int(m['peak'][i]) if m['valid'][i] else 65535,bits,
                    float(m['total'][i]),float(m['centroid'][i]),*m['bands'][i])
        pieces.append(b+struct.pack('<Q',fnv(b)))
    wire=b''.join(pieces);need(len(wire)==168*len(m['ends']),'168 bytes per monitor group')
    return wire

def validate(wire,m):
    need(len(wire)==168*len(m['ends']),'Telemetry exact length')
    for i in range(len(m['ends'])):
        b=wire[i*168:(i+1)*168];v=BODY.unpack(b[:-8])
        need(fnv(b[:-8])==struct.unpack('<Q',b[-8:])[0],'Telemetry checksum')
        need(v[:3]==(b'TSM1',1,int(m['valid'][i])),'Telemetry header')
        need(v[3]==round(m['ends'][i]*48000),'Telemetry sample time')
        need(v[4]==(int(m['peak'][i]) if m['valid'][i] else 65535),'Telemetry peak')
        need(v[5]==sum(int(a)<<j for j,a in enumerate(m['active'][i])),'Telemetry active mask')
        need(v[6]==m['total'][i] and v[7]==m['centroid'][i],'Telemetry totals')
        need(np.array_equal(np.array(v[8:]),m['bands'][i]),'Telemetry band equality')
    return True
