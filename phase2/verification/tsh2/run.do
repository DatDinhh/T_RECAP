onerror {quit -code 2}
onbreak {}
run -all
set completed [string trim [examine -radix decimal /dv_stream_tb/checker_done]]
puts "DV_EXIT_STATE=$completed"
if {$completed eq "1"} {
    quit -code 0
} else {
    quit -code 1
}
