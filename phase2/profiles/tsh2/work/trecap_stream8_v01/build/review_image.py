"""Read-only source/pin audit for an isolated AFA1 HPS image; no hardware access."""
import argparse
import hashlib
import json
from pathlib import Path
import re

OLD=Path("D:/SeniorCapstoneProject")
LEGACY_PIN=OLD/"runs/quartus/windows/20260915-lite-bram-01/implementation-reports/trecap_de1soc.pin"
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def pin_rows(path):
    rows={}
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        parts=[part.strip() for part in line.split(":")]
        if len(parts)>=7 and parts[2] in ("input","output","bidir"):
            name=parts[0]
            if name in rows:
                raise ValueError("Duplicate active pin: "+name)
            rows[name]={"pin":parts[1],"direction":parts[2],"io_standard":parts[3],"bank":parts[5]}
    return rows

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--build",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    dest=args.build.resolve();args.out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((dest/"source_manifest.json").read_text())
    checks=[]
    def check(name,value,details=None):
        checks.append({"name":name,"passed":bool(value),"details":details})
    mismatches=[entry["path"] for entry in manifest["files"] if not (dest/entry["path"]).is_file() or sha(dest/entry["path"])!=entry["sha256"]]
    check("all_prepared_source_hashes",not mismatches,mismatches)
    wrapper_path=dest/"sources/platform_designer_wrapper.sv"
    check("wrapper_matches_legacy_source",sha(wrapper_path)==sha(OLD/"rtl/platform/de1soc/platform_designer_wrapper.sv"))
    top=(dest/"sources/trecap_hps_top.sv").read_text()
    wrapper=wrapper_path.read_text()
    declarations=re.findall(r"(input|output|inout)\s+wire\s*(\[\d+:\d+\])?\s*(HPS_\w+)\s*[,)]",top)
    scalar_ports={}
    for direction,width,name in declarations:
        if width:
            hi,lo=map(int,re.findall(r"\d+",width))
            for i in range(lo,hi+1):scalar_ports[f"{name}[{i}]"]=direction
        else:scalar_ports[name]=direction
    legacy_rows=pin_rows(LEGACY_PIN)
    legacy_hps={k:v for k,v in legacy_rows.items() if k.startswith("HPS_")}
    check("complete_HPS_port_set",len(declarations)==52 and len(scalar_ports)==127 and set(scalar_ports)==set(legacy_hps),
          {"bus_ports":len(declarations),"scalar_ports":len(scalar_ports),"legacy_scalar_ports":len(legacy_hps)})
    direct_ports=re.findall(r"\.(HPS_\w+)\((HPS_\w+)\)",top)
    check("direct_HPS_wrapper_bindings",len(direct_ports)==52 and all(a==b for a,b in direct_ports) and {a for a,b in direct_ports}=={name for _,_,name in declarations})
    check("fabric_clock_and_leaf_bridge_reset_shared",
          ".clk_50_i(CLOCK_50),.bridge_reset_n_i(reset_n)" in top and ".clk(CLOCK_50),.rst_n(reset_n)" in top)
    reset_expression=re.search(r"wire\s+async_reset_n\s*=\s*([^;]+)",top)
    check("no_KEY_only_master_reset_hazard",reset_expression is not None and reset_expression.group(1).strip()=="h2f_reset_n",
          None if reset_expression is None else reset_expression.group(1))
    check("HPS_reset_requests_inactive",all(f".{name}(1'b1)" in wrapper for name in
          ("hps_f2h_cold_reset_req_reset_n","hps_f2h_debug_reset_req_reset_n","hps_f2h_warm_reset_req_reset_n")))
    check("unused_F2SDRAM_requests_inactive",".avm_write_i(1'b0)" in top and ".trecap_f2h_sdram0_read(1'b0)" in wrapper)
    qip=dest/"legacy/platform/de1soc/qsys/system/synthesis/system.qip"
    original=qip.with_suffix(".qip.original").read_bytes()
    removed=[line for line in original.splitlines(keepends=True) if b"-name MISC_FILE" in line and b'"../../../../../D"' in line]
    expected=b"".join(line for line in original.splitlines(keepends=True) if line not in removed)
    check("single_known_metadata_removal_only",len(removed)==1 and qip.read_bytes()==expected)
    refs=manifest["qip_references"]
    missing=[entry["path"] for entry in refs if not (dest/entry["path"]).is_file() or sha(dest/entry["path"])!=entry["sha256"]]
    check("generated_QIP_closure",len(refs)==109 and not missing,{"references":len(refs),"missing_or_changed":missing})
    peripheral_io=dest/"hps_peripheral_io.tcl"
    peripheral_sdc=dest/"hps_peripheral_timing.sdc"
    check("legacy_HPS_IO_and_timing_scripts_unchanged",all(sha(dest/name)==sha(OLD/"constraints/de1soc"/name) for name in ("hps_peripheral_io.tcl","hps_peripheral_timing.sdc")))
    assignments=dest/"hps_ddr_assignments.qsf"
    ddr_text=assignments.read_text() if assignments.exists() else ""
    ddr_ready="Generated HPS DDR assignments" in ddr_text and "Placeholder" not in ddr_text
    ddr_rows=re.findall(r'^set_instance_assignment -name (IO_STANDARD|INPUT_TERMINATION|OUTPUT_TERMINATION) (\{[^}]+\}|\S+) -to (\{[^}]+\}|\S+) -tag __hps_sdram_p0$',ddr_text,re.M)
    ddr_values={kind:{} for kind in ("IO_STANDARD","INPUT_TERMINATION","OUTPUT_TERMINATION")}
    ddr_duplicates=[]
    for kind,value,target in ddr_rows:
        target=target.strip("{}");value=value.strip("{}")
        if target in ddr_values[kind]:ddr_duplicates.append(kind+":"+target)
        ddr_values[kind][target]=value
    ddr_data={f"HPS_DDR3_DQ[{i}]" for i in range(32)}
    ddr_strobes={f"HPS_DDR3_DQS_{sign}[{i}]" for sign in ("P","N") for i in range(4)}
    ddr_masks={f"HPS_DDR3_DM[{i}]" for i in range(4)}
    ddr_clocks={"HPS_DDR3_CK_P","HPS_DDR3_CK_N"}
    expected_io={name:("DIFFERENTIAL 1.5-V SSTL CLASS I" if name in ddr_strobes|ddr_clocks else "SSTL-15 CLASS I") for name in legacy_hps if name.startswith("HPS_DDR3_")}
    expected_input={name:"PARALLEL 50 OHM WITH CALIBRATION" for name in ddr_data|ddr_strobes}
    expected_output={name:"SERIES 50 OHM WITH CALIBRATION" for name in ddr_data|ddr_strobes|ddr_masks}
    expected_output.update({name:"SERIES 50 OHM WITHOUT CALIBRATION" for name in ddr_clocks})
    ddr_summary={"captured":ddr_ready,"sha256":sha(assignments) if assignments.exists() else None,
                 "io_standard_assignments":len(ddr_values["IO_STANDARD"]),
                 "input_termination_assignments":len(ddr_values["INPUT_TERMINATION"]),
                 "calibrated_output_termination_assignments":sum(value=="SERIES 50 OHM WITH CALIBRATION" for value in ddr_values["OUTPUT_TERMINATION"].values()),
                 "uncalibrated_clock_termination_assignments":sum(value=="SERIES 50 OHM WITHOUT CALIBRATION" for value in ddr_values["OUTPUT_TERMINATION"].values()),
                 "duplicate_assignments":ddr_duplicates}
    check("vendor_DDR_assignment_capture",ddr_ready and not ddr_duplicates and ddr_values=={"IO_STANDARD":expected_io,"INPUT_TERMINATION":expected_input,"OUTPUT_TERMINATION":expected_output},ddr_summary)
    pin_path=dest/"output_files/audio_hps.pin"
    pin_comparison={"available":pin_path.is_file(),"legacy_sha256":sha(LEGACY_PIN)}
    if pin_path.is_file():
        device_match=re.search(r'ASSIGNED TO AN:\s*(\S+)',pin_path.read_text(encoding="utf-8",errors="replace"))
        check("fitted_device_identity",device_match is not None and device_match.group(1)=="5CSEMA5F31C6",None if device_match is None else device_match.group(1))
        new=pin_rows(pin_path);new_hps={k:v for k,v in new.items() if k.startswith("HPS_")}
        differences={k:{"legacy":legacy_hps.get(k),"new":new_hps.get(k)} for k in set(legacy_hps)|set(new_hps) if legacy_hps.get(k)!=new_hps.get(k)}
        fpga=manifest["fpga_pins"]
        fpga_differences={k:new.get(k) for k,pin in fpga.items() if new.get(k)!={"pin":pin,"direction":"output" if k.startswith("LEDR[") else "input","io_standard":"3.3-V LVTTL","bank":legacy_rows[k]["bank"]}}
        dedicated_jtag={"TCK","TDI","TDO","TMS"}
        jtag_differences={k:{"legacy":legacy_rows.get(k),"new":new.get(k)} for k in dedicated_jtag if new.get(k)!=legacy_rows.get(k) or k not in new}
        check("dedicated_JTAG_pins_match_legacy",not jtag_differences,jtag_differences)
        unexpected=sorted(set(new)-set(legacy_hps)-set(fpga)-dedicated_jtag-{k for k in new if k.startswith("altera_reserved_")})
        pin_comparison.update(sha256=sha(pin_path),HPS_scalar_count=len(new_hps),HPS_differences=differences,FPGA_differences=fpga_differences,dedicated_JTAG_differences=jtag_differences,unexpected_active_pins=unexpected)
        check("fitted_HPS_pins_match_legacy",len(new_hps)==127 and not differences,pin_comparison)
        check("fitted_FPGA_pin_assignments_and_no_extra_pins",not fpga_differences and not unexpected)
    else:
        check("fitted_pin_report_available",False,pin_comparison)
    report={"schema":"afa1-independent-image-source-pin-review-v1","status":"PASS_SOURCE_AND_PIN_AUDIT_PENDING_TIMING_AND_RUNTIME" if all(c["passed"] for c in checks) else "INCOMPLETE_OR_FAILED_SOURCE_PIN_AUDIT",
            "build":str(dest),"source_id":manifest["source_id"],"source_manifest_sha256":sha(dest/"source_manifest.json"),
            "review_script_sha256":sha(Path(__file__)),
            "checks":checks,"pin_comparison":pin_comparison,
            "not_qualified":["Fitted setup/hold/recovery/removal and constraint completeness; separate timing review required.",
                             "Bootloader/HPS handoff register compatibility and live DDR survival across reconfiguration.",
                             "Running bridge/reset/remap state, device-tree ownership, device-memory mapping and physical MMIO.",
                             "Physical program admission and runtime correctness/performance."]}
    (args.out/"report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"failed_or_pending":[c["name"] for c in checks if not c["passed"]],"pin_report_available":pin_path.is_file()},indent=2))

if __name__=="__main__":
    main()
