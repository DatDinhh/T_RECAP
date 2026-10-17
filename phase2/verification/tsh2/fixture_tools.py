"""Project-generated integer stimulus and independent TSP1 byte encoding.

Packet contract implementation admitted from the project's audit_packets.py.
No recorded audio or external dataset is used.
"""
import struct

def synthetic_input():
    state=0x20261017;result=[]
    def triangle(p):return p-16 if p<32 else 48-p
    for i in range(1024):
        state=(1664525*state+1013904223)&0xffffffff
        result.append(12*triangle(i%64)+3*triangle((i*5)%64)+((state>>24)%7)-3)
    return result

def record(frame,threshold,values,keep,sparse):
    if sparse:
        payload=b''.join(struct.pack('<Q',(v<<8)|k) for k,v in enumerate(values) if keep[k]);count=sum(keep)
    else:
        payload=b''.join((v if keep[k] else 0).to_bytes(7,'little') for k,v in enumerate(values));count=129
    header=struct.pack('<IHHIIQQHHI',0x31505354,1,int(sparse),0x00010001,len(payload),frame,threshold,count,1,0)
    padding=b'\0'*(-(48+len(payload))%8);digest=14695981039346656037
    for byte in header+payload+padding:digest=((digest^byte)*1099511628211)&((1<<64)-1)
    return header+struct.pack('<Q',digest)+payload+padding

def packets(rows,threshold,sparse):
    result=bytearray()
    if len(rows)!=1161:raise ValueError('Expected nine complete129-bin frames')
    for frame in range(9):
        bins=rows[frame*129:(frame+1)*129]
        if [int(r['bin_idx']) for r in bins]!=list(range(129)):raise ValueError('Canonical order')
        if any(int(r['frame_idx'])!=frame for r in bins):raise ValueError('Frame ownership')
        result+=record(frame,threshold,[int(r['mag2']) for r in bins],[not int(r['mask']) for r in bins],sparse)
    return bytes(result)
