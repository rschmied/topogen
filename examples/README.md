# Example IOS configs

Reference configs you can copy-paste or compare against TopoGen output.

| File | Purpose |
|------|---------|
| [EEM-SCRIPTS.md](EEM-SCRIPTS.md) | **List of EEM scripts** (PKI): script name, example file, working checkbox. |
| `ca-root-config.txt` | CA-ROOT PKI server (IOS-XE): 20-year certs, grant auto, database on flash, exportable key. Set clock from exec before starting PKI; optional EEM for first boot. |
| `eem-ca-root-set-clock.txt` | EEM applet CA-ROOT-SET-CLOCK: one-shot (countdown 90s) on CA-ROOT. If NTP synced, sets TIME_DONE only; else clock set + ntp master 6. |
| `eem-client-pki-set-clock.txt` | EEM applet CLIENT-PKI-SET-CLOCK: one-shot (countdown 90s) on clients. If NTP synced, sets TIME_DONE only; else clock set. |
| `eem-client-pki-authenticate.txt` | EEM applet CLIENT-PKI-AUTHENTICATE: triggered by syslog PKI-6-AUTHORITATIVE_CLOCK; run crypto pki authenticate CA-ROOT-SELF + "yes" (pattern ".*"). Minimal version, no delete self/write mem. |
| `eem-client-pki-chain.txt` | EEM applet CLIENT-PKI-CHAIN: triggered by syslog PKI-6-AUTHORITATIVE_CLOCK; run `crypto pki authenticate CA-ROOT-SELF` with pattern "yes/no" and send "yes"; sets PKI_DONE 1, deletes self, write mem. |
| `eem-auto-auth.txt` | EEM applet AUTO-AUTH: run-once at 130s; same authenticate + pattern "yes/no" + "yes" for CA-ROOT-SELF; sets PKI_DONE 1, deletes self, write mem. |
| `eem-client-pki-enroll.txt` | EEM applet CLIENT-PKI-ENROLL: trustpoint lab-ca-tp is in config (TopoGen --pki); FQDN in subject. Applet sets CA_AUTH_DONE and ENROLL_DONE when it sees certs. Run once: `crypto pki authenticate lab-ca-tp`, `crypto pki enroll lab-ca-tp` (answer yes). |
| `eem-do-ssh.txt` | EEM applet do-ssh: one-shot at reboot. Zeroize RSA, generate new key, remove old TP-self-signed-N, toggle ip http secure-server and restconf, then remove applet and write mem. Refreshes self-signed cert for HTTPS/RESTCONF. |

**Testing PKI labs:** When building a lab with `--pki`, add `--ntp <server>` (and `--ntp-vrf <vrf>` if using mgmt) so NTP is configured. That lets you verify the clock EEM: if NTP syncs, the applet sets TIME_DONE and does not overwrite the clock; if NTP does not sync, it applies the fallback clock floor.
