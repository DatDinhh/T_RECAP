# SPDX-License-Identifier: MIT
"""Render the T-RECAP architecture atlas as SVG and a vector PDF.

Dependencies: reportlab. Diagram content is documentation, not an executable
model. No project model, simulator or FPGA tool is imported or invoked.
"""
from pathlib import Path
import argparse, hashlib, html, json, math
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
import reportlab

W, H = 1600, 1132
C = {
    'ink':'#26364B', 'muted':'#586A80', 'line':'#708299',
    'bg':'#FCFCFE', 'white':'#FFFFFF', 'border':'#D8E0EA',
    'mint':'#DDF2E9', 'mint_d':'#407D6C',
    'blue':'#DFECFA', 'blue_d':'#4D78A8',
    'lav':'#EBE4FA', 'lav_d':'#8066A9',
    'rose':'#F8E0E8', 'rose_d':'#A66882',
    'sand':'#F7ECD5', 'sand_d':'#9C7D3F',
    'gray':'#EBEFF4', 'gray_d':'#65778A',
}
FONT_DIR = Path(reportlab.__file__).parent/'fonts'
pdfmetrics.registerFont(TTFont('Atlas', str(FONT_DIR/'Vera.ttf')))
pdfmetrics.registerFont(TTFont('AtlasBold', str(FONT_DIR/'VeraBd.ttf')))
pdfmetrics.registerFont(pdfmetrics.Font('AtlasMono', 'Courier', 'WinAnsiEncoding'))
FAMILY={'Atlas':'DejaVu Sans, Arial, sans-serif','AtlasBold':'DejaVu Sans, Arial, sans-serif','AtlasMono':'DejaVu Sans Mono, Consolas, monospace'}

def wrap(s, width, size=17, font='Atlas'):
    lines=[]
    for para in s.split('\n'):
        current=''
        for word in para.split():
            trial=(current+' '+word).strip()
            if current and pdfmetrics.stringWidth(trial,font,size)>width:
                lines.append(current); current=word
            else: current=trial
        lines.append(current)
    return lines

class Plate:
    def __init__(self, number, slug, title, subtitle, refs):
        self.number,self.slug,self.title,self.subtitle,self.refs=number,slug,title,subtitle,refs
        self.ops=[]; self.nodes={}; self.warnings=[]
        self.rect(0,0,W,H,C['bg'],None,0)
        self.rect(48,42,7,83,C['lav_d'],None,3)
        self.text(75,57,'T-RECAP   /   ARCHITECTURE ATLAS',15,C['muted'],'AtlasBold')
        self.text(75,104,title,39,C['ink'],'AtlasBold')
        self.text(75,139,subtitle,18,C['muted'])
        self.text(1525,83,f'{number:02d}',35,C['lav_d'],'AtlasBold','end')
        self.line([(48,163),(1552,163)],C['border'],1)

    def rect(self,x,y,w,h,fill,stroke=C['border'],r=15,sw=1.3,dash=None):
        self.ops.append(('rect',x,y,w,h,fill,stroke,r,sw,dash))
    def text(self,x,y,s,size=17,color=None,font='Atlas',anchor='start'):
        color=color or C['ink']
        width=pdfmetrics.stringWidth(s,font,size)
        left=x-width if anchor=='end' else x-width/2 if anchor=='middle' else x
        if left < 0 or left+width>W+1: self.warnings.append(f'text outside page: {s}')
        self.ops.append(('text',x,y,s,size,color,font,anchor))
    def lines(self,x,y,lines,size=17,color=None,font='Atlas',gap=None):
        for i,s in enumerate(lines): self.text(x,y+i*(gap or size*1.4),s,size,color,font)
    def line(self,pts,color=None,sw=2.1,dash=None,arrow=False):
        color=color or C['line']; self.ops.append(('line',pts,color,sw,dash))
        if arrow:
            (ax,ay),(bx,by)=pts[-2:]; dx,dy=bx-ax,by-ay; norm=math.hypot(dx,dy)
            dx,dy=dx/norm,dy/norm
            self.ops.append(('poly',[(bx,by),(bx-10*dx+4.5*dy,by-10*dy-4.5*dx),(bx-10*dx-4.5*dy,by-10*dy+4.5*dx)],color))
    def edge(self,pts,label=None,lx=None,ly=None,kind='data',color=None):
        col=color or (C['lav_d'] if kind=='control' else C['rose_d'] if kind=='tap' else C['line'])
        self.line(pts,col,2.2,[8,6] if kind=='control' else [3,5] if kind=='tap' else None,True)
        if label:
            lx=lx if lx is not None else (pts[0][0]+pts[-1][0])/2
            ly=ly if ly is not None else (pts[0][1]+pts[-1][1])/2-9
            wid=pdfmetrics.stringWidth(label,'Atlas',14)
            self.rect(lx-wid/2-5,ly-15,wid+10,21,C['bg'],None,4)
            self.text(lx,ly,label,14,col,anchor='middle')
    def panel(self,x,y,w,h,label,tone='blue',tag=None):
        self.rect(x,y,w,h,C['white'],C['border'],22)
        self.rect(x+1,y+1,w-2,45,C[tone],None,21)
        self.rect(x+1,y+25,w-2,21,C[tone],None,0)
        self.text(x+22,y+30,label,18,C[tone+'_d'],'AtlasBold')
        if tag:self.text(x+w-20,y+29,tag,13,C[tone+'_d'],anchor='end')
    def node(self,key,x,y,w,h,title,body=(),code=None,tone='blue'):
        self.rect(x+1,y+3,w,h,'#EFF1F6',None,14)
        self.rect(x,y,w,h,C[tone],C[tone+'_d'],14,1.15)
        yy=y+30
        titlelines=wrap(title,w-34,20,'AtlasBold')
        self.lines(x+17,yy,titlelines,20,C['ink'],'AtlasBold',25)
        yy+=25*len(titlelines)+4
        bl=[]
        for b in body:bl.extend(wrap(b,w-34,16))
        self.lines(x+17,yy,bl,16,C['ink'],gap=22)
        bottom=yy+(len(bl)-1)*22 if bl else yy-22
        if code:
            codes=code.split('\n'); cy=y+h-15-(len(codes)-1)*16
            if bottom+17>cy:self.warnings.append(f'node text collision {key}: body {bottom} code {cy}')
            for i,c in enumerate(codes):
                if pdfmetrics.stringWidth(c,'AtlasMono',11.5)>w-34:self.warnings.append(f'code too wide {key}: {c}')
                self.text(x+17,cy+i*16,c,11.5,C[tone+'_d'],'AtlasMono')
        elif bottom>y+h-13:self.warnings.append(f'node body outside {key}')
        self.nodes[key]=(x,y,w,h)
    def p(self,key,side='r'):
        x,y,w,h=self.nodes[key]
        return {'l':(x,y+h/2),'r':(x+w,y+h/2),'t':(x+w/2,y),'b':(x+w/2,y+h)}[side]
    def connect(self,a,b,sa='r',sb='l',**kw):self.edge([self.p(a,sa),self.p(b,sb)],**kw)
    def note(self,x,y,w,h,title,body,tone='gray'):
        self.rect(x,y,w,h,C[tone],None,13)
        self.text(x+19,y+29,title,17,C[tone+'_d'],'AtlasBold')
        ls=wrap(body,w-38,16)
        self.lines(x+19,y+55,ls,16,C['ink'],gap=22)
        if y+55+(len(ls)-1)*22>y+h-12:self.warnings.append(f'note overflow: {title}')
    def footer(self):
        y=1034
        self.line([(48,y),(1552,y)],C['border'],1)
        for x,label,tone in [(65,'Sources','mint'),(250,'DSP / configuration','lav'),(570,'Telemetry','rose'),(780,'HPS / host','sand'),(1000,'Platform / memory','blue')]:
            self.rect(x,y+18,14,14,C[tone],C[tone+'_d'],4,0.8)
            self.text(x+23,y+30,label,13.5,C['muted'])
        self.line([(1290,y+25),(1328,y+25)],C['line'],2)
        self.text(1337,y+30,'data',13,C['muted'])
        self.line([(1412,y+25),(1450,y+25)],C['lav_d'],2,[7,5])
        self.text(1459,y+30,'control',13,C['muted'])
        self.text(65,1090,'SOURCE: '+ '  |  '.join(Path(p).name for p in self.refs[:3]),12,C['muted'])
        self.text(65,1114,'Architecture source snapshot 2026-09-14  /  Implementation structure; hardware operation is a separate milestone.',12,C['muted'])
        self.text(1535,1114,f'T-RECAP  /  {self.number:02d}',12,C['muted'],anchor='end')

def plate1():
    p=Plate(1,'01-system-overview','System architecture','A fixed-point FPGA processing path with independent observation, host transport and control.',
        ['rtl/platform/de1soc/de1_soc_trecap_top.sv','rtl/top/trecap_de1soc_full_top.sv','docs/architecture/architecture_design.md'])
    p.panel(55,194,300,670,'INPUTS + SOURCE LOGIC','mint')
    p.panel(395,194,755,670,'FPGA PROCESSING','blue','5CSEMA5F31C6  /  50 MHz')
    p.panel(1190,194,355,670,'HPS + HOST','sand')
    for key,y,title,body,code in [
        ('bram',264,'BRAM replay',['FPGA ROM: 4096 x 12-bit','48 ksample/s default profile'],'trecap_bram_replay_source'),
        ('audio',414,'WM8731 / FPGA RX',['Stereo I2S -> async FIFO','Adapter -> signed 12-bit'],'audio_codec_wrapper'),
        ('adc',564,'LTC2308 -> FPGA',['100 ksample/s continuous','Manual capture: diagnostics'],'adc_wrapper'),
        ('diag',714,'Diagnostic source',['Ramp / impulse / constant','FPGA synthetic generator'],'trecap_diagnostic_source')]:
        p.node(key,75,y,260,130,title,body,code,'mint')
    p.node('mux',445,280,285,145,'Source / epoch owner',['Four sources -> one stream','Atomic sample + index'], 'trecap_source_core_integration','mint')
    p.node('dsp',800,280,300,145,'STFT / mask / WOLA',['256-point FFT; hop = 128','Reconstruct signed 12-bit y[n]'],'trecap_core_top','lav')
    p.node('tel',800,500,300,150,'Telemetry formatter',['WAVE / SPEC / METRICS','STATUS + bounded record FIFO'],'trecap_telemetry_top','rose')
    p.node('csr',445,500,285,150,'CSR + safe commits',['Threshold, source, telemetry','Replay control + status'],'trecap_hps_bridge_top','lav')
    p.node('ddr',800,713,300,125,'DDR record writer',['64-bit Avalon-MM master','Publish complete records only'],'trecap_ddr_ring_writer','blue')
    p.node('hps',1210,280,315,145,'HPS Linux runtime',['Reserved DDR ring consumer','CSR control + command server'],'sw/hps/','sand')
    p.node('ddrm',1210,505,315,135,'Shared HPS DDR3',['Reserved 32 MiB telemetry ring','FPGA writes; HPS consumes'],None,'blue')
    p.node('pc',1210,708,315,135,'PC dashboard',['Waveform / spectrum / metrics','UDP telemetry + command ACK'],'sw/pc_dashboard/','sand')
    for s in ['bram','audio','adc','diag']:
        a=p.p(s); p.edge([a,(376,a[1]),(376,352),(445,352)])
    p.connect('mux','dsp',label='12-bit',lx=766,ly=340)
    p.connect('dsp','tel','b','t',kind='tap',label='taps',lx=995,ly=448)
    p.connect('tel','ddr','b','t',label='record stream',lx=950,ly=687)
    p.edge([(1100,775),(1168,775),(1168,572),(1210,572)],label='data64',lx=1168,ly=748)
    p.connect('ddrm','hps','t','b',label='committed records',lx=1368,ly=465)
    p.edge([(1525,354),(1566,354),(1566,775),(1525,775)],label='UDP',lx=1560,ly=690)
    p.edge([(1210,322),(1173,322),(1173,471),(588,471),(588,500)],kind='control',label='HPS lightweight bridge / 32-bit CSR',lx=865,ly=471)
    p.connect('csr','mux','t','b',kind='control')
    p.edge([(1525,808),(1582,808),(1582,402),(1525,402)],kind='control')
    p.text(462,685,'Control routes: see plate 07',14,C['lav_d'])
    p.note(55,890,490,112,'OFFLINE REFERENCE MODEL','sw/reference_model/ defines the arithmetic reference. Frozen coefficients populate FPGA ROMs.','gray')
    p.note(570,890,510,112,'CORE OWNERSHIP','FFT, mask, IFFT and reconstruction execute in FPGA. Telemetry congestion does not drive core ready.','lav')
    p.note(1105,890,440,112,'DEFAULT BRING-UP PROFILE','BRAM zero vector, STATUS-only telemetry, manual replay start; LINE-OUT disabled.','mint')
    return p

def plate2():
    p=Plate(2,'02-dsp-pipeline','DSP datapath and frame ownership','The numerical path preserves the fixed 256 / 128 / 384 geometry and frame-owned threshold snapshots.',
        ['rtl/core/trecap_core_top.sv','spec/generated/core_config.json','docs/architecture/storage_schedule.md'])
    xs=[65,450,835,1220]; ww=315
    specs=[
        ('ring',xs[0],235,'Input ring + scheduler',['Signed 12-bit x[n]','512 x 76-bit tagged history','L=256; trigger each H=128'],'trecap_input_ring\ntrecap_frame_scheduler'),
        ('window',xs[1],235,'Analysis window',['Frozen sqrt(Hann), Q15','s12 x u16 -> s27; no shift'],'trecap_analysis_window'),
        ('fft',xs[2],235,'Forward FFT',['256 points, radix-2 DIT','28-bit complex; total /256'],'trecap_fft256'),
        ('can',xs[3],235,'Hermitian canonicalizer',['Real DC / Nyquist bins','Mirrored bins become conjugate'],'trecap_hermitian_canonicalizer'),
        ('wola',xs[0],515,'Synthesis + WOLA',['36-bit IFFT x window','37-bit OLA -> signed 12-bit y'],'trecap_synthesis_wola'),
        ('ifft',xs[1],515,'Inverse FFT',['256 points, radix-2 DIT','36-bit complex; no stage /2'],'trecap_ifft256'),
        ('builder',xs[2],515,'Masked spectrum',['Keep or zero canonical bins','Preserve conjugate symmetry'],'trecap_spectrum_mask_builder'),
        ('mask',xs[3],515,'Magnitude + threshold',['mag2 = Re^2 + Im^2: 56 bits','129 bins; DC protected','Suppress < THR2; equality kept'],'trecap_mag2_mask')]
    for k,x,y,t,b,c in specs:p.node(k,x,y,ww,155,t,b,c,'lav')
    for a,b in [('ring','window'),('window','fft'),('fft','can')]:p.connect(a,b)
    p.connect('can','mask','b','t',label='canonical complex bins',lx=1378,ly=457)
    for a,b in [('mask','builder'),('builder','ifft'),('ifft','wola')]:p.connect(a,b,'l','r')
    p.node('meta',535,415,595,68,'Frame metadata: 4 x 120 bits',[],None,'sand')
    p.text(557,466,'{frame_idx[63:0], THR2[55:0]} captured at frame admission',14,C['sand_d'])
    p.edge([(223,390),(223,448),(535,448)],kind='control')
    p.edge([(1130,448),(1179,448),(1179,558),(1220,558)],kind='control')
    p.node('delay',65,760,410,147,'Delayed input history',['1024 x 76-bit tagged history','D = L + G = 384','Align original x[n-D] with y[n]'],'trecap_delay_error_metrics','blue')
    p.node('metric',585,760,450,147,'Error and aggregate metrics',['e[n] = x[n-D] - y[n]','Sample/error tap + error aggregates'],'trecap_delay_error_metrics','rose')
    p.note(1145,760,390,147,'SCHEDULE BUDGET','18,000 fabric clocks per frame (360 us). At 100 ksample/s: 64,000 clocks per hop.','lav')
    p.edge([(223,235),(223,209),(39,209),(39,834),(65,834)],label='accepted input',lx=118,ly=718)
    p.connect('delay','metric',label='x[n-D]',lx=530,ly=824)
    p.edge([(223,670),(223,711),(810,711),(810,760)],label='y[n]',lx=623,ly=704)
    p.note(65,939,715,67,'ARITHMETIC CONTRACT','Round to nearest, ties away from zero; saturation at defined boundaries.','gray')
    p.note(810,939,725,67,'ALIGNMENT','D = 384 samples: 8 ms at 48 ksample/s; 3.84 ms at 100 ksample/s.','gray')
    return p

def plate3():
    p=Plate(3,'03-transform-memory','Transform engines and storage','Separate iterative FFT and IFFT engines reuse one registered butterfly per engine.',
        ['rtl/fft/trecap_fft_stage.sv','docs/architecture/transform_microarchitecture.md','docs/architecture/storage_schedule.md'])
    p.panel(55,194,725,424,'EACH TRANSFORM ENGINE','lav')
    p.node('load',80,270,195,128,'Load',['Bit-reversed input','256 accepts'],None,'lav')
    p.node('ram',320,270,225,128,'Frame RAM',['Synchronous M10K','Two complex ports'],None,'blue')
    p.node('out',590,270,165,128,'Output',['Natural order','2 clocks/bin'],None,'lav')
    p.node('bf',290,459,305,132,'Registered butterfly',['8 stages x 128 butterflies','7 edges per butterfly'],'trecap_fft_stage','lav')
    p.node('rom',80,459,160,132,'Twiddles',['2 x 256 x 17','Frozen Q15'],None,'blue')
    p.connect('load','ram');p.connect('ram','out');p.connect('rom','bf')
    p.edge([(378,398),(378,433),(370,433),(370,459)])
    p.edge([(510,459),(510,421),(492,421),(492,398)])
    p.panel(815,194,730,424,'WIDTHS + ENGINE SERVICE','blue')
    rows=[('Work RAM geometry','256 x 56','256 x 72'),('Data / twiddle component','28 / 17 bits','36 / 17 bits'),('Four signed products','45 bits each','53 bits each'),('Full product sum','47 bits','55 bits'),('Butterfly sum','30 bits','38 bits'),('Final stage shift','1 bit','0 bits')]
    p.text(844,274,'QUANTITY',13,C['muted'],'AtlasBold');p.text(1188,274,'FFT',14,C['lav_d'],'AtlasBold');p.text(1380,274,'IFFT',14,C['lav_d'],'AtlasBold')
    for i,(a,b,c) in enumerate(rows):
        y=311+i*39;p.line([(839,y+13),(1520,y+13)],C['border'],0.8)
        p.text(844,y,a,16);p.text(1165,y,b,16);p.text(1370,y,c,16)
    p.text(844,576,'256 load + 7168 compute + 512 output = 7936 clocks',17,C['lav_d'],'AtlasBold')
    p.text(844,600,'Local count assumes a complete, available frame and a ready output.',13,C['muted'])
    p.panel(55,648,1490,169,'SEVEN-EDGE BUTTERFLY TRANSACTION','lav')
    steps=[('1','RAM + ROM','read'),('2','Four DSP','products'),('3','Full complex','sum / difference'),('4','Q15 product','round + saturate'),('5','A + product','A - product'),('6','Stage result','round + saturate'),('7','Write A / B','advance index')]
    for i,(num,a,b) in enumerate(steps):
        x=78+i*210
        p.rect(x,714,186,79,C['lav'],None,12)
        p.text(x+13,739,num,18,C['lav_d'],'AtlasBold');p.text(x+43,739,a,15,C['ink'],'AtlasBold');p.text(x+43,765,b,14)
        if i<6:p.edge([(x+186,754),(x+205,754)])
    p.note(55,847,465,152,'SYNCHRONOUS STORE OWNERSHIP','Load, compute and output phases do not overlap inside one engine. Reset invalidates ownership; frame RAM payload is not bulk reset.','blue')
    p.note(545,847,485,152,'OTHER CORE STORES','Canonicalizer 256 x 56; input history 512 x 76; delayed history 1024 x 76; WOLA frame 256 x 36 and OLA ring 384 x 37.','blue')
    p.note(1055,847,490,152,'FIXED COEFFICIENT PROVENANCE','Analysis window: combinational 256 x 16 ROM. Synthesis: separate synchronous 256 x 16 M10K. Twiddles: 256 x 17 per component; frozen artifacts.','gray')
    return p

# Additional plates are defined below; all use the same geometry and palette.

def plate4():
    p=Plate(4,'04-sources-epochs','Sample sources and stream epochs','Four physical or synthetic sources share one normalized interface and one DSP history owner.',
        ['rtl/top/trecap_source_core_integration.sv','rtl/sources/trecap_source_mux.sv','docs/architecture/source_health.md'])
    columns=[80,460,840,1220]
    for x,label in zip(columns,['MODE 0 / REPLAY','MODE 1 / ADC','MODE 2 / AUDIO','MODE 3 / DIAGNOSTIC']):
        p.text(x,218,label,15,C['mint_d'],'AtlasBold')
    p.node('r0',80,245,300,133,'Frozen input ROM',['4096 x signed 12-bit','48 ksample/s default tick'],'trecap_bram_replay_source','mint')
    p.node('r1',460,245,300,133,'LTC2308 controller',['Unsigned 12-bit, 100 kS/s','2.5 MHz registered serial clock'],'adc_wrapper','mint')
    p.node('r2',840,245,300,133,'WM8731 receiver',['I2S stereo; nominal 48 kframe/s','RX async FIFO: 8 x 96 bits'],'audio_codec_wrapper','mint')
    p.node('r3',1220,245,300,133,'Pattern generator',['Ramp / impulse / constant','Alternating / LFSR / periodic'],'trecap_diagnostic_source','mint')
    p.node('a0',80,444,300,150,'Replay sequencer',['Finite input + paced zero flush','Explicit start / completion'],'trecap_source_core_integration','mint')
    p.node('a1',460,444,300,150,'ADC normalization',['Raw - 2048 -> signed 12-bit','1 pending sample; sequence64'],'trecap_adc_adapter','mint')
    p.node('a2',840,444,300,150,'Audio normalization',['Select left; 1 pending sample','Round >>4; saturate to 12 bits'],'trecap_audio_adapter','mint')
    p.node('a3',1220,444,300,150,'Diagnostic selection',['SW[2:0]; 48 ksample/s','Amplitude / pattern controls'],'trecap_diagnostic_source','mint')
    for i in range(4):p.connect(f'r{i}',f'a{i}','b','t')
    p.node('mux',453,677,690,107,'4:1 mux -> selected-stream analysis / tail routing',['{sample[11:0], sample_index[63:0], valid} / ready'],'trecap_source_mux','mint')
    for i in range(4):
        a=p.p(f'a{i}','b');p.edge([a,(a[0],633),(798,633),(798,677)])
    p.node('core',453,863,690,132,'One mathematical core',['Frame history and delayed reference accept together','Board y_ready = 1; source changes invalidate DSP epoch'],'trecap_core_top','lav')
    p.connect('mux','core','b','t',label='signed 12-bit + absolute index',lx=798,ly=831)
    p.note(65,677,340,146,'MANUAL ADC MODE','SW[7]=1 + KEY[2]: raw conversion diagnostics only. No sample enters STFT/WOLA; periodic DSP rate is zero.','sand')
    p.note(65,850,340,145,'REPLAY GEOMETRY','After source selection: 4096 input samples -> 33 frames; 4608 output samples. Final 384 tokens go only to WOLA drain.','gray')
    p.note(1190,677,345,146,'RECOVERY SEQUENCE','Capture stop acknowledged -> settle 4096 clocks -> first sample -> run. Sequence/drop/timeout faults stop the epoch.','sand')
    p.note(1190,850,345,145,'OPTIONAL LINE-OUT','y -> mono L/R -> TX FIFO 512 x 33 -> DAC. Best effort; disabled in all shipped build profiles.','gray')
    return p

def plate5():
    p=Plate(5,'05-telemetry','Observation and telemetry records','Core taps are valid-only: packet congestion can discard telemetry without stalling numerical processing.',
        ['rtl/telemetry/trecap_telemetry_top.sv','rtl/telemetry/trecap_packet_fifo.sv','spec/generated/packet_layouts.json'])
    p.node('tap',65,210,1470,80,'Core observation taps: samples / unique bins / frame statistics / error aggregates',[],None,'lav')
    p.text(84,271,'Authoritative core counters + source status + synthesized STATUS / METRICS cadence',16,C['lav_d'])
    packetnodes=[
        ('wave',65,'WAVE',['x_delayed / y / error: int16','16 + 6 x nsamp payload bytes','nsamp <= 192; stride selection'],'trecap_wave_packetizer'),
        ('spec',450,'SPEC129 / SPEC64',['129 bins / 64 buckets','287 / 268 payload bytes','clip16(mag2 >> spec_shift)'],'trecap_spec_packetizer'),
        ('metrics',835,'METRICS',['Error + eligible-bin aggregates','56 payload bytes','Core totals; explicit metric epoch'],'trecap_metrics_packetizer'),
        ('status',1220,'STATUS',['Core + transport state','72 payload bytes','Current CSR threshold snapshot'],'trecap_status_packetizer')]
    for k,x,t,b,c in packetnodes:
        p.node(k,x,372,315,178,t,b,c,'rose')
        p.edge([(x+157,290),(x+157,372)],kind='tap')
    p.node('sched',355,642,395,152,'Record-atomic scheduler',['STATUS > METRICS > SPEC > WAVE','One candidate owns all its beats'],'trecap_packet_scheduler','rose')
    p.node('fifo',990,642,545,152,'Bounded packet FIFO + priority drops',['8 queued records + 1 staging ownership slot','Descriptors move; payload stays in M10K RAM'],'trecap_packet_fifo / trecap_priority_dropper','rose')
    for k in ['wave','spec','metrics','status']:
        a=p.p(k,'b');p.edge([a,(a[0],592),(550,592),(550,642)])
    p.connect('sched','fifo',label='payload32 + keep4 + last',lx=870,ly=703)
    p.note(65,850,455,150,'FORMATTED RECORD BOUNDARY','Per-beat valid/ready; stable metadata for a whole record. The common header and DDR padding are added downstream.','rose')
    p.note(545,850,480,150,'LOSS AND EPOCH OWNERSHIP','Packetizer/scheduler/FIFO losses share packet_fifo_drop_count. DDR losses use dma_drop_count. Epoch changes discard partial collections.','rose')
    p.note(1050,850,485,150,'RECORDS -> DDR BUILDER','32-byte common header; complete record <= 1200 UDP bytes. DDR storage rounds total length to a 64-byte boundary.','blue')
    p.edge([(1262,794),(1262,850)],label='accepted record',lx=1378,ly=828)
    return p

def plate6():
    p=Plate(6,'06-ddr-hps-transport','DDR transport and pointer ownership','FPGA produces committed records; Linux consumes them from a reserved, noncached ring.',
        ['rtl/hps_bridge/trecap_ddr_ring_writer.sv','rtl/platform/de1soc/platform_designer_wrapper.sv','docs/architecture/de1soc_hps_transport.md'])
    p.panel(55,195,1010,407,'FPGA PRODUCER / 50 MHz','blue')
    p.node('record',80,272,275,138,'Record builder',['Header32 + payload + padding','64-bit DDR write stream'],'trecap_ddr_record_builder','rose')
    p.node('writer',400,272,290,138,'Ring writer + master',['Free-space / WRAP decisions','Waitrequest; record commit'],'trecap_ddr_ring_writer\ntrecap_avmm_write_master','blue')
    p.node('guard',735,272,305,138,'Platform address guard',['Address64 / data64 / BE8','Require address < 0x40000000'],'platform_designer_wrapper','blue')
    p.connect('record','writer');p.connect('writer','guard')
    p.note(80,451,960,122,'WRITE RESPONSE SEMANTICS','The wrapper returns registered OKAY / SLVERR for local validation and generated-bus acceptance. OKAY does not indicate physical DRAM completion. Publish W only after the record write sequence succeeds.','gray')
    p.node('qsys',1120,272,410,138,'Generated HPS DDR path',['Avalon bridge: address32 / data64','f2h_sdram0 -> hard DDR controller'],'trecap_f2h_sdram_bridge','blue')
    p.connect('guard','qsys',label='1 beat',lx=1080,ly=332)
    p.node('ring',1120,475,410,127,'Reserved DDR ring: 32 MiB',['0x3E000000 <= address < 0x40000000','Inside the 1 GiB HPS DDR3 space'],None,'blue')
    p.connect('qsys','ring','b','t')
    p.panel(55,640,730,360,'MONOTONIC 64-BIT OWNERS','blue')
    p.node('w',80,716,295,116,'Producer W',['FPGA owns publication','HPS reads coherent snapshot'],'trecap_ring_pointer_ctrl','blue')
    p.node('rd',460,716,295,116,'Consumer Rd',['HPS commits consumed extent','FPGA reads committed pointer'],'ring_reader.c / csr_map.c','sand')
    p.text(418,748,'W snapshot',12,C['blue_d'],anchor='middle')
    p.edge([(375,770),(460,770)],kind='control')
    p.text(418,807,'Rd commit',12,C['sand_d'],anchor='middle')
    p.edge([(460,791),(375,791)],kind='control')
    p.text(81,870,'64-byte record alignment + 64-byte guard; no record straddles end.',16)
    p.text(81,899,'WRAP consumes the remaining tail and is not sent over UDP.',16)
    p.text(81,925,'Init: disable/drain -> transport reset -> ring config -> Rd=0.',15,C['blue_d'])
    p.text(81,950,'Check W=0; enable the writer and telemetry.',15,C['blue_d'])
    p.text(81,979,'Physical / FPGA bus addresses are distinct from userspace pointers.',14,C['muted'])
    p.node('linux',865,688,330,145,'Linux ring mapping',['Read-only /dev/trecap-ring','Noncached mmap; one consumer'],'platform/de1soc/linux/driver/\ntrecap_platform.c','sand')
    p.node('stream',1240,688,290,145,'HPS ring reader',['Validate committed records','UDP copy; omit DDR padding'],'trecap_udp_streamer','sand')
    p.edge([(1325,602),(1325,641),(1029,641),(1029,688)],label='mapped bytes',lx=1144,ly=632)
    p.connect('linux','stream')
    p.node('dash',865,906,665,93,'PC dashboard / UDP port 5005',['Typed records; sequence / loss tracking; wave, spectrum and metrics'],'sw/pc_dashboard/','sand')
    p.edge([(1385,833),(1385,870),(1197,870),(1197,906)],label='UDP header + payload',lx=1288,ly=863)
    return p

def plate7():
    p=Plate(7,'07-control-plane','Commands, CSRs and safe configuration','Control moves from the desktop to HPS software, then across the lightweight bridge into explicit FPGA owners.',
        ['docs/architecture/de1soc_command_path.md','rtl/hps_bridge/trecap_csr_bank.sv','docs/architecture/platform_grant.md'])
    p.node('pc',65,237,315,144,'PC command client',['Protocol v2; 28-byte request','Default peer source port 5007'],'sw/pc_dashboard/','sand')
    p.node('hps',450,237,315,144,'HPS command dispatcher',['UDP 5006; validate bound peer','Sequence ledger + result cache'],'sw/hps/','sand')
    p.node('adapt',835,237,315,144,'LW bridge + CSR adapter',['AXI -> Avalon-MM; data32','Full address21 decode before leaf'],'trecap_avmm_csr_adapter','blue')
    p.node('bank',1220,237,315,144,'CSR bank / ABI 1.8',['Base 0xFF200000; 4 KiB window','Aligned, full-word, single-beat'],'trecap_csr_bank','lav')
    for a,b in [('pc','hps'),('hps','adapt'),('adapt','bank')]:p.connect(a,b,kind='control')
    p.edge([(608,381),(608,426),(222,426),(222,381)],kind='control',label='32-byte v2 result',lx=414,ly=426)
    p.text(714,428,'HPS result: APPLIED / NOOP / REJECTED / FAILED',17,C['sand_d'])
    p.panel(65,481,1470,269,'CONFIGURATION AND ACTION OWNERS','lav')
    opts=[
        ('thr',85,'Threshold / source',['THR2: safe apply + frame snapshot','Source: source-safe boundary'],'trecap_csr_shadow_commit'),
        ('tel',455,'Telemetry controls',['Packet enable / spectrum mode','Decimation and capture settings'],'trecap_telemetry_top'),
        ('ptr',825,'Ring pointers',['Base / size / Rd commit','W snapshot; transport lifecycle'],'trecap_ring_pointer_ctrl'),
        ('replay',1195,'Replay + source health',['Explicit replay accept / reject','Health snapshot 0x100..0x180'],'trecap_source_core_\nintegration')]
    for k,x,t,b,c in opts:
        p.node(k,x,567,320,155,t,b,c,'lav')
        p.edge([(1378,381),(1378,544),(x+160,544),(x+160,567)],kind='control')
    p.note(65,800,460,196,'AT-MOST-ONCE COMMAND EFFECT','Identical retries resend cached result bytes. Stale or conflicting sequence numbers are rejected. Applied results require command-specific writes and readbacks. PING remains a diagnostic exception.','sand')
    p.note(555,800,490,196,'CODEC OWNERSHIP GRANT','Linux driver holds HPS_GPIO48 low and confirms readback, selecting the FPGA I2C path. HPS then sets PLATFORM_CONTROL[0] at 0x184. The FPGA reads this grant, not the dedicated GPIO48 pin.','blue')
    p.note(1075,800,460,196,'CONFIGURATION CONSISTENCY','A shared runtime profile binds FPGA parameters to HPS startup. Telemetry cadence is synthesized. All profiles reset to BRAM; HPS commits ADC or audio selection after startup.','lav')
    return p

def plate8():
    p=Plate(8,'08-clocks-reset-cdc','Clock, reset and CDC boundaries','The 50 MHz fabric owns numerical processing; external audio serialization crosses through dedicated async FIFOs.',
        ['rtl/platform/de1soc/de1_soc_trecap_top.sv','rtl/platform/de1soc/audio_codec_wrapper.sv','config/boards/physical_timing.json'])
    p.panel(55,194,980,584,'FABRIC / CLOCK_50 = 50 MHz / 20 ns','blue')
    p.panel(1080,194,465,584,'CODEC + FPGA SERIAL LOGIC','mint')
    p.node('reset',80,270,355,149,'Reset controller',['KEY[0] release held 20 ms','Combine h2f_reset_n; sync release'],'clock_reset_ctrl','blue')
    p.node('fabric',505,270,505,149,'One fabric reset and clock domain',['Sources / DSP / telemetry / CSRs / DDR writer','Sample and status ticks are clock enables'],'rst_n_platform / CLOCK_50','blue')
    p.connect('reset','fabric',kind='control')
    p.node('rx',595,486,415,112,'RX async FIFO: 8 x 96',['Stereo samples + sequence64','BCLK rising edge -> fabric50'],None,'mint')
    p.node('tx',595,636,415,112,'Optional TX FIFO: 512 x 33',['Epoch + duplicated mono L/R','FIFO read: BCLK rising edge'],None,'mint')
    p.node('codec',1105,486,415,112,'FPGA I2S receiver',['Capture at BCLK rising edge','Nominal 48 kframe/s, 16-bit stereo'],None,'mint')
    p.node('dac',1105,636,415,112,'I2S / TX monitor',['Launch data on BCLK falling edge','Best effort; profile disabled'],None,'mint')
    p.connect('codec','rx','l','r');p.connect('tx','dac')
    p.edge([(802,486),(802,419)],label='input',lx=901,ly=472)
    p.edge([(557,419),(557,692),(595,692)],label='y[n]',lx=552,ly=614)
    p.node('pll',80,486,425,116,'Audio PLL from CLOCK_50',['AUD_XCK nominal 12.288 MHz','Feeds codec; does not clock the DSP'],'audio_pll_wrapper','blue')
    p.node('init',80,636,425,116,'Codec I2C initialization',['PLL supported + lock + HPS grant','100 kHz I2C; codec address 0x1A'],'audio_codec_i2c_init','blue')
    p.connect('pll','init','b','t',kind='control')
    p.node('clock',1105,270,415,149,'WM8731 clock generation',['Receives AUD_XCK from FPGA PLL','Drives BCLK / LRCK','Nominal BCLK = 3.072 MHz'],'WM8731 / external board codec','mint')
    p.edge([(293,486),(293,451),(1061,451),(1061,344),(1105,344)],label='AUD_XCK',lx=642,ly=451)
    p.connect('clock','codec','b','t')
    p.note(55,821,475,177,'ASYNCHRONOUS SINGLE-BIT INPUTS','ADC_DOUT and I2C ACK data enter preserved 2FF fabric synchronizers. ADC_SCLK is a registered output from the 50 MHz FSM; it never clocks internal DSP logic.','blue')
    p.note(555,821,485,177,'FIFO CROSSING CONTRACT','Gray pointers and BCLK reset release use at least 2 synchronization stages. Pointer route <= 20 ns; Gray skew <= 10 ns; payload route <= 20 ns. FIFO ownership transfers payload.','mint')
    p.note(1065,821,480,177,'HPS AND PHYSICAL CLOCKS','HPS DDR/peripheral clocks remain generated-system owned. No fabric reset feeds back into HPS reset. Audio frequencies are nominal design rates, not board measurements.','gray')
    return p

def svg_document(plate):
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
         '<title id="title">'+html.escape(plate.title)+'</title>',
         '<desc id="desc">'+html.escape(plate.subtitle)+'</desc>']
    for op in plate.ops:
        if op[0]=='rect':
            _,x,y,w,h,fill,stroke,r,sw,dash=op
            ds=f' stroke-dasharray="{",".join(map(str,dash))}"' if dash else ''
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill or "none"}" stroke="{stroke or "none"}" stroke-width="{sw}"{ds}/>')
        elif op[0]=='text':
            _,x,y,s,size,color,font,anchor=op
            weight='700' if font=='AtlasBold' else '400'
            out.append(f'<text x="{x}" y="{y}" font-family="{FAMILY[font]}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{html.escape(s)}</text>')
        elif op[0]=='line':
            _,pts,color,sw,dash=op; ds=f' stroke-dasharray="{",".join(map(str,dash))}"' if dash else ''
            out.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"{ds}/>')
        elif op[0]=='poly':
            _,pts,color=op;out.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="{color}"/>')
    out.append('</svg>');return '\n'.join(out)+'\n'

def pdf_page(c,p):
    c.saveState();c.scale(1190.55/W,841.89/H)
    for op in p.ops:
        if op[0]=='rect':
            _,x,y,w,h,fill,stroke,r,sw,dash=op
            if fill:c.setFillColor(HexColor(fill))
            if stroke:c.setStrokeColor(HexColor(stroke))
            c.setLineWidth(sw);c.setDash(dash or [])
            c.roundRect(x,H-y-h,w,h,r,stroke=bool(stroke),fill=bool(fill))
        elif op[0]=='text':
            _,x,y,s,size,color,font,anchor=op;c.setFont(font,size);c.setFillColor(HexColor(color))
            {'start':c.drawString,'end':c.drawRightString,'middle':c.drawCentredString}[anchor](x,H-y,s)
        elif op[0]=='line':
            _,pts,color,sw,dash=op;c.setStrokeColor(HexColor(color));c.setLineWidth(sw);c.setDash(dash or []);c.setLineJoin(1);c.setLineCap(1)
            path=c.beginPath();path.moveTo(pts[0][0],H-pts[0][1])
            for x,y in pts[1:]:path.lineTo(x,H-y)
            c.drawPath(path)
        elif op[0]=='poly':
            _,pts,color=op;c.setFillColor(HexColor(color));path=c.beginPath();path.moveTo(pts[0][0],H-pts[0][1])
            for x,y in pts[1:]:path.lineTo(x,H-y)
            path.close();c.drawPath(path,stroke=0,fill=1)
    c.restoreState();c.showPage()

def viewer(plates):
    buttons='\n'.join(f'<button type="button" data-page="{i}" aria-pressed="{str(i==0).lower()}"><span>{p.number:02}</span>{html.escape(p.title)}</button>' for i,p in enumerate(plates))
    data=json.dumps([{'file':p.slug+'.svg','title':p.title,'subtitle':p.subtitle} for p in plates])
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>T-RECAP Architecture Atlas</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6fa;color:#26364b;font-family:Arial,sans-serif}header{padding:26px 34px;background:#fcfcfe;border-bottom:1px solid #d8e0ea;display:flex;align-items:center;justify-content:space-between;gap:20px}h1{font-size:25px;margin:4px 0}header small{color:#8066a9;letter-spacing:2px;font-size:11px}header p{margin:7px 0 0;color:#586a80;font-size:14px}.links{display:flex;gap:10px}a,button{color:inherit}a{padding:10px 15px;background:#ebe4fa;border-radius:9px;text-decoration:none;font-size:13px}main{display:grid;grid-template-columns:272px 1fr;min-height:calc(100vh - 122px)}nav{padding:22px 15px;background:#fcfcfe;border-right:1px solid #d8e0ea}nav button{display:flex;gap:12px;text-align:left;width:100%;padding:15px 11px;margin-bottom:7px;border:1px solid transparent;background:none;border-radius:11px;cursor:pointer;line-height:1.45;font-size:13px}nav button span{color:#8066a9;font-weight:700}nav button[aria-pressed=true]{background:#ebe4fa;border-color:#d5c7ef}nav p{padding:15px 11px;color:#586a80;font-size:12px;line-height:1.65}.view{min-width:0}.toolbar{display:flex;align-items:center;justify-content:space-between;padding:15px 24px;gap:15px;border-bottom:1px solid #d8e0ea;background:#fff}.toolbar label{display:flex;align-items:center;gap:10px;font-size:13px}.toolbar input{width:140px;accent-color:#8066a9}.toolbar button{padding:8px 12px;border:1px solid #d8e0ea;background:#fff;border-radius:7px;cursor:pointer}.viewport{height:calc(100vh - 185px);overflow:auto;padding:24px}.canvas{width:100%;min-width:700px;line-height:0;box-shadow:0 6px 26px #26364b12;background:white}.canvas img{width:100%;height:auto;display:block}@media(max-width:800px){main{grid-template-columns:1fr}nav{display:flex;overflow:auto;padding:10px}nav button{min-width:200px;margin:0 5px}nav p{display:none}header{padding:18px;align-items:flex-start}h1{font-size:21px}header p{display:none}.links{flex-direction:column}.viewport{height:70vh;padding:12px}.toolbar{padding:12px}.canvas{min-width:700px}}
</style></head><body><header><div><small>T-RECAP / SENIOR CAPSTONE</small><h1>Architecture atlas</h1><p>Eight vector plates covering the FPGA datapath, platform and host interfaces.</p></div><div class="links"><a href="trecap-architecture-atlas.pdf">Open PDF</a><a id="svg-link" href="01-system-overview.svg" download>Download SVG</a></div></header><main><nav aria-label="Architecture plates">'''+buttons+'''<p>Source snapshot: 14 September 2026.<br>Diagrams describe the implemented source architecture. Board execution and functional validation remain separate milestones.<br><br>Solid: data flow.<br>Dashed: control.<br>Dotted: valid-only observation.</p></nav><section class="view"><div class="toolbar"><span id="plate-name">System architecture</span><label>Zoom <input id="zoom" type="range" min="100" max="220" step="10" value="100"><output id="zoom-value">100%</output><button id="fit" type="button">Fit</button></label></div><div class="viewport" id="viewport"><div class="canvas" id="canvas"><img id="plate" src="01-system-overview.svg" alt="System architecture"></div></div></section></main><script>
const pages='''+data+''';const img=document.getElementById('plate'),canvas=document.getElementById('canvas'),zoom=document.getElementById('zoom'),value=document.getElementById('zoom-value');function setZoom(n){zoom.value=n;value.value=n+'%';canvas.style.width=n+'%'}document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>{const p=pages[Number(button.dataset.page)];img.src=p.file;img.alt=p.title+'. '+p.subtitle;document.getElementById('plate-name').textContent=p.title;const link=document.getElementById('svg-link');link.href=p.file;document.querySelectorAll('[data-page]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.getElementById('viewport').scrollTo(0,0);setZoom(100)}));zoom.addEventListener('input',()=>setZoom(Number(zoom.value)));document.getElementById('fit').addEventListener('click',()=>setZoom(100));
</script></body></html>'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();root=args.repo_root.resolve();out=args.output or root/'docs/architecture/diagrams';out.mkdir(parents=True,exist_ok=True)
    plates=[plate1(),plate2(),plate3(),plate4(),plate5(),plate6(),plate7(),plate8()]
    warnings=[]
    for p in plates:p.footer();warnings.extend([f'{p.number}: {s}' for s in p.warnings])
    pdf=out/'trecap-architecture-atlas.pdf';c=canvas.Canvas(str(pdf),pagesize=(1190.55,841.89),pageCompression=1)
    c.setTitle('T-RECAP Architecture Atlas');c.setAuthor('T-RECAP');c.setSubject('FPGA signal-processing and DE1-SoC platform architecture')
    for p in plates:
        (out/(p.slug+'.svg')).write_text(svg_document(p),encoding='utf-8');c.bookmarkPage(p.slug);c.addOutlineEntry(p.title,p.slug,0);pdf_page(c,p)
    c.save();(out/'index.html').write_text(viewer(plates),encoding='utf-8')
    refs=sorted({r for p in plates for r in p.refs} | {
        'config/profiles/de1soc_bram_replay.json',
        'config/profiles/de1soc_adc_demo.json',
        'config/profiles/de1soc_linein_demo.json',
        'config/boards/de1soc_hps_transport.json',
        'docs/architecture/de1soc_ddr_ring_ownership.md',
        'rtl/core/trecap_delay_error_metrics.sv',
        'rtl/core/trecap_analysis_window.sv',
        'rtl/core/trecap_synthesis_wola.sv',
        'rtl/core/trecap_mag2_mask.sv',
        'rtl/core/trecap_spectrum_mask_builder.sv',
        'rtl/platform/de1soc/adc_wrapper.sv',
        'rtl/sources/trecap_audio_adapter.sv',
        'rtl/common/async_fifo.sv',
        'platform/de1soc/linux/driver/trecap_platform.c',
        'platform/de1soc/address_map/hps_bridge_regions.json',
        'platform/de1soc/qsys/system.qsys',
        'sw/hps/config/trecap_hps_config.json',
        'sw/pc_dashboard/configs/dashboard_direct_link.json',
    })
    manifest={'schema':'trecap_architecture_atlas_v1','snapshot_date':'2026-09-14','scope':'Architecture documentation only; no functional execution','pages':[{'number':p.number,'title':p.title,'svg':p.slug+'.svg','source_refs':p.refs} for p in plates], 'source_sha256':{r:hashlib.sha256((root/r).read_bytes()).hexdigest() for r in refs},'layout_warnings':warnings}
    (out/'atlas_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'pdf':str(pdf),'pages':len(plates),'warnings':warnings},indent=2))

if __name__=='__main__':main()
