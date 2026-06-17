tclsh

set hubs {R1 R21 R41}

set hostname ""
if {[catch {exec "show run | include ^hostname"} out]} {
    puts "ERROR: could not read hostname: $out"
    tclquit
}
if {[regexp {^hostname\s+(\S+)} $out _ hn]} {
    set hostname $hn
}

if {[lsearch -exact $hubs $hostname] >= 0} {
    puts "SKIP: $hostname is a hub"
    tclquit
}

if {![llength [info commands ios_config]]} {
    puts "ERROR: ios_config not available in this Tcl environment"
    puts "Run these commands manually on $hostname:"
    puts "conf t"
    puts " interface Tunnel0"
    puts "  ip nhrp shortcut"
    puts "end"
    puts "wr mem"
    tclquit
}

set sh ""
if {[catch {exec "show ip interface brief | include Tunnel0"} sh]} {
    set sh ""
}

if {![regexp {Tunnel0} $sh]} {
    puts "SKIP: $hostname has no Tunnel0"
    tclquit
}

if {[catch {ios_config "interface Tunnel0" "ip nhrp shortcut"} err]} {
    puts "ERROR: Failed to apply config on $hostname: $err"
    tclquit
}

if {[catch {exec "write memory"} err]} {
    puts "WARN: write memory failed on $hostname: $err"
}

puts "DONE: added 'ip nhrp shortcut' on $hostname"

tclquit
