# SPDX-License-Identifier: MIT
# Source-owned, fixed-profile CSR Avalon bridge. This is not generated Intel IP.
# The Intel 20.1 pipeline bridge lacks writeresponsevalid. Retaining that role
# here lets Platform Designer wait for the CSR leaf and preserve write errors.
package require -exact qsys 16.0

set_module_property NAME trecap_avalon_csr_bridge
set_module_property VERSION 1.0
set_module_property DISPLAY_NAME {T-RECAP CSR response bridge}
set_module_property DESCRIPTION {Fixed single-beat Avalon bridge with read and write completion responses}
set_module_property AUTHOR {T-RECAP project team}
set_module_property GROUP {T-RECAP}
set_module_property INSTANTIATE_IN_SYSTEM_MODULE true
set_module_property EDITABLE false
set_module_property VALIDATION_CALLBACK validate_profile

add_fileset synth QUARTUS_SYNTH
set_fileset_property synth TOP_LEVEL trecap_avalon_csr_bridge
add_fileset_file trecap_avalon_csr_bridge.sv SYSTEM_VERILOG PATH trecap_avalon_csr_bridge.sv

# Keep the existing eleven configuration names so source construction/readback
# uses the same API. Each value is restricted to the implemented fixed profile.
set trecap_csr_profile {
    ADDRESS_UNITS STRING SYMBOLS
    ADDRESS_WIDTH INTEGER 21
    DATA_WIDTH INTEGER 32
    LINEWRAPBURSTS INTEGER 0
    MAX_BURST_SIZE INTEGER 1
    MAX_PENDING_RESPONSES INTEGER 1
    PIPELINE_COMMAND INTEGER 0
    PIPELINE_RESPONSE INTEGER 0
    SYMBOL_WIDTH INTEGER 8
    USE_AUTO_ADDRESS_WIDTH INTEGER 0
    USE_RESPONSE INTEGER 1
}
foreach {name type value} $trecap_csr_profile {
    add_parameter $name $type $value
    set_parameter_property $name ALLOWED_RANGES [list $value]
    set_parameter_property $name HDL_PARAMETER false
    set_parameter_property $name AFFECTS_GENERATION false
}
proc validate_profile {} {
    global trecap_csr_profile
    foreach {name type expected} $trecap_csr_profile {
        set actual [get_parameter_value $name]
        if {![string equal $actual $expected]} {
            send_message error "T-RECAP CSR bridge requires $name=$expected; got $actual"
        }
    }
}

add_interface clk clock end
add_interface_port clk clk clk Input 1
add_interface reset reset end
set_interface_property reset associatedClock clk
set_interface_property reset synchronousEdges DEASSERT
add_interface_port reset reset reset Input 1

add_interface s0 avalon end
add_interface m0 avalon start
foreach intf {s0 m0} {
    set_interface_property $intf associatedClock clk
    set_interface_property $intf associatedReset reset
    set_interface_property $intf addressUnits SYMBOLS
    set_interface_property $intf bitsPerSymbol 8
    set_interface_property $intf burstcountUnits WORDS
    set_interface_property $intf burstOnBurstBoundariesOnly false
    set_interface_property $intf linewrapBursts false
}
set_interface_property s0 bridgesToMaster m0
set_interface_property s0 maximumPendingReadTransactions 1
set_interface_property s0 maximumPendingWriteTransactions 1
set_interface_property s0 readLatency 0
set_interface_property s0 readWaitTime 0
set_interface_property s0 writeWaitTime 0

# No debugaccess role: this CSR target has no debug bypass semantics.
foreach {role width} {
    address 21
    burstcount 1
    byteenable 4
    read 1
    write 1
    writedata 32
} {
    add_interface_port s0 s0_$role $role Input $width
    add_interface_port m0 m0_$role $role Output $width
}
foreach {role width} {
    waitrequest 1
    readdata 32
    readdatavalid 1
    writeresponsevalid 1
    response 2
} {
    add_interface_port s0 s0_$role $role Output $width
    add_interface_port m0 m0_$role $role Input $width
}
