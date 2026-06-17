# VPN Debug: DMVPN Phase 3 + IKEv2 PKI (TopoGen Lab)

**Goal:** Get IPsec tunnels up when IKEv2 SAs do not form. Follow steps in order; paste outputs as requested so we can pinpoint the failure.

**Your setup (reference):**
- **Topology:** Flat underlay, 3 routers (R1 hub, R2/R3 spokes), CA-ROOT at 10.10.255.254
- **Auth:** IKEv2 with PKI — trustpoint `CA-ROOT-SELF`, profile `TOPGEN-IKEV2`, transform `TOPGEN-TS`
- **OOB mgmt:** R1=192.168.1.203, R2=192.168.1.214, R3=192.168.1.124 (SSH to these)
- **SCEP:** `http://10.10.255.254:80` (inband, 10.10.0.0/16)
- **NTP:** Inband to CA (10.10.255.254)

---

## Step 0: Confirm underlay and roles

On each router, confirm **NBMA (underlay) interface** and that you know which is hub vs spoke.

**Run on R1, R2, R3:**

```text
show ip interface brief
show run interface GigabitEthernet1
show run interface Tunnel0
```

**Please paste:** Output from R1 only (we need Gi1 IP and that Tunnel0 exists with `tunnel protection ipsec profile TOPGEN-IPSEC`).

**Check:** R1’s Gi1 should be on 10.10.x.x; R2/R3 Gi1 also 10.10.x.x. Tunnel0 should have `ip nhrp redirect` on R1 and `ip nhrp shortcut` + `ip nhrp nhs` on R2/R3.

---

## Step 1: Clock and NTP (critical for PKI)

Certificate validation uses **time**. If clocks are wrong or not synced, IKEv2 will not accept certs.

**On R1, R2, R3 run:**

```text
show clock
show ntp status
show ntp associations
```

**On CA-ROOT (if you have console/SSH):**

```text
show clock
show ntp status
```

**What we need:**
- All routers and CA: clock **date/time plausible** (e.g. 2025–2026, correct timezone).
- If NTP is used: `show ntp status` should show “synchronized” or similar; associations should show 10.10.255.254 (or your NTP server) and reach.

**If clock is wrong:** Set manually so cert validity checks can pass, then fix NTP for persistence:

```text
clock set HH:MM:SS DAY MONTH YEAR
! e.g. clock set 14:30:00 18 Feb 2026
```

**Paste:** `show clock` and `show ntp status` from **R1 and R2** (one hub, one spoke).

---

## Step 2: NBMA reachability (underlay)

IKEv2 runs over the underlay. Spokes must reach hub’s NBMA IP; all must reach CA for SCEP (if not yet enrolled).

**On R2 (spoke):**

```text
ping 10.10.255.254
ping <R1_Gi1_IP>
```

**On R1 (hub):**

```text
ping 10.10.255.254
ping <R2_Gi1_IP>
ping <R3_Gi1_IP>
```

Replace `<R1_Gi1_IP>` / `<R2_Gi1_IP>` / `<R3_Gi1_IP>` with the Gi1 addresses from Step 0.

**Paste:** Result of `ping 10.10.255.254` from R2 and `ping <R2_Gi1_IP>` from R1 (success/fail and any loss).

---

## Step 3: PKI certificates (trustpoint CA-ROOT-SELF)

IKEv2 RSA-sig uses the **identity certificate** from trustpoint `CA-ROOT-SELF`. If enrollment or auth failed, there will be no valid cert and no IKEv2 SA.

**On R1, R2, R3 run:**

```text
show crypto pki certificates CA-ROOT-SELF
show crypto pki trustpoints
```

**What we need:**
- **Trustpoint CA-ROOT-SELF** listed and in state “enrolled” or equivalent (not “pending” or missing).
- **Certificates:** At least:
  - **CA Certificate** (issued by CA-ROOT for the root).
  - **Certificate** (router’s own identity cert; subject CN = router FQDN, e.g. `r1.domain.com`).

**If you see “Certificate Name: none” or no identity certificate:** Enrollment didn’t complete. Then run:

```text
show crypto pki certificates CA-ROOT-SELF
crypto pki authenticate CA-ROOT-SELF
```

- **Note:** The EEM applet `CLIENT-PKI-AUTHENTICATE` is **still broken and is to be fixed**. Manual authentication is required.
- **R1 (hub):** From config mode run **authc**, answer **yes**, then **end** and **write memory**. When prompted, the router displays the CA fingerprint — copy it for the spokes.
- **Spokes (R2, R3, …):** Once you have the CA fingerprint from R1 (or from CA-ROOT), on each spoke run from exec: `crypto pki authenticate CA-ROOT-SELF fingerprint <fingerprint>` (no interactive yes), then `write memory`.

To enroll manually, after authenticating run:

```text
crypto pki enroll CA-ROOT-SELF
```

(Use the same FQDN/CN as in your config; you can cancel and fix config if subject doesn’t match.)

**Paste:** Full `show crypto pki certificates CA-ROOT-SELF` from **R1** and **R2**. If enrollment is pending/failed, paste the output of `show crypto pki trustpoints` from one of them too.

---

## Step 4: IKEv2 and IPsec status (before debug)

**On R1 and R2:**

```text
show crypto ikev2 sa
show crypto ipsec sa
show crypto session
```

**Expected when broken:** IKEv2 SA empty or no matching session; IPsec SA empty.

**Paste:** Output of these three commands from **R1** and **R2**.

---

## Step 5: Trigger and capture IKEv2 (debug)

Trigger traffic that should bring up the tunnel (e.g. from spoke to hub overlay), then capture IKEv2.

**On R2 (spoke):**

```text
debug crypto ikev2
```

**On R1 (hub):** (optional but useful)

```text
debug crypto ikev2
```

**Trigger:** From R2 ping the hub’s **tunnel** IP (e.g. 10.20.0.1 or whatever your Tunnel0 on R1 is):

```text
ping 10.20.0.1
```

(Use the actual hub tunnel IP from `show ip interface brief` on R1, Tunnel0.)

Let a few attempts happen (5–10 seconds), then:

**On R2 and R1:**

```text
undebug all
```

**Paste:** The **debug** output from **R2** (and R1 if you have it). Look for:
- IKE_SA_INIT request/response
- Auth/certificate errors (e.g. “certificate invalid”, “clock skew”, “no matching profile”)
- Any “failed” or “rejected” lines

---

## Step 6: Config sanity (IKEv2 profile and match)

TopoGen uses a single profile for all peers (`match identity remote address 0.0.0.0 0.0.0.0`). We only need to confirm it’s present and bound.

**On R1 and R2:**

```text
show run | section crypto ikev2
show run | section crypto ipsec
show run | section Tunnel0
```

**Check:**
- `crypto ikev2 profile TOPGEN-IKEV2` has:
  - `authentication local rsa-sig`
  - `authentication remote rsa-sig`
  - `pki trustpoint CA-ROOT-SELF`
- `crypto ipsec profile TOPGEN-IPSEC` has `set ikev2-profile TOPGEN-IKEV2`
- `interface Tunnel0` has `tunnel protection ipsec profile TOPGEN-IPSEC`

**Paste:** Only if something looks wrong (e.g. different trustpoint, pre-share instead of rsa-sig). Otherwise “config matches” is enough.

---

## Step 7: CA-ROOT and SCEP (if certs were missing or bad)

If in Step 3 certs were missing or enrollment failed, verify CA is up and SCEP is reachable.

**On CA-ROOT:**

```text
show crypto pki server
show crypto pki certificates
show ip http server status
```

**From R2 (spoke):**

```text
curl -v http://10.10.255.254:80
```

(or from router: `test http://10.10.255.254` if available; otherwise a ping is a minimal reachability check — we already did that in Step 2).

**Check:** PKI server “enabled”, CA cert present, HTTP server on. If CA wasn’t started first (before R1/R2/R3), clients can’t enroll; restart CA, wait for it to be ready, then re-enroll from routers.

---

## Summary checklist (order of checks)

| # | Check              | Commands / What to paste                          |
|---|--------------------|----------------------------------------------------|
| 0 | Underlay & roles   | R1: `show ip int brief`, `show run int Gi1`, `show run int Tunnel0` |
| 1 | Clock & NTP        | R1, R2: `show clock`, `show ntp status`           |
| 2 | NBMA reachability  | R2→10.10.255.254, R1→R2 Gi1 ping results          |
| 3 | PKI certs          | R1, R2: `show crypto pki certificates CA-ROOT-SELF` (and trustpoints if not enrolled) |
| 4 | IKEv2/IPsec state | R1, R2: `show crypto ikev2 sa`, `show crypto ipsec sa`, `show crypto session` |
| 5 | IKEv2 debug       | R2 (and R1): `debug crypto ikev2`, then ping hub tunnel IP, then `undebug all` — paste debug |
| 6 | Config            | Only if something looks wrong in profile/trustpoint/tunnel |
| 7 | CA-ROOT/SCEP      | Only if certs missing: CA `show crypto pki server`, HTTP status; R2 reachability to 10.10.255.254 |

---

## Common causes in this lab (TopoGen + IOS-XE)

1. **Time:** CA or routers with wrong clock → cert validity check fails → IKEv2 rejects certs. Fix clock and/or NTP first.
2. **Enrollment order:** CA-ROOT must be up and PKI server enabled before R1/R2/R3 enroll. If you started spokes first, re-enroll after CA is ready.
3. **No identity cert:** Trustpoint shows “pending” or only CA cert → run `crypto pki authenticate` then `crypto pki enroll` and ensure subject-name (CN) matches what IKEv2 will use (FQDN).
4. **Underlay:** No route or ACL blocking 10.10.0.0/16 or UDP 500/4500 → fix routing/ACL so NBMA and IKEv2 ports are reachable.
5. **Profile/trustpoint mismatch:** Rare if you didn’t change config; ensure no second profile or trustpoint overriding (e.g. pre-share left in config).

Reply with the requested pastes (Step 0 R1, Step 1 R1+R2, Step 2 pings, Step 3 R1+R2 certs, Step 4 R1+R2 crypto show, Step 5 R2 debug). From that we can say exactly what to fix next (e.g. “set clock on R2”, “re-enroll R2”, “check NTP to CA”, or “IKEv2 proposal mismatch” and where to change it).
