"""Fail-closed independent HPS timing gate. Reads artifacts; never hardware."""
import argparse, collections, csv, hashlib, io, json, re
from pathlib import Path

P='platform_designer_wrapper:platform|system:u_platform_designer_system|system_hps_0:hps_0|'
I=P+'system_hps_0_hps_io:hps_io|system_hps_0_hps_io_border:border|'
D=I+'hps_sdram:hps_sdram_inst|'
DDR_IO=D+'hps_sdram_p0:p0|hps_sdram_p0_acv_hard_memphy:umemphy|hps_sdram_p0_acv_hard_io_pads:uio_pads|hps_sdram_p0_altdqdqs:dq_ddio'
HARD=P+'system_hps_0_fpga_interfaces:fpga_interfaces|'
PORTS={'HPS_USB_CLKOUT','HPS_I2C1_SCLK','HPS_I2C2_SCLK'}
CORNER_NAMES={'6_slow_1100mv_85c':'Slow 1100mV 85C Model','6_slow_1100mv_0c':'Slow 1100mV 0C Model',
              'MIN_fast_1100mv_85c':'Fast 1100mV 85C Model','MIN_fast_1100mv_0c':'Fast 1100mV 0C Model'}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def table(p):
    return [[x.strip() for x in line.split(';')[1:-1]] for line in p.read_text(errors='strict').splitlines() if line.startswith(';')]
def hard_class(n):
    if n in PORTS:return 'hard_peripheral_clock_port'
    if re.fullmatch(re.escape(HARD)+r'(clocks_resets|hps2fpga_light_weight)~FF_\d+',n):return 'hard_HPS_interface_internal'
    if re.fullmatch(re.escape(I)+r'(emac1|qspi|sdio|usb1|spim1|uart0|i2c0|i2c1|gpio)_inst~FF_\d+',n):return 'hard_HPS_peripheral_internal'
    if re.fullmatch(re.escape(I)+r'intermediate\[[01]\]',n):return 'hard_HPS_peripheral_intermediate'
    emac={'emac1_inst','emac1_inst~O_EMAC_CLK_TX','emac1_inst~O_EMAC_PHY_TX_OE','emac1_inst~O_EMAC_GMII_MDC',
          'emac1_inst~O_EMAC_PHY_TXD1','emac1_inst~O_EMAC_PHY_TXD2','emac1_inst~O_EMAC_PHY_TXD3',
          'emac1_inst~EMAC_CLK_RX[0]','emac1_inst~EMAC_PHY_RXDV[0]','emac1_inst~EMAC_GMII_MDO_I[0]'}
    emac.update(f'emac1_inst~EMAC_PHY_RXD[{i}]' for i in range(4))
    if n in {I+suffix for suffix in emac}:return 'hard_HPS_EMAC_port_model'
    if n in {D+'hps_sdram_pll:pll|afi_clk',D+'hps_sdram_pll:pll|pll_write_clk'}:return 'hard_DDR_PLL_model'
    if re.fullmatch(re.escape(DDR_IO)+r'\[[0-3]\]\.ubidir_dq_dqs\|altdq_dqs2_acv_connect_to_hard_phy_cyclonev:altdq_dqs2_inst\|dqs_delay_chain~POS_POSTAMBLE_DFF',n):return 'hard_DDR_DQS_model'
    return None
def multi_class(n):
    suffix=r'\[[0-3]\]\.ubidir_dq_dqs\|altdq_dqs2_acv_connect_to_hard_phy_cyclonev:altdq_dqs2_inst\|'
    suffix+=r'(dqs_delay_chain~POSTAMBLE_DFF|input_path_gen\[[0-7]\]\.(read_fifo~WRITE_ADDRESS_DFF|capture_reg~DFFLO|aligned_input\[1\]))'
    return 'DDR_calibrated_read_capture' if re.fullmatch(re.escape(DDR_IO)+suffix,n) else None

def analyze(build,reports,out):
    checks=[]
    def check(name,passed,details=None):checks.append(dict(name=name,passed=bool(passed),details=details))
    manifest=json.loads((build/'source_manifest.json').read_text());receipt=json.loads((build/'build_receipt.json').read_text())
    bindings={}
    for name in ['source_manifest.json','build_receipt.json','audio_hps.qsf','audio_hps.qpf','hps_ddr_assignments.qsf','hps_sdram_p0_summary.csv','hps_image.sdc','hps_peripheral_timing.sdc']:
        bindings[name]=sha(build/name)
    check('manifest_bound_to_build',bindings['source_manifest.json']==receipt['source_manifest_sha256'] and manifest['source_id']==receipt['source_id'])
    changed=[r['path'] for r in manifest['files'] if sha(build/r['path'])!=r['sha256']]
    check('prepared_sources_unchanged',not changed,changed)
    check('build_stages_successful',[r['stage'] for r in receipt['stages']]==['map','ddr_capture','fit','sta'] and all(r['exit_code']==0 and sha(build/r['log'])==r['sha256'] for r in receipt['stages']))
    check('settings_unchanged',receipt['settings_before_tool_sha256']==receipt['settings_after_tool_sha256']=={k:sha(build/k) for k in receipt['settings_after_tool_sha256']})
    check('DDR_assignments_bound',bindings['hps_ddr_assignments.qsf']==receipt['ddr_assignments_sha256'])
    for label,r in receipt['artifacts'].items():
        bindings[r['path']]=sha(build/r['path']);check('artifact_'+label,bindings[r['path']]==r['sha256'])
    check('independent_tool_completed','INDEPENDENT_HPS_TIMING_REPORTS_COMPLETE corners=4' in (build/'review.log').read_text())
    clocks=list(csv.DictReader((reports/'clocks.tsv').open(),delimiter='\t'))
    wanted={'CLOCK_50':20.,D+'hps_sdram_pll:pll|pll_write_clk_dq_write_clk':2.5,D+'hps_sdram_pll:pll|afi_clk_write_clk':2.5,
      'platform|u_platform_designer_system|hps_0|hps_io|border|hps_sdram_inst|hps_sdram_p0_sampling_clock':2.5,
      'HPS_DDR3_CK_P':2.5,'HPS_DDR3_CK_N':2.5}
    wanted.update({f'HPS_DDR3_DQS_{pol}[{i}]_{direction}':2.5 for pol,direction in [('P','IN'),('P','OUT'),('N','OUT')] for i in range(4)})
    check('all_18_expected_clock_names_and_periods',len(clocks)==18 and {r['clock']:float(r['period_ns']) for r in clocks}==wanted)
    paths=list(csv.DictReader((reports/'corners.tsv').open(),delimiter='\t'))
    keys={(r['corner'],r['clock'],r['check']) for r in paths}
    expected={(corner,clock,kind) for corner in CORNER_NAMES for clock in wanted for kind in ['setup','hold','recovery','removal']}
    check('four_corners_all_clocks_all_checks',len(paths)==288 and keys==expected)
    fabric=[];raw_ddr=[]
    for r in paths:
        r['slack_ns']=None if r['slack_ns']=='N/A' else float(r['slack_ns'])
        if r['clock']=='CLOCK_50' or r['clock'].endswith('|afi_clk_write_clk'):
            fabric.append(r)
        else:
            raw_ddr.append(r)
    check('fabric_and_AFI_setup_hold_recovery_removal',all(r['slack_ns'] is not None and r['slack_ns']>=0 for r in fabric),[r for r in fabric if r['slack_ns'] is None or r['slack_ns']<0])
    # Generated DDR input/output paths require the vendor calibrated analysis below.
    # Their raw path values are retained, never silently folded into fabric slack.
    summary=[]
    pat=r"Type\s*:\s*(.+? Model) (Setup|Hold|Recovery|Removal|Minimum Pulse Width) '([^']+)'\s*\nSlack\s*:\s*([-\d.]+)\s*\nTNS\s*:\s*([-\d.]+)"
    for corner,kind,clock,slack,tns in re.findall(pat,(build/'output_files/audio_hps.sta.summary').read_text()):
        summary.append(dict(corner=corner,check=kind,clock=clock,slack_ns=float(slack),tns_ns=float(tns)))
    check('compiler_summary_complete',len(summary)==44 and {r['corner'] for r in summary}==set(CORNER_NAMES.values()))
    check('compiler_summary_all_nonnegative',all(r['slack_ns']>=0 and r['tns_ns']>=0 for r in summary),[r for r in summary if r['slack_ns']<0])
    mismatches=[]
    for r in fabric:
        match=[s for s in summary if (s['corner'],s['clock'],s['check'].lower())==(CORNER_NAMES[r['corner']],r['clock'],r['check'])]
        if len(match)!=1 or match[0]['slack_ns']!=r['slack_ns']:mismatches.append(r)
    check('independent_vs_compiler_slack_agrees',not mismatches,mismatches)
    ddr_text=(build/'hps_sdram_p0_summary.csv').read_text()
    ddr=[]
    for row in csv.reader(io.StringIO('\n'.join(ddr_text.splitlines()[2:]))):
        if not row:continue
        match=re.fullmatch(r'(.+) \((.+ Model)\)',row[0])
        if not match:raise ValueError('Unexpected DDR summary row')
        ddr.append(dict(path=match[1],corner=match[2],setup_ns=float(row[1]),hold_ns=None if row[2]=='--' else float(row[2])))
    ddr_types={'Address Command','Bus Turnaround Time','Core','Core Recovery/Removal','DQS vs CK','Postamble','Read Capture','Write'}
    check('vendor_DDR_full_calibrated_report',len(ddr)==32 and {(r['path'],r['corner']) for r in ddr}=={(p,c) for p in ddr_types for c in CORNER_NAMES.values()} and
          all(r['setup_ns']>=0 and (r['hold_ns'] is not None and r['hold_ns']>=0 or r['path']=='Bus Turnaround Time' and r['hold_ns'] is None) for r in ddr))
    constraints={};first_nodes=None
    for corner in CORNER_NAMES:
        rows=table(reports/f'{corner}_constraint_checks.rpt')
        counts={r[0]:int(r[1]) for r in rows if len(r)==2 and r[0] in ['no_clock','multiple_clock','loops','latches','generated_clock']}
        no_clock=[r[0] for r in rows if len(r)==2 and r[1] in ["No clock feeds this register's clock port.",'Node was determined to feed a clock port but was found without an associated clock assignment.']]
        multiple=[r[0] for r in rows if len(r)==2 and r[1]=="More than one clock feeds this register's clock port."]
        u=table(reports/f'{corner}_unconstrained.rpt')
        ucounts={r[0]:[int(r[1]),int(r[2])] for r in u if len(r)==3 and r[0] in ['Illegal Clocks','Unconstrained Clocks','Unconstrained Input Ports','Unconstrained Input Port Paths','Unconstrained Output Ports','Unconstrained Output Port Paths']}
        unclock=[r[0] for r in u if len(r)==4 and r[-1]=='Unconstrained']
        unknown_no=[n for n in no_clock if hard_class(n) is None];unknown_multi=[n for n in multiple if multi_class(n) is None]
        c=dict(counts=counts,no_clock_categories=dict(collections.Counter(hard_class(n) or 'UNKNOWN' for n in no_clock)),
          multiple_clock_categories=dict(collections.Counter(multi_class(n) or 'UNKNOWN' for n in multiple)),
          unknown_no_clock=unknown_no,unknown_multiple_clock=unknown_multi,unconstrained_summary=ucounts,unconstrained_clocks=unclock,
          no_clock_names_sha256=hashlib.sha256('\n'.join(sorted(no_clock)).encode()).hexdigest(),multiple_clock_names_sha256=hashlib.sha256('\n'.join(sorted(multiple)).encode()).hexdigest())
        constraints[corner]=c
        check(corner+'_constraint_coverage',counts==dict(no_clock=6372,multiple_clock=100,loops=0,latches=0,generated_clock=0) and len(no_clock)==6372 and len(multiple)==100 and not unknown_no and not unknown_multi,dict(unknown_no=unknown_no,unknown_multiple=unknown_multi))
        check(corner+'_unconstrained_classification',len(ucounts)==6 and set(unclock)==PORTS and all(v==([3,3] if k=='Unconstrained Clocks' else [0,0]) for k,v in ucounts.items()))
        nodes=(sorted(no_clock),sorted(multiple))
        if first_nodes is None:first_nodes=nodes
        check(corner+'_exception_set_matches_first_corner',nodes==first_nodes)
        pulse=(reports/f'{corner}_min_pulse_width.rpt').read_text()
        pulse_match=re.search(r'Found (\d+) results \((\d+) violated\).*?Worst case slack is ([-\d.]+)',pulse)
        check(corner+'_independent_pulse_width',pulse_match and int(pulse_match[2])==0 and float(pulse_match[3])>=0)
    # Bind the unchanged vendor script closure so the exception classification
    # cannot be reused on another generated hard-IP preset accidentally.
    vendor_files={r['path']:r['sha256'] for r in manifest['files'] if r['path'].endswith(('.sdc','.tcl')) and '/submodules/' in r['path']}
    result=dict(schema='afa1-independent-timing-gate-v1',status='PASS_TIMING_ONLY' if all(c['passed'] for c in checks) else 'FAIL_TIMING_GATE',
      physical_programming_authorized=False,build_path=str(build),source_id=manifest['source_id'],binding_sha256=bindings,
      script_sha256=sha(Path(__file__)),tcl_sha256=sha(Path(__file__).with_name('timing_review.tcl')),
      reports_path=str(reports),report_files_sha256={p.name:sha(p) for p in sorted(reports.iterdir()) if p.is_file()},
      checks=checks,clocks=clocks,independent_path_records=paths,compiler_summary_records=summary,vendor_DDR_calibrated_records=ddr,
      constraints=constraints,vendor_script_hashes=vendor_files,
      exception_rationale=['Only exact generated HPS hard primitive register names and three explicit hard-peripheral clock ports are classified as no_clock; no fabric register is exempted.',
        'One hundred multiple_clock nodes are exact DDR hard read-capture/postamble structures under four DQS groups, covered by vendor calibrated DDR analysis.',
        'Vendor DDR raw input/output path analysis contains calibration-dependent negative slack; the separate 8 categories x 4 corners calibrated report is the applicable DDR margin gate.',
        'The 84 explicit hard-peripheral pin cuts preserve vendor directions and wrapper names. They do not cover DDR, adapter, leaf, framer or generated HPS-to-fabric synchronous paths.',
        'Only asynchronous reset-synchronizer clear pins and constant LED outputs are custom false paths; reset release and all synchronous fabric remain timed.'],
      limitations=['This is fitted static timing evidence, not oscillator calibration or physical boot/DDR validation.','Timing PASS alone cannot authorize programming; separate source/pin/reset/boot and exclusive ownership gates apply.'])
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(status=result['status'],failed_checks=[c['name'] for c in checks if not c['passed']],report=str(out)),indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=Path,required=True);p.add_argument('--reports',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=analyze(a.build.resolve(),a.reports.resolve(),a.out.resolve());raise SystemExit(0 if r['status']=='PASS_TIMING_ONLY' else 1)
