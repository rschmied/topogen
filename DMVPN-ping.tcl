tclsh
set max 20
set base "10.20"

for {set n 1} {$n <= $max} {incr n} {
    set hi [expr {$n / 256}]
    set lo [expr {$n % 256}]
    set ip [format "%s.%d.%d" $base $hi $lo]

    puts [format "PING R%-3d %s" $n $ip]
    if {[catch {exec "ping $ip repeat 10 timeout 1"} out]} {
        puts "PING ERROR: $out"
    } else {
        puts $out
    }
}
tclquit
