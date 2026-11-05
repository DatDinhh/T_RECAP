onerror {quit -code 2}
onbreak {}
run -all
set completed [string trim [examine -radix unsigned /rf_limit_tb/checker_done]]
puts "DV_CHECKER_DONE=$completed"
if {$completed eq "1"} {quit -code 0} else {quit -code 1}
