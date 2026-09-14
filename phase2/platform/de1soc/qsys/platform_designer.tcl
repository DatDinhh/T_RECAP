# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC Platform Designer system source.
# File class: [1] hand-written Platform Designer/Qsys source.
# Layer: platform/de1soc/qsys/
# Owner: T-RECAP Phase 2 implementation.
#
# This script constructs/saves the Platform Designer source system.qsys and can
# read back the frozen tool-derived HPS parameter partition without mutating the
# graph. HDL/IP generation is deliberately external and must use qsys-generate.

proc trecap_pd_normpath {path} {
    if {[string equal $path ""]} { return "" }
    if {[regexp {^[A-Za-z]:[\\/]} $path] || [regexp {^[/\\][/\\]} $path] || [string equal [string index $path 0] "/"]} {
        return [file join $path]
    }
    return [file join [pwd] $path]
}

set trecap_pd_this_file [info script]
if {[string equal $trecap_pd_this_file ""]} {
    set trecap_pd_this_file [trecap_pd_normpath [file join [pwd] platform de1soc qsys platform_designer.tcl]]
}
set trecap_pd_this_dir [file dirname [trecap_pd_normpath $trecap_pd_this_file]]
set trecap_pd_config_file [file join $trecap_pd_this_dir hps_config.tcl]
if {![file exists $trecap_pd_config_file]} {
    return -code error "missing hps_config.tcl next to platform_designer.tcl"
}
source $trecap_pd_config_file

namespace eval ::trecap_pd {
    variable opts
    array set opts {
        mode                  auto
        repo_root             {}
        python_exe            {}
        force                 0
        strict_exports        1
        dry_run               0
        print_summary         0
        emit_runtime_config   0
        emit_bridge_regions   0
        readback_output       {}
    }
}

proc ::trecap_pd::message {kind text} {
    if {[llength [info commands post_message]] > 0} {
        post_message -type $kind $text
    } else {
        puts "[string toupper $kind]: $text"
    }
}

proc ::trecap_pd::usage {} {
    puts {Usage: platform_designer.tcl [options]

Options:
  --mode validate|construct|capture-readback|emit-configs|probe|probe-hps|auto
      validate      Check repo inputs and HPS config. No Qsys commands required.
      construct     Create and save system.qsys from the frozen graph contract.
      capture-readback
                    Load a normalized system.qsys read-only and capture the 44
                    tool-derived HPS values. Never adds or rewires graph nodes.
      emit-configs  Write HPS runtime and bridge-region JSON only.
      probe         Report available Platform Designer Tcl commands and exit.
      probe-hps     Create/reuse HPS instance, then report visible HPS parameters/interfaces.
      auto          generate inside qsys-script, validate under plain tclsh.

  --repo-root PATH        Override repository root.
  --python-exe PATH       Use this exact Python executable for source checks.
  --force                 Recreate system.qsys instead of loading existing source.
  --strict-exports        Retained for CLI compatibility; the source graph is always strict.
  --emit-runtime-config   Write sw/hps/config/trecap_hps_config.json.
  --emit-bridge-regions   Write platform/de1soc/address_map/hps_bridge_regions.json.
  --emit-all-manifests    Equivalent to both emit options.
  --readback-output PATH  Write ordered name/value TSV for 44 readback-only HPS parameters.
  --print-summary         Print resolved HPS/Qsys configuration.
  --dry-run               Validate and print planned actions without writing files.
  -h, --help              Show this help.}
}

proc ::trecap_pd::parse_args {argv_list default_repo_root} {
    variable opts
    set opts(repo_root) $default_repo_root

    set i 0
    while {$i < [llength $argv_list]} {
        set arg [lindex $argv_list $i]
        switch -- $arg {
            --mode {
                incr i
                if {$i >= [llength $argv_list]} { return -code error "--mode requires a value" }
                set opts(mode) [string tolower [lindex $argv_list $i]]
                if {[string equal $opts(mode) "generate"]} {
                    # Compatibility for direct qsys-script users. The outer
                    # runners use the unambiguous construct mode.
                    set opts(mode) construct
                }
                if {[lsearch -exact {auto validate construct capture-readback emit-configs probe probe-hps} $opts(mode)] < 0} {
                    return -code error "invalid --mode '$opts(mode)'"
                }
            }
            --repo-root {
                incr i
                if {$i >= [llength $argv_list]} { return -code error "--repo-root requires a value" }
                set opts(repo_root) [trecap_pd_normpath [lindex $argv_list $i]]
            }
            --python-exe {
                incr i
                if {$i >= [llength $argv_list]} { return -code error "--python-exe requires a value" }
                set opts(python_exe) [trecap_pd_normpath [lindex $argv_list $i]]
            }
            --force { set opts(force) 1 }
            --strict-exports { set opts(strict_exports) 1 }
            --dry-run { set opts(dry_run) 1 }
            --print-summary { set opts(print_summary) 1 }
            --emit-runtime-config { set opts(emit_runtime_config) 1 }
            --emit-bridge-regions { set opts(emit_bridge_regions) 1 }
            --readback-output {
                incr i
                if {$i >= [llength $argv_list]} { return -code error "--readback-output requires a value" }
                set opts(readback_output) [trecap_pd_normpath [lindex $argv_list $i]]
            }
            --emit-all-manifests {
                set opts(emit_runtime_config) 1
                set opts(emit_bridge_regions) 1
            }
            -h -
            --help {
                usage
                return -code return 0
            }
            default {
                return -code error "unknown option: $arg"
            }
        }
        incr i
    }
}

proc ::trecap_pd::qsys_available {} {
    return [expr {[llength [info commands create_system]] > 0 || [llength [info commands load_system]] > 0}]
}

proc ::trecap_pd::load_qsys_api {} {
    set version [::trecap_hps_config::get qsys_api_version]
    if {[qsys_available]} {
        if {[catch {package present qsys} actual]} {
            return -code error "Platform Designer commands are visible but the qsys package version cannot be verified: $actual"
        }
        if {![string equal $actual $version]} {
            return -code error "loaded qsys Tcl API $actual does not match frozen API $version"
        }
        return 1
    }
    if {![catch {package require -exact qsys $version} msg]} {
        message info "loaded frozen Platform Designer qsys Tcl API version $version"
        return 1
    }
    return -code error "required qsys Tcl API $version is unavailable: $msg"
}

proc ::trecap_pd::qsys_command_inventory {} {
    set patterns {create_system load_system save_system add_instance get_instances add_interface set_interface_property set_instance_parameter_value get_instance_parameter_value set_project_property get_instance_parameters get_instance_interfaces add_connection get_connection_parameters get_connection_parameter_value set_connection_parameter_value reload_ip_catalog validate_instance validate_system remove_interface delete_interface}
    set out {}
    foreach p $patterns {
        if {[llength [info commands $p]] > 0} { lappend out $p }
    }
    return $out
}

proc ::trecap_pd::require_qsys_commands {} {
    set required {
        create_system load_system save_system add_instance get_instances
        add_interface set_interface_property set_instance_parameter_value
        get_instance_parameter_value get_instance_parameters get_instance_interfaces
        add_connection get_connection_parameters get_connection_parameter_value
        set_connection_parameter_value reload_ip_catalog validate_instance validate_system
        set_project_property
    }
    set missing {}
    foreach cmd $required {
        if {[llength [info commands $cmd]] == 0} { lappend missing $cmd }
    }
    if {[llength $missing] != 0} {
        return -code error "required Platform Designer commands are missing: $missing"
    }
    return 1
}

proc ::trecap_pd::qsys_script_extra_args {} {
    set out {}
    for {set i 1} {$i < 128} {incr i} {
        set found 0
        foreach varname [list ::$i ::--$i $i --$i] {
            if {[info exists $varname]} {
                lappend out [set $varname]
                set found 1
                break
            }
        }
        if {!$found} { break }
    }
    return $out
}

proc ::trecap_pd::decode_cli_hex {encoded} {
    if {[string equal $encoded ""]} { return {} }
    set out {}
    set index 0
    foreach hex [split $encoded ,] {
        if {[expr {[string length $hex] % 2}] != 0 || ![regexp {^[0-9a-fA-F]*$} $hex]} {
            return -code error "invalid qsys-script --cmd argument encoding at index $index"
        }
        if {[catch {binary format H* $hex} bytes]} {
            return -code error "cannot decode qsys-script --cmd argument $index: $bytes"
        }
        if {[catch {encoding convertfrom utf-8 $bytes} value]} {
            return -code error "qsys-script --cmd argument $index is not valid UTF-8: $value"
        }
        lappend out $value
        incr index
    }
    return $out
}

proc ::trecap_pd::script_argv {} {
    # qsys-script 20.1 does not document a bare "--" positional forwarding
    # convention. The supported wrappers therefore pass a comma-separated,
    # UTF-8 hex encoding through the documented --cmd option. Hex makes paths
    # safe across Bash, PowerShell, Windows quoting, Tcl braces, and backslashes.
    if {[info exists ::trecap_pd_cli_hex]} {
        return [decode_cli_hex $::trecap_pd_cli_hex]
    }
    if {[info exists ::argv] && [llength $::argv] > 0} { return $::argv }
    return [qsys_script_extra_args]
}

proc ::trecap_pd::resolved_mode {} {
    variable opts
    if {![string equal $opts(mode) "auto"]} { return $opts(mode) }
    if {[qsys_available]} { return construct }
    return validate
}

proc ::trecap_pd::required_file {repo_root rel_path} {
    set p [trecap_pd_normpath [file join $repo_root $rel_path]]
    if {![file exists $p]} { return -code error "required file missing: $rel_path" }
    return $p
}

proc ::trecap_pd::required_dir {repo_root rel_path} {
    set p [trecap_pd_normpath [file join $repo_root $rel_path]]
    if {![file isdirectory $p]} { return -code error "required directory missing: $rel_path" }
    return $p
}

proc ::trecap_pd::run_static_platform_check {} {
    variable opts
    set checker [trecap_pd_normpath [file join $opts(repo_root) scripts check_hps_platform.py]]
    if {![file exists $checker]} {
        return -code error "mandatory frozen-platform checker is missing: $checker"
    }
    set python_cmd {}
    if {![string equal $opts(python_exe) ""]} {
        if {![file exists $opts(python_exe)] || ![file isfile $opts(python_exe)]} {
            return -code error "explicit Python executable is missing or is not a file: $opts(python_exe)"
        }
        set python_cmd [list $opts(python_exe)]
    } else {
        foreach candidate {python3 python} {
            if {[llength [info commands auto_execok]] > 0} {
                if {[catch {auto_execok $candidate} resolved]} { continue }
                if {![string equal $resolved ""]} {
                    set python_cmd $resolved
                    break
                }
            }
        }
    }
    if {[llength $python_cmd] == 0} {
        return -code error "python3/python is required to recompute and verify the frozen HPS preset hash"
    }
    set command $python_cmd
    lappend command $checker --repo-root $opts(repo_root) --quiet
    if {[catch {eval exec $command} output]} {
        return -code error "mandatory frozen-platform hash/parity check failed: $output"
    }
    message info "frozen HPS preset hash and platform-source parity verified"
    return 1
}

proc ::trecap_pd::validate_repo_inputs {} {
    variable opts
    set repo_root $opts(repo_root)
    ::trecap_hps_config::validate
    foreach rel {
        spec/generated/csr_map.json
        spec/generated/packet_layouts.json
        spec/generated/interface_types.json
        rtl/include/generated/trecap_csr_pkg.sv
        rtl/include/generated/trecap_packet_pkg.sv
        rtl/include/generated/trecap_iface_pkg.sv
        rtl/hps_bridge/trecap_hps_bridge_top.sv
        rtl/hps_bridge/trecap_ddr_ring_writer.sv
        constraints/de1soc/de1soc.qsf
        constraints/de1soc/de1soc.sdc
        constraints/de1soc/clocks.sdc
        constraints/de1soc/pin_assignments.tcl
        platform/de1soc/qsys/hps_config.tcl
        platform/de1soc/qsys/system_blueprint.xml
        platform/de1soc/qsys/system.qsys
        platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv
        platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json
        scripts/check_hps_platform.py
    } { required_file $repo_root $rel }
    required_dir $repo_root platform/de1soc/qsys
    run_static_platform_check
    return 1
}

proc ::trecap_pd::qsys_cmd {description args} {
    variable opts
    if {$opts(dry_run)} {
        message info "DRY-RUN: $description -> $args"
        return 1
    }
    if {[catch {uplevel 1 $args} msg]} { return -code error "$description failed: $msg" }
    return 1
}

proc ::trecap_pd::qsys_validate_strict {description args} {
    variable opts
    if {$opts(dry_run)} {
        message info "DRY-RUN: require clean $description -> $args"
        return {}
    }
    if {[catch {uplevel 1 $args} validation_messages]} {
        return -code error "$description failed: $validation_messages"
    }
    # Quartus20.1.1 Build720 returns strings with explicit severity prefixes.
    # Keep the raw messages, reject errors and unknown severities, and accept
    # only the reviewed non-critical HPS clock-approximation warnings below.
    set failures 0
    set debug_count 0
    set warning_count 0
    set validation_log {}
    if {![string equal $opts(readback_output) ""]} {
        set validation_path "${opts(readback_output)}.validation.log"
        file mkdir [file dirname $validation_path]
        # The bundled Quartus Java Tcl interpreter cannot append to a file
        # that does not exist yet; create it explicitly on the first phase.
        set validation_mode w
        if {[file exists $validation_path]} { set validation_mode a }
        set validation_log [open $validation_path $validation_mode]
        puts $validation_log "=== $description ==="
    }
    foreach validation_message $validation_messages {
        if {![string equal $validation_log ""]} { puts $validation_log $validation_message }
        # System validation prefixes the same HPS messages with the system name.
        regsub {^Warning: system[.]hps_0: } $validation_message {Warning: hps_0: } validation_message
        if {[regexp -nocase {^Debug:} $validation_message]} {
            incr debug_count
        } elseif {[regexp -nocase {^Info:} $validation_message]} {
            message info "$description: $validation_message"
        } elseif {[regexp {^Warning: hps_0: } $validation_message] && (
            [string first {"Configuration/HPS-to-FPGA user 0 clock frequency" (desired_cfg_clk_mhz) requested 100.0 MHz, but only achieved 97.368421 MHz} $validation_message] >= 0 ||
            [string first {"QSPI clock frequency" (desired_qspi_clk_mhz) requested 400.0 MHz, but only achieved 370.0 MHz} $validation_message] >= 0 ||
            [string equal $validation_message {Warning: hps_0: 1 or more output clock frequencies cannot be achieved precisely, consider revising desired output clock frequencies.}]
        )} {
            # Neither optional clock drives the50MHz core/CSR/DDR fabric domain.
            # Their actual vendor-derived values are retained in the readback.
            incr warning_count
            message warning "$description: $validation_message"
        } else {
            incr failures
            message error "$description: $validation_message"
        }
    }
    if {![string equal $validation_log ""]} { close $validation_log }
    message info "$description: $debug_count debug messages, $warning_count reviewed clock warnings, $failures failures"
    if {$failures != 0} {
        return -code error "$description returned $failures unaccepted validation message(s)"
    }
    return 1
}

proc ::trecap_pd::delete_export_if_possible {export_name} {
    if {[string equal $export_name ""]} { return }
    foreach cmd {remove_interface delete_interface} {
        if {[llength [info commands $cmd]] > 0} {
            catch {$cmd $export_name}
            return
        }
    }
}

proc ::trecap_pd::create_or_load_system {} {
    variable opts
    set repo_root $opts(repo_root)
    set qsys_file [trecap_pd_normpath [file join $repo_root [::trecap_hps_config::get qsys_file_rel]]]
    set system_name [::trecap_hps_config::get qsys_system_name]

    if {[file exists $qsys_file] && !$opts(force)} {
        set fp [open $qsys_file r]
        set qsys_text [read $fp]
        close $fp
        if {[string first "T_RECAP_BOOTSTRAP_QSYS_SOURCE=1" $qsys_text] < 0} {
            return -code error "refusing to reconstruct an existing Quartus-normalized system.qsys; use the outer generate mode to run qsys-generate directly, or pass --force only for an intentional destructive rebuild"
        }
        message info "replacing the checked-in bootstrap with a Quartus-normalized system.qsys"
    } elseif {[file exists $qsys_file] && $opts(force)} {
        message warning "--force explicitly permits replacing the existing system.qsys from the frozen blueprint"
    }

    if {!$opts(dry_run)} { file mkdir [file dirname $qsys_file] }
    qsys_cmd "create system" create_system $system_name

    # qsys-script receives the source IP search path on its command line.
    # reload_ip_catalog in Quartus20.1.1 discards that supplied search path;
    # use the fresh process catalog so the response-capable CSR IP stays visible.
    qsys_cmd "set device family" set_project_property DEVICE_FAMILY [::trecap_hps_config::get device_family]
    qsys_cmd "set target device" set_project_property DEVICE [::trecap_hps_config::get device_part]
    return $qsys_file
}

proc ::trecap_pd::add_or_reuse_instance {inst type version} {
    if {[llength [info commands get_instances]] > 0} {
        if {![catch {get_instances} instances] && [lsearch -exact $instances $inst] >= 0} {
            message info "reusing Platform Designer instance $inst"
            return 1
        }
    }
    if {![string equal $version ""]} {
        qsys_cmd "add instance $inst" add_instance $inst $type $version
    } else {
        qsys_cmd "add instance $inst" add_instance $inst $type
    }
    return 1
}

proc ::trecap_pd::normalized_value {value} {
    set value [string trim $value]
    # Platform Designer may render multi-value parameters either as comma lists
    # (Qsys XML) or Tcl whitespace lists (Tcl API). Those forms are equivalent.
    set value [string map [list "," " "] $value]
    regsub -all {[[:space:]]+} $value { } value
    if {[string equal -nocase $value "true"]} { return 1 }
    if {[string equal -nocase $value "false"]} { return 0 }
    return $value
}

proc ::trecap_pd::qsys_api_value {param semantic_value} {
    # The frozen TSV records Qsys XML semantic values. The Quartus 20.1 Tcl API
    # requires Tcl-list serialization for the array-valued HPS parameters.
    switch -- $param {
        F2SDRAM_Type {
            if {![string equal $semantic_value "Avalon-MM Bidirectional"]} {
                return -code error "unsupported frozen F2SDRAM_Type semantic value: $semantic_value"
            }
            # One Tcl-list element containing a space, exactly as emitted by
            # the official Quartus 20.1 Cyclone-V GHRD construction script.
            return {Avalon-MM\ Bidirectional}
        }
        AVL_DATA_WIDTH_PORT -
        CPORT_TYPE_PORT -
        DMA_Enable -
        GPIO_Enable -
        LOANIO_Enable -
        PRIORITY_PORT -
        WEIGHT_PORT {
            return [string map [list "," " "] $semantic_value]
        }
        default { return $semantic_value }
    }
}

proc ::trecap_pd::semantic_parameter_value {param api_value} {
    if {[string equal $param "F2SDRAM_Type"]} {
        set value [string trim $api_value]
        if {![catch {llength $value} count] && $count == 1} {
            set value [lindex $value 0]
        }
        return [string map [list "\\ " " "] $value]
    }
    return [normalized_value $api_value]
}

proc ::trecap_pd::parameter_values_equal {param actual expected} {
    set actual [semantic_parameter_value $param $actual]
    set expected [semantic_parameter_value $param $expected]
    if {[string equal $actual $expected]} { return 1 }
    # Numeric IP parameters may be rendered as integer or decimal strings
    # (clockFrequency is returned as 50000000.0 by Quartus20.1). Compare exact
    # numeric values without tolerances; enums and lists remain exact strings.
    set numeric_pattern {^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$}
    if {[regexp $numeric_pattern $actual] && [regexp $numeric_pattern $expected]} {
        return [expr {double($actual) == double($expected)}]
    }
    return 0
}

proc ::trecap_pd::instance_parameter_names {inst} {
    if {[catch {get_instance_parameters $inst} names]} {
        return -code error "cannot inventory parameters on $inst: $names"
    }
    return $names
}

proc ::trecap_pd::set_parameter_strict {inst param expected} {
    variable opts
    if {$opts(dry_run)} {
        message info "DRY-RUN: require and set $inst.$param -> $expected"
        return 1
    }
    set names [instance_parameter_names $inst]
    if {[lsearch -exact $names $param] < 0} {
        return -code error "required parameter $param is absent on $inst"
    }
    if {[catch {get_instance_parameter_value $inst $param} current]} {
        return -code error "cannot read $inst.$param: $current"
    }
    set api_expected [qsys_api_value $param $expected]
    # Compare before writing: setting an unchanged HPS parameter still triggers
    # expensive vendor callbacks in Quartus20.1. Every required value is read
    # back here and again after complete-system validation, including defaults.
    if {![parameter_values_equal $param $current $expected]} {
        if {[catch {set_instance_parameter_value $inst $param $api_expected} msg]} {
            return -code error "cannot set required parameter $inst.$param: $msg"
        }
    }
    if {[catch {get_instance_parameter_value $inst $param} actual]} {
        return -code error "cannot read back $inst.$param: $actual"
    }
    if {![parameter_values_equal $param $actual $expected]} {
        return -code error "$inst.$param readback mismatch: expected '$expected', got '$actual'"
    }
    return 1
}

proc ::trecap_pd::verify_parameter_strict {inst param expected} {
    variable opts
    if {$opts(dry_run)} {
        message info "DRY-RUN: verify $inst.$param remains $expected"
        return 1
    }
    set names [instance_parameter_names $inst]
    if {[lsearch -exact $names $param] < 0} {
        return -code error "required parameter $param is absent on $inst during final verification"
    }
    if {[catch {get_instance_parameter_value $inst $param} actual]} {
        return -code error "cannot verify final $inst.$param: $actual"
    }
    if {![parameter_values_equal $param $actual $expected]} {
        return -code error "$inst.$param drifted after system validation: expected '$expected', got '$actual'"
    }
    return 1
}

proc ::trecap_pd::instance_interface_names {inst} {
    if {[catch {get_instance_interfaces $inst} names]} {
        return -code error "cannot inventory interfaces on $inst: $names"
    }
    return $names
}

proc ::trecap_pd::require_internal_interface {qualified_name} {
    set dot [string first "." $qualified_name]
    if {$dot < 1} { return -code error "invalid qualified interface: $qualified_name" }
    set inst [string range $qualified_name 0 [expr {$dot - 1}]]
    set local [string range $qualified_name [expr {$dot + 1}] end]
    set names [instance_interface_names $inst]
    if {[lsearch -exact $names $local] < 0 && [lsearch -exact $names $qualified_name] < 0} {
        return -code error "required interface $qualified_name is absent; $inst exposes: $names"
    }
    return 1
}

proc ::trecap_pd::export_interface_strict {export_name kind direction internal_if} {
    variable opts
    if {[string equal $export_name ""]} {
        return -code error "required export name is empty for $internal_if"
    }
    if {$opts(dry_run)} {
        message info "DRY-RUN: require and export $internal_if as $export_name ($kind $direction)"
        return 1
    }
    require_internal_interface $internal_if
    delete_export_if_possible $export_name
    qsys_cmd "add required export $export_name" add_interface $export_name $kind $direction
    qsys_cmd "bind required export $export_name" set_interface_property $export_name EXPORT_OF $internal_if
    return 1
}

proc ::trecap_pd::add_connection_strict {description source_if sink_if} {
    variable opts
    if {$opts(dry_run)} {
        message info "DRY-RUN: require add_connection $source_if $sink_if ($description)"
        return 1
    }
    require_internal_interface $source_if
    require_internal_interface $sink_if
    qsys_cmd $description add_connection $source_if $sink_if
    return 1
}

proc ::trecap_pd::connection_parameter_values_equal {actual expected} {
    # Qsys may read address values back as either decimal or padded hex. Prefer
    # numeric comparison where the portable config parser can represent both.
    if {![catch {::trecap_hps_config::as_int $actual} actual_int] &&
        ![catch {::trecap_hps_config::as_int $expected} expected_int]} {
        return [expr {$actual_int == $expected_int}]
    }
    return [string equal [normalized_value $actual] [normalized_value $expected]]
}

proc ::trecap_pd::set_connection_parameter_strict {description source_if sink_if param expected} {
    variable opts
    set connection ${source_if}/${sink_if}
    if {$opts(dry_run)} {
        message info "DRY-RUN: require and set $connection.$param -> $expected ($description)"
        return 1
    }
    if {[catch {get_connection_parameters $connection} names]} {
        return -code error "cannot inventory parameters on connection $connection: $names"
    }
    if {[lsearch -exact $names $param] < 0} {
        return -code error "required connection parameter $param is absent on $connection"
    }
    if {[catch {set_connection_parameter_value $connection $param $expected} msg]} {
        return -code error "cannot set required connection parameter $connection.$param: $msg"
    }
    if {[catch {get_connection_parameter_value $connection $param} actual]} {
        return -code error "cannot read back connection parameter $connection.$param: $actual"
    }
    if {![connection_parameter_values_equal $actual $expected]} {
        return -code error "$connection.$param readback mismatch: expected '$expected', got '$actual'"
    }
    return 1
}

proc ::trecap_pd::verify_connection_parameter_strict {source_if sink_if param expected} {
    variable opts
    set connection ${source_if}/${sink_if}
    if {$opts(dry_run)} {
        message info "DRY-RUN: verify $connection.$param remains $expected"
        return 1
    }
    if {[catch {get_connection_parameters $connection} names]} {
        return -code error "cannot inventory parameters on connection $connection during final verification: $names"
    }
    if {[lsearch -exact $names $param] < 0} {
        return -code error "required connection parameter $param is absent on $connection during final verification"
    }
    if {[catch {get_connection_parameter_value $connection $param} actual]} {
        return -code error "cannot verify final connection parameter $connection.$param: $actual"
    }
    if {![connection_parameter_values_equal $actual $expected]} {
        return -code error "$connection.$param drifted after system validation: expected '$expected', got '$actual'"
    }
    return 1
}

proc ::trecap_pd::connect_hps_bridge_clocks {hps fabric_clock_if} {
    foreach local_sink [::trecap_hps_config::get hps_bridge_clock_sinks] {
        set sink ${hps}.${local_sink}
        add_connection_strict "connect required HPS bridge clock $sink" $fabric_clock_if $sink
    }
}

proc ::trecap_pd::avalon_mm_bridge_parameter_map {} {
    return {
        ADDRESS_UNITS          address_units
        ADDRESS_WIDTH          address_width
        DATA_WIDTH             data_width
        LINEWRAPBURSTS         linewrap_bursts
        MAX_BURST_SIZE         max_burst_size
        MAX_PENDING_RESPONSES  max_pending_responses
        PIPELINE_COMMAND       pipeline_command
        PIPELINE_RESPONSE      pipeline_response
        SYMBOL_WIDTH           symbol_width
        USE_AUTO_ADDRESS_WIDTH use_auto_address_width
        USE_RESPONSE           use_response
    }
}

proc ::trecap_pd::configure_avalon_mm_bridge {config_prefix} {
    set inst [::trecap_hps_config::get ${config_prefix}_instance]
    add_or_reuse_instance $inst \
        [::trecap_hps_config::get ${config_prefix}_component_type] \
        [::trecap_hps_config::get ${config_prefix}_component_version]
    foreach {parameter suffix} [avalon_mm_bridge_parameter_map] {
        set_parameter_strict $inst $parameter [::trecap_hps_config::get ${config_prefix}_${suffix}]
    }
    return $inst
}

proc ::trecap_pd::configure_hps_instance {} {
    variable opts
    set hps [::trecap_hps_config::get hps_instance]
    add_or_reuse_instance $hps [::trecap_hps_config::get hps_component_type] [::trecap_hps_config::get hps_component_version]

    if {$opts(dry_run)} {
        foreach pair [::trecap_hps_config::hps_parameter_pairs] {
            set_parameter_strict $hps [lindex $pair 0] [lindex $pair 1]
        }
        message info "DRY-RUN: require validate_instance $hps and verify all frozen parameter readbacks"
        return $hps
    }

    if {[catch {get_instance_parameters $hps} visible]} {
        return -code error "cannot inventory frozen HPS parameters: $visible"
    }
    set expected_writable {}
    set expected_all {}
    foreach pair [::trecap_hps_config::hps_snapshot_pairs] {
        lappend expected_all [lindex $pair 0]
    }
    set missing {}
    foreach pair [::trecap_hps_config::hps_parameter_pairs] {
        set param [lindex $pair 0]
        lappend expected_writable $param
        if {[lsearch -exact $visible $param] < 0} { lappend missing $param }
    }
    # Quartus20.1 get_instance_parameters includes internal/derived cache
    # parameters that are not serialized as user parameters in a .qsys file.
    # Require the complete source-owned partition, but do not mistake extra
    # vendor implementation parameters for writable source configuration.
    foreach param $expected_all {
        if {[lsearch -exact $visible $param] < 0 && [lsearch -exact $missing $param] < 0} {
            lappend missing $param
        }
    }
    if {[llength $missing] != 0} {
        return -code error "the Quartus HPS inventory lacks required frozen parameters: $missing"
    }
    set internal_parameters {}
    foreach param $visible {
        if {[lsearch -exact $expected_all $param] < 0} { lappend internal_parameters $param }
    }
    message info "HPS inventory: [llength $expected_all] required snapshot parameters; [llength $internal_parameters] additional vendor implementation parameters"

    for {set pass 1} {$pass <= 2} {incr pass} {
        foreach pair [::trecap_hps_config::hps_parameter_pairs] {
            set_parameter_strict $hps [lindex $pair 0] [lindex $pair 1]
        }
        message info "completed frozen HPS writable-parameter convergence pass $pass of 2"
    }
    qsys_validate_strict "validate frozen HPS instance" validate_instance $hps

    # Re-read every applied value after instance validation so dependent
    # updates cannot silently alter the 476 settable parameters. The remaining
    # 44 rows are explicitly tool-derived/readback-only provenance values and
    # are captured from the normalized Qsys output in the next integration step.
    foreach pair [::trecap_hps_config::hps_parameter_pairs] {
        set param [lindex $pair 0]
        set expected [lindex $pair 1]
        if {[catch {get_instance_parameter_value $hps $param} actual]} {
            return -code error "cannot verify $hps.$param after validation: $actual"
        }
        if {![parameter_values_equal $param $actual $expected]} {
            return -code error "$hps.$param drifted after validation: expected '$expected', got '$actual'"
        }
    }
    return $hps
}

proc ::trecap_pd::build_system_graph {} {
    set hps [configure_hps_instance]

    add_or_reuse_instance clk_0 clock_source {}
    set_parameter_strict clk_0 clockFrequency [::trecap_hps_config::get clk_50_hz]
    set_parameter_strict clk_0 clockFrequencyKnown [::trecap_hps_config::get fabric_clock_frequency_known]
    set_parameter_strict clk_0 resetSynchronousEdges [::trecap_hps_config::get fabric_reset_synchronous_edges]

    set csr_bridge [configure_avalon_mm_bridge csr_bridge]
    set sdram_bridge [configure_avalon_mm_bridge f2h_sdram_bridge]

    connect_hps_bridge_clocks $hps [::trecap_hps_config::get fabric_clk_internal]
    foreach bridge [list $csr_bridge $sdram_bridge] {
        add_connection_strict "connect required clock for $bridge" \
            [::trecap_hps_config::get fabric_clk_internal] ${bridge}.clk
        add_connection_strict "connect required reset for $bridge" \
            [::trecap_hps_config::get fabric_reset_bridge_internal] ${bridge}.reset
    }

    set csr_upstream [::trecap_hps_config::get csr_bridge_upstream_interface]
    set csr_slave [::trecap_hps_config::get csr_bridge_slave_interface]
    add_connection_strict "connect HPS lightweight AXI manager to typed CSR bridge" $csr_upstream $csr_slave
    set_connection_parameter_strict "freeze CSR bridge at lightweight-aperture offset zero" \
        $csr_upstream $csr_slave baseAddress \
        [::trecap_hps_config::get csr_bridge_connection_base_address]

    set sdram_master [::trecap_hps_config::get f2h_sdram_bridge_master_interface]
    set sdram_downstream [::trecap_hps_config::get f2h_sdram_bridge_downstream_interface]
    add_connection_strict "connect typed FPGA write bridge to HPS SDRAM agent" $sdram_master $sdram_downstream
    set_connection_parameter_strict "freeze FPGA-to-HPS SDRAM mapping at base address zero" \
        $sdram_master $sdram_downstream baseAddress \
        [::trecap_hps_config::get f2h_sdram_bridge_connection_base_address]

    # Export the clock-source input. The clock-source output remains internal
    # and drives all HPS and typed-bridge clock sinks. Export the paired reset
    # input; clk_0.clk_reset drives the two typed bridges internally.
    export_interface_strict [::trecap_hps_config::get fabric_clk_export] clock [::trecap_hps_config::get fabric_clk_export_role] clk_0.clk_in
    export_interface_strict [::trecap_hps_config::get fabric_reset_export] reset [::trecap_hps_config::get fabric_reset_export_role] [::trecap_hps_config::get fabric_reset_internal]
    export_interface_strict [::trecap_hps_config::get hps_io_export] conduit [::trecap_hps_config::get hps_io_export_role] ${hps}.hps_io
    export_interface_strict [::trecap_hps_config::get hps_memory_export] conduit [::trecap_hps_config::get hps_memory_export_role] ${hps}.memory
    export_interface_strict [::trecap_hps_config::get h2f_lw_master_export] avalon [::trecap_hps_config::get h2f_lw_master_export_role] [::trecap_hps_config::get h2f_lw_master_export_internal]
    export_interface_strict [::trecap_hps_config::get f2h_sdram0_export] avalon [::trecap_hps_config::get f2h_sdram0_export_role] [::trecap_hps_config::get f2h_sdram0_export_internal]
    export_interface_strict [::trecap_hps_config::get h2f_reset_export] reset [::trecap_hps_config::get h2f_reset_export_direction] ${hps}.h2f_reset

    # The frozen HPS preset enables fabric reset requests and STM hardware
    # events. Export every required input; the board wrapper ties these unused
    # requests inactive instead of leaving required HPS interfaces unconnected.
    foreach local_reset {f2h_cold_reset_req f2h_debug_reset_req f2h_warm_reset_req} {
        export_interface_strict [::trecap_hps_config::get ${local_reset}_export] \
            reset sink ${hps}.${local_reset}
    }
    export_interface_strict [::trecap_hps_config::get f2h_stm_hw_events_export] \
        conduit end ${hps}.f2h_stm_hw_events

    qsys_validate_strict "validate complete Platform Designer system" validate_system

    # Clock-derived updates can occur only after the complete graph exists.
    # Re-check every writable HPS value, both typed-bridge parameter sets, and
    # both base addresses after validate_system. This catches tool-driven
    # normalization before any source or readback is saved.
    variable opts
    if {$opts(dry_run)} {
        message info "DRY-RUN: re-check all writable HPS values after complete-system validation"
    } else {
        foreach pair [::trecap_hps_config::hps_parameter_pairs] {
            set param [lindex $pair 0]
            set expected [lindex $pair 1]
            if {[catch {get_instance_parameter_value $hps $param} actual]} {
                return -code error "cannot verify $hps.$param after complete-system validation: $actual"
            }
            if {![parameter_values_equal $param $actual $expected]} {
                return -code error "$hps.$param drifted after complete-system validation: expected '$expected', got '$actual'"
            }
        }
        foreach config_prefix {csr_bridge f2h_sdram_bridge} {
            set bridge [::trecap_hps_config::get ${config_prefix}_instance]
            foreach {parameter suffix} [avalon_mm_bridge_parameter_map] {
                verify_parameter_strict $bridge $parameter \
                    [::trecap_hps_config::get ${config_prefix}_${suffix}]
            }
        }
        verify_connection_parameter_strict $csr_upstream $csr_slave baseAddress \
            [::trecap_hps_config::get csr_bridge_connection_base_address]
        verify_connection_parameter_strict $sdram_master $sdram_downstream baseAddress \
            [::trecap_hps_config::get f2h_sdram_bridge_connection_base_address]
    }
}

proc ::trecap_pd::save_system_source {} {
    variable opts
    set repo_root $opts(repo_root)
    set qsys_file [trecap_pd_normpath [file join $repo_root [::trecap_hps_config::get qsys_file_rel]]]
    if {$opts(dry_run)} {
        message info "DRY-RUN: save to staging Qsys file, then atomically replace $qsys_file"
        return
    }
    set staging_file [file join [file dirname $qsys_file] system.step3_staging.qsys]
    if {[file exists $staging_file]} { file delete -force $staging_file }
    qsys_cmd "save validated Platform Designer system to staging" save_system $staging_file
    if {![file exists $staging_file]} {
        return -code error "save_system returned without creating staging file: $staging_file"
    }
    if {[catch {file rename -force $staging_file $qsys_file} msg]} {
        # Quartus20.1's Java Tcl cannot replace an existing file on Windows.
        # Python os.replace retains atomic replacement on the same filesystem;
        # never delete the working source first or fall back to a partial copy.
        set python_cmd {}
        if {![string equal $opts(python_exe) ""]} {
            set python_cmd [list $opts(python_exe)]
        } else {
            foreach candidate {python3 python} {
                if {![catch {auto_execok $candidate} resolved] && ![string equal $resolved ""]} {
                    set python_cmd $resolved
                    break
                }
            }
        }
        if {[llength $python_cmd] == 0} {
            return -code error "atomic replacement requires Python after Tcl rename failed: $msg"
        }
        set replace_command $python_cmd
        lappend replace_command -c {import os, sys; os.replace(sys.argv[1], sys.argv[2])} $staging_file $qsys_file
        if {[catch {eval exec $replace_command} replace_msg]} {
            return -code error "could not atomically replace $qsys_file: $replace_msg (Tcl: $msg)"
        }
    }
    message info "atomically replaced Platform Designer source after clean construction: $qsys_file"
}

proc ::trecap_pd::write_hps_readback_capture {hps output_path} {
    variable opts
    if {[string equal $output_path ""]} {
        return -code error "capture-readback requires --readback-output"
    }
    if {$opts(dry_run)} {
        message info "DRY-RUN: capture exactly [::trecap_hps_config::get hps_preset_readback_parameter_count] HPS readback-only values -> $output_path"
        return
    }
    set visible [instance_parameter_names $hps]
    set rows {}
    foreach pair [::trecap_hps_config::hps_readback_pairs] {
        set name [lindex $pair 0]
        if {[lsearch -exact $visible $name] < 0} {
            return -code error "required readback-only parameter is absent on $hps: $name"
        }
        if {[catch {get_instance_parameter_value $hps $name} value]} {
            return -code error "cannot read tool-derived parameter $hps.$name: $value"
        }
        set value [semantic_parameter_value $name $value]
        if {[string first "\t" $value] >= 0 || [string first "\n" $value] >= 0 || [string first "\r" $value] >= 0} {
            return -code error "readback-only parameter $name contains a non-TSV-safe value"
        }
        lappend rows [list $name $value]
    }
    if {[llength $rows] != [::trecap_hps_config::get hps_preset_readback_parameter_count]} {
        return -code error "incomplete HPS readback capture"
    }
    file mkdir [file dirname $output_path]
    set staging ${output_path}.tmp
    set fp [open $staging w]
    puts $fp "# schema=trecap_hps_readback_capture_v1"
    puts $fp "# source=Quartus-20.1-qsys-api-16.0"
    foreach row $rows {
        puts $fp "[lindex $row 0]\t[lindex $row 1]"
    }
    close $fp
    file rename -force $staging $output_path
    message info "captured [llength $rows] ordered HPS readback-only values: $output_path"
}

proc ::trecap_pd::capture_existing_system_readback {} {
    variable opts
    set qsys_file [trecap_pd_normpath [file join $opts(repo_root) [::trecap_hps_config::get qsys_file_rel]]]
    if {![file exists $qsys_file]} {
        return -code error "normalized system.qsys is missing: $qsys_file"
    }
    set fp [open $qsys_file r]
    set qsys_text [read $fp]
    close $fp
    if {[string first "T_RECAP_BOOTSTRAP_QSYS_SOURCE=1" $qsys_text] >= 0} {
        return -code error "cannot capture tool readbacks from the hand-written bootstrap; construct with Quartus first"
    }
    if {$opts(dry_run)} {
        write_hps_readback_capture [::trecap_hps_config::get hps_instance] $opts(readback_output)
        return
    }
    qsys_cmd "load normalized Platform Designer system read-only" load_system $qsys_file
    set hps [::trecap_hps_config::get hps_instance]
    if {[lsearch -exact [get_instances] $hps] < 0} {
        return -code error "normalized system lacks required HPS instance: $hps"
    }
    write_hps_readback_capture $hps $opts(readback_output)
}

proc ::trecap_pd::emit_config_manifests {} {
    variable opts
    set repo_root $opts(repo_root)
    if {$opts(emit_bridge_regions)} {
        if {$opts(dry_run)} {
            message info "DRY-RUN: write [::trecap_hps_config::get hps_bridge_regions_rel]"
        } else {
            set p [::trecap_hps_config::write_bridge_regions $repo_root]
            message info "validated and preserved reviewed bridge-region source $p"
        }
    }
    if {$opts(emit_runtime_config)} {
        if {$opts(dry_run)} {
            message info "DRY-RUN: write [::trecap_hps_config::get hps_runtime_config_rel]"
        } else {
            set p [::trecap_hps_config::write_hps_runtime_config $repo_root]
            message info "validated and preserved reviewed HPS runtime source $p"
        }
    }
}

proc ::trecap_pd::probe_hps_instance {} {
    load_qsys_api
    if {![qsys_available]} { return -code error "Platform Designer commands are not available for HPS probe" }
    require_qsys_commands
    # Probe in a process-local scratch system. Never load, delete, or save the
    # checked-in system.qsys from an inventory operation.
    qsys_cmd "create non-persistent HPS probe system" create_system trecap_hps_probe
    qsys_cmd "set probe device family" set_project_property DEVICE_FAMILY [::trecap_hps_config::get device_family]
    qsys_cmd "set probe target device" set_project_property DEVICE [::trecap_hps_config::get device_part]
    set hps [configure_hps_instance]

    if {[catch {get_instance_parameters $hps} names]} {
        return -code error "get_instance_parameters $hps failed: $names"
    } else {
        message info "$hps parameters: $names"
    }
    if {[catch {get_instance_interfaces $hps} ifaces]} {
        return -code error "get_instance_interfaces $hps failed: $ifaces"
    } else {
        message info "$hps interfaces: $ifaces"
    }
    message info "probe complete; scratch system was not saved"
}

proc ::trecap_pd::main {} {
    variable opts
    set default_repo_root [::trecap_hps_config::repo_root [info script]]
    parse_args [script_argv] $default_repo_root

    if {$opts(print_summary)} { ::trecap_hps_config::emit_summary }
    validate_repo_inputs

    set mode [resolved_mode]
    message info "T-RECAP Platform Designer mode: $mode"

    if {[string equal $mode "validate"]} { return 0 }
    if {[string equal $mode "probe"]} {
        load_qsys_api
        set cmds [qsys_command_inventory]
        if {[llength $cmds] == 0} {
            message warning "no Platform Designer system-scripting commands are visible"
        } else {
            message info "visible Platform Designer commands: $cmds"
        }
        return 0
    }
    if {[string equal $mode "probe-hps"]} {
        probe_hps_instance
        return 0
    }
    if {[string equal $mode "emit-configs"]} {
        set opts(emit_runtime_config) 1
        set opts(emit_bridge_regions) 1
        emit_config_manifests
        return 0
    }

    if {[string equal $mode "capture-readback"]} {
        if {!$opts(dry_run)} { load_qsys_api }
        if {!$opts(dry_run)} { require_qsys_commands }
        capture_existing_system_readback
        return 0
    }

    if {!$opts(dry_run)} { load_qsys_api }
    if {!$opts(dry_run) && ![qsys_available]} {
        set cmds [qsys_command_inventory]
        return -code error "Platform Designer commands are not available after requesting the qsys Tcl API. Visible commands: $cmds. Run qsys-script with --package-version=16.0 or verify the Intel FPGA Platform Designer installation."
    }
    if {!$opts(dry_run)} { require_qsys_commands }

    create_or_load_system
    build_system_graph
    save_system_source
    if {![string equal $opts(readback_output) ""]} {
        write_hps_readback_capture [::trecap_hps_config::get hps_instance] $opts(readback_output)
    }
    emit_config_manifests
}

set trecap_pd_exit_code [catch {::trecap_pd::main} trecap_pd_msg]
if {$trecap_pd_exit_code != 0} {
    if {$trecap_pd_exit_code == 2} { exit 0 }
    return -code error "T-RECAP platform_designer: $trecap_pd_msg"
}
