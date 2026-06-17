<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.8
Date Modified: 2026-03-24

- Called by: Developers and users testing manual PKI import (PEM terminal) on IOS/IOS-XE
- Reads from: PKI.md, tools/gen_pki_openssl.ps1, tools/gen_pki_openssl.sh, tools/gen_pki_manual_test.py
- Writes to: None (documentation only)
- Calls into: References PKI.md, OpenSSL commands, CML/IOS-XE import steps

Purpose: Step-by-step manual test for importing pre-generated CA and router certs via crypto pki import pem terminal.
-->

# Manual PKI import test (IOS / IOS-XE)

Test that pre-generated certs can be imported on **IOS** or **IOS-XE** with `crypto pki import ... pem terminal` so we can later inject them into TopoGen configs and avoid key generation at boot.

**Classic IOS (IOSv):** Use **PKCS#12** import, not PEM terminal. OpenSSL 3 must use **`-legacy`** when creating the .p12 so the container uses RC2/3DES (IOS cannot decode AES-256 PKCS#12). The script outputs `r1.p12` / `r2.p12`. Trustpoint must include **`rsakeypair <name> 2048`**. **PEM terminal:** Use **unencrypted** key only; some images want one combined paste (key + cert + CA) — use `r1_combined.pem`.

**Root CA import quick reference:**  
- **IOS (Classic IOSv)** — import root so the device trusts the CA: see [§5. IOS (Classic IOSv): Root CA import](#5-ios-classic-iosv-root-ca-import).  
- **IOS-XE** — load root cert + key on the CA-ROOT server (static root): see [§6. IOS-XE: Root CA import (CA-ROOT server)](#6-ios-xe-root-ca-import-ca-root-server).

## 1. Generate PEMs (one-time)

From repo root:

```powershell
pip install cryptography
python tools/gen_pki_manual_test.py
```

**Recommended:** Have **OpenSSL** available so router keys can be 3DES-encrypted; many IOS images reject AES-256-CBC and report "Unable to decode key" otherwise.

**OpenSSL on Windows:** OpenSSL is a separate program; Git for Windows bundles it but does not add it to the system PATH, so PowerShell may not find it. Four options:

1. **Git Bash (recommended if you already use Git):** Open the **Git Bash** application (Start → "Git Bash"; do not type `bash` in PowerShell—that runs WSL and can fail with "Nested virtualization is not supported"). In Git Bash, `cd` to the repo then run `bash tools/gen_pki_openssl.sh` or the OpenSSL commands from §7. OpenSSL is in Git Bash’s environment by default.
2. **PowerShell script:** From repo root run `powershell -ExecutionPolicy Bypass -File .\tools\gen_pki_openssl.ps1` (use this if you get "running scripts is disabled"). Otherwise `.\tools\gen_pki_openssl.ps1`. If you see "couldn't create signal pipe", use the Git Bash app (option 1) or native OpenSSL (option 4).

3. **Full path in PowerShell:** Call Git’s OpenSSL directly: `& "C:\Program Files\Git\usr\bin\openssl.exe" version`. You can use this path in scripts or add that folder to your user PATH. Note: when invoked from **Python** (e.g. by `gen_pki_manual_test.py`), Git’s OpenSSL often fails with "couldn't create signal pipe"; use Git Bash for the OpenSSL script, or install native OpenSSL for the Python workflow.
4. **Native Windows build (works everywhere):** Install [Win64 OpenSSL from slproweb](https://slproweb.com/products/Win32OpenSSL.html) (e.g. "Win64 OpenSSL v3.x Light"). During install, choose to copy DLLs to the OpenSSL `/bin` directory; after install, restart the terminal. Then `openssl` works in PowerShell and the Python script can use it for 3DES keys.

This creates in `out/`:

- `ca-key.pem`, `ca-cert.pem` — self-signed Root CA (RSA 2048)
- `r1-key.pem`, `r1-cert.pem` — router R1 key + cert (SAN: R1.virl.lab, R1, 10.10.0.1)

### CA-ROOT certificate fingerprints (record after `crypto pki authenticate`)

When you import the CA cert, the router displays the CA fingerprint. Record it for verification or for use with `enrollment fingerprint` / `--pki-ca-fingerprint` (non-interactive auth).

**Python script (ca-cert.pem):** `gen_pki_manual_test.py` generates a **new** CA each run (random serial, “valid from now”), so the fingerprint **changes every time**. Use only for ad-hoc testing.

| Algorithm | Fingerprint (example; changes each run) |
|-----------|----------------------------------------|
| MD5       | 3A7DEDFA C6B81566 9AE84180 073FC6CF |
| SHA1      | D3900470 D1FA6884 D38AE9A9 0B205185 94632D87 |

**OpenSSL root CA (rootCA.pem):** The scripts `gen_pki_openssl.sh` / `gen_pki_openssl.ps1` use subject `CN=CA-ROOT.virl.lab`. The table below is **example** output for one such cert. If you generate the Root CA **once** and never regenerate it, this fingerprint stays **stable**.

| Algorithm | Fingerprint (example; stable if you never regenerate rootCA.pem) |
|-----------|-------------------------------------------------------------------|
| SHA256    | C8C6E494 1FD5BFA9 4C774A50 4AC813C3 9621F463 CC791047 5CC1DDD2 B01A4402 |
| SHA1      | 0E7B9C8E 88989585 0D79FA6A 65EE3D65 CEC47E8A |
| MD5       | 67C56A08 ECEC2DBA FCCD35D4 6E2AB762 |

To re-print subject, dates, serial, and fingerprints for **your** CA: `python tools/show_root_ca_info.py [path/to/rootCA.pem]` (default `out/rootCA.pem`; requires `pip install cryptography`).

#### Why the fingerprint changes when you regenerate

A certificate fingerprint changes if **any** of these change: subject, issuer, validity timestamps (notBefore/notAfter), serial number, extensions, or public key. The Python script uses a **random serial** and **“valid from now”** timestamp, so every run produces a different fingerprint even if the CN stays the same.

#### Stable fingerprint for hundreds of labs / thousands of routers: generate Root CA once, then freeze

1. Create **one** `rootCA.key` + `rootCA.pem` (e.g. with the OpenSSL commands below).
2. Put **only `rootCA.pem`** into your templates/configs as the trust anchor; distribute it to every router (or use the golden cert-chain method below).
3. Once you have loaded the CA and signed certs successfully, put both the **certificate and key** (e.g. `rootCA.pem`, `rootCA.key`) in the repo under **`proven_certs/`** so you can recreate PKI labs and sign new router certs anytime; the same CA stays the canonical set for all labs (see `proven_certs/README.md`). Do **not** regenerate the root. **Never use these keys in production** — they are only for isolated labs in CML.

That keeps the fingerprint constant because the certificate bytes never change.

**One-time OpenSSL commands (run once, then keep the files):**

```bash
# From repo root; output in out/
mkdir -p out && cd out
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 3650 -out rootCA.pem -subj "/CN=CA-ROOT.virl.lab"
```

Optional: CA key encrypted (password ≥ 8 chars) and still usable for signing:

```bash
openssl genrsa -des3 -out rootCA.key 2048
openssl req -x509 -new -key rootCA.key -sha256 -days 3650 -out rootCA.pem -subj "/CN=CA-ROOT.virl.lab"
```

(You will be prompted for the key passphrase when signing router certs.)

#### Auto-trust on IOS-XE at scale (no fingerprint prompts)

To avoid interactive `crypto pki authenticate` on every router:

1. Import the CA cert **once** on a “golden” router (e.g. `crypto pki authenticate CA-ROOT-SELF` and paste the PEM).
2. On that router, run `show run` and copy the generated **`crypto pki certificate chain CA-ROOT-SELF`** block (the certificate lines under that command).
3. Paste that block into your TopoGen templates (or config snippet) so **every** router boots with the same CA chain already in place.

Then no router needs to accept a fingerprint prompt; the chain is already trusted.

## 2. On the router (IOS or IOS-XE)

Use a single router (e.g. one node from a small DMVPN lab) in config mode.

### Step A: Create trustpoint

**Classic IOS (IOSv)** — include `rsakeypair` and `enrollment terminal`:

```
crypto pki trustpoint CA-ROOT-SELF
 enrollment terminal
 revocation-check none
 rsakeypair CA-ROOT-SELF 2048
exit
```

**IOS-XE** — same, or without `rsakeypair` if you prefer:

```
crypto pki trustpoint CA-ROOT-SELF
 enrollment terminal
 revocation-check none
exit
```

### Step B (classic IOS / IOSv): Import options

**Option A — Key import then certificate (Grok-style)**  
Script now outputs **r1.pub** (from `openssl rsa -in r1.key -pubout -out r1.pub`). On the router:

1. `crypto key import rsa CA-ROOT-SELF pem terminal`  
   Paste **r1.pub**, then **quit**. Paste **r1.key** (unencrypted), then **quit**.
2. `crypto pki import CA-ROOT-SELF certificate pem terminal`  
   Paste **r1.pem**, then **quit**. Paste **rootCA.pem** if prompted, then **quit**.

**Option B — PKCS#12 (.p12)**

Use the **.p12** file (generated with `-legacy` so IOS can decode it). Put `r1.p12` on a TFTP server or copy to flash, then:

```
crypto pki import CA-ROOT-SELF pkcs12 tftp://<tftp-ip>/r1.p12 password TopoGenPKI2025
```

Or from flash (after copying the file there):

```
crypto pki import CA-ROOT-SELF pkcs12 flash:r1.p12 password TopoGenPKI2025
```

Then verify: `show crypto pki certificates CA-ROOT-SELF`. Skip to Step D.

### Step B (PEM terminal): Import certificate

```
crypto pki import CA-ROOT-SELF certificate pem terminal
```

Then paste the **entire** contents of `out/r1-cert.pem` (including `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----`).  
Then type:

```
quit
```

### Step C: Import the router private key (Router-cert: use same passphrase)

Router keys are generated with passphrase **TopoGenPKI2025** (14 chars). You must use it on import:

```
crypto pki import Router-cert pem terminal password TopoGenPKI2025
```

**Option 1 — One combined paste (some IOS):** Paste the entire contents of **r1_combined.pem** (unencrypted key + router cert + CA cert in one file), then type **quit**.

**Option 2 — Separate prompts:** Paste in the order the router asks: **rootCA.pem** → **r1.key** (unencrypted only; encrypted keys often cause "Unable to decode key") → **r1.pem**, then **quit**.

Paste the **entire** contents of each file (including `-----BEGIN ... -----` and `-----END ... -----`).  
Then type:

```
quit
```

### Step D: Verify

```
show crypto pki certificates CA-ROOT-SELF
```

You should see the certificate and that the trustpoint has a private key.

### Step E: Use in IKEv2 (optional)

If the router already has an IKEv2 profile that references `pki trustpoint CA-ROOT-SELF`, the tunnel should be able to use this identity. Test with a second router that has the same CA and its own imported cert, or with an existing DMVPN lab where one node uses the imported cert.

## 3. Notes

- **Password:** Router keys are encrypted with passphrase **TopoGenPKI2025**. Use `password TopoGenPKI2025` on the import command so the router can decrypt the key.
- **Key encryption:** Many **IOS** and IOS-XE images cannot decode AES-256-CBC or PKCS#8 PEM keys and report "Unable to decode key". **Classic IOS** (e.g. IOSv) is often stricter: try **unencrypted** (`r1.key`), then **single DES** (`r1_des.key` from the OpenSSL script), then 3DES. The Python script uses OpenSSL for 3DES when available; the OpenSSL script (`gen_pki_openssl.ps1` / `.sh`) outputs `r1.key`, `r1_des.key`, and `r1_traditional.key` so you can try each.
- **CA chain:** For IKEv2 rsa-sig, the peer must trust the CA. If the other side only has the CA cert, you may need to import the CA certificate as well (e.g. under the same trustpoint or a separate one, depending on IOS/IOS-XE version).
- **SAN:** The generated router cert includes Subject Alternative Name (IP + FQDN + hostname) so IKEv2 identity checks pass with minimal fuss.

### Successful import verification (output reference)

After a successful **crypto pki import &lt;name&gt; pem terminal password &lt;pass&gt;** (CA cert → encrypted key → identity cert), the router stores:

**`show crypto pki certificates`** shows two blocks per trustpoint:

| Field | Meaning |
|-------|--------|
| **Certificate** (first block) | Router identity cert (CN=R1, R2, …). **Certificate Serial Number (hex)** is the cert’s serial. **Issuer** = CA (e.g. cn=CA-ROOT.virl.lab). **Subject** = this device (e.g. cn=R2). **Validity Date** = start/end. **Associated Trustpoints** = trustpoint name. **Storage** = nvram filename (e.g. `nvram:TopoGen-Root#711D.cer`). |
| **CA Certificate** (second block) | Root (or intermediate) CA cert. **Serial**, **Issuer**, **Subject**, **Validity**, **Associated Trustpoints**, **Storage** (e.g. `nvram:TopoGen-Root#56BECA.cer`). |

**`show run \| sec &lt;trustpoint&gt;`** (e.g. `show run | sec R2`) shows:

- **crypto pki trustpoint** stanza (enrollment terminal, revocation-check none, rsakeypair).
- **crypto pki certificate chain &lt;name&gt;** with:
  - **certificate &lt;serial_hex&gt;** — identity cert (hex blob; serial matches `show crypto pki certificates`).
  - **certificate ca &lt;serial_hex&gt;** — CA cert (hex blob).

Serial numbers and **Storage** filenames vary per device and per cert; the *structure* (identity cert + CA cert, both with serial and hex) is what indicates success. Private keys are in private-config and are not shown in `show run`.

## 4. If import fails

- **"Unable to decode key" / "PEM files import failed":** The router likely does not support the key’s encryption (e.g. AES-256-CBC). **Classic IOS** (e.g. IOSv): try **r1.key** (unencrypted), then **r1_des.key**, then **r1_traditional.key**. Regenerate with the OpenSSL script if needed.
- Ensure no extra spaces or line breaks when pasting; the PEM block must be complete.
- On some images, `pem terminal` may expect a specific prompt; try pasting line-by-line if block paste fails.
- Check `show crypto pki certificates` and `show crypto pki trustpoints` after each step.

---

## 5. IOS (Classic IOSv): Root CA import

Use this on **Classic IOS (IOSv)** to make the router **trust** the root CA (e.g. for IKEv2 or before importing a router identity cert). Classic IOS does not run `crypto pki server`; this is client-side only.

1. **Create trustpoint** (if not already):
   ```
   crypto pki trustpoint CA-ROOT-SELF
    enrollment terminal
    revocation-check none
    rsakeypair CA-ROOT-SELF 2048
   exit
   ```

2. **Import the root CA certificate only** — authenticate (paste root cert):
   ```
   crypto pki authenticate CA-ROOT-SELF
   ```
   Paste the full contents of **rootCA.pem** (from `out/` or OpenSSL §7), then **quit**. The router shows the CA fingerprint; confirm with **y** if prompted.

3. **Verify:** `show crypto pki certificates CA-ROOT-SELF` — you should see the CA certificate. You can then import a router identity (key + cert) under the same trustpoint, or use PKCS#12 which bundles identity + CA.

**Alternative:** When doing a full identity import with `crypto pki import <name> pem terminal`, the router may prompt for the CA cert first; paste **rootCA.pem** when asked, then the key and identity cert.

---

## 6. IOS-XE: Root CA import (CA-ROOT server)

Use this on the **CA-ROOT** router (IOS-XE) so the PKI server uses a pre-generated root cert and key (same fingerprint every time). Server must start in **shutdown**; load the PEMs, then **no shutdown**.

**Init config (no key generate, enrollment terminal only):**
```
crypto pki server CA-ROOT
 database level complete
 no database archive
 grant auto
 lifetime certificate 7300
 lifetime ca-certificate 7300
 database url flash:
 shutdown
!
ip http secure-server
ip http secure-trustpoint CA-ROOT-SELF
!
crypto pki trustpoint CA-ROOT-SELF
 enrollment terminal
 revocation-check none
 rsakeypair CA-ROOT-SELF 2048
!
```

**Import (unencrypted root key):** Use **no** `password` — IOS-XE treats `password` as requiring a value on the same line (% Incomplete command if you leave it blank).
```
crypto pki import CA-ROOT-SELF pem terminal
```
Paste **rootCA.pem** → **quit** → paste **rootCA.key** → **quit** → **quit**.

**Import (encrypted root key):** Passphrase must be on the same line:
```
crypto pki import CA-ROOT-SELF pem terminal password YourPassPhrase
```
Then paste **rootCA.pem** → **quit** → paste encrypted key PEM → **quit** → **quit**.

**Then bring up the server:**
```
crypto pki server CA-ROOT
 no shutdown
 exit
```

---

## 7. Alternative: OpenSSL-only generation

If you prefer to generate all PKI assets with OpenSSL only (no Python script), use the following. These commands produce PEMs compatible with `crypto pki import ... pem terminal` as referenced in [PKI.md](../PKI.md) and the DMVPN templates (e.g. `iosv-dmvpn.jinja2`).

### Step A: Generate the Root CA (private key and self-signed certificate)

```bash
# Generate Root CA private key
openssl genrsa -out rootCA.key 2048

# Generate self-signed Root certificate
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 7300 -out rootCA.pem \
  -subj "/CN=CA-ROOT.virl.lab"
```

### Step B: Generate the router private key

```bash
openssl genrsa -out router.key 2048
```

### Step C: Create a CSR for the router (with SAN)

```bash
openssl req -new -key router.key -out router.csr \
  -subj "/CN=R1" \
  -addext "subjectAltName = IP:10.10.0.1, DNS:R1.virl.lab"
```

### Step D: Sign the router certificate with the Root CA

```bash
openssl x509 -req -in router.csr -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
  -out router.pem -days 7300 -sha256 -copy_extensions copyall
```

### Step E: Encrypt the router key for import

Many IOS/IOS-XE images accept only **traditional PEM** (BEGIN RSA PRIVATE KEY, Proc-Type: 4,ENCRYPTED), not PKCS#8. Use **-traditional**:

```bash
openssl rsa -in r1.key -des3 -out r1_traditional.key -passout "pass:R1Pass123" -traditional
```

For R2 (or any router), change the label and password (e.g. `r2.key` → `r2_traditional.key`, `pass:R2Pass123`). Use this file when the router prompts for the encrypted private key; the password goes in `crypto pki import <name> pem terminal password <pass>`.

Optional: PKCS#8 for images that accept it:

```bash
openssl pkcs8 -topk8 -v1 PBE-SHA1-3DES -in router.key -out router_encrypted.key -passout pass:TopoGenPKI2025
```

### Exact OpenSSL commands (copy-paste, one router)

Run from a shell with `openssl` on PATH, from the repo root; output goes in `out/`. Replace `R1` / `r1` / `10.10.0.1` / `R1Pass123` for another router (e.g. R2 → `10.10.0.2`, `r2.virl.lab`, `R2Pass123`).

**Root CA (one-time):**

```bash
openssl genrsa -out out/rootCA.key 2048
openssl req -x509 -new -nodes -key out/rootCA.key -sha256 -days 7300 -out out/rootCA.pem -subj "/CN=CA-ROOT.virl.lab"
```

**Router R1 (key + cert + traditional encrypted key):**

```bash
openssl genrsa -out out/r1.key 2048
openssl rsa -in out/r1.key -pubout -out out/r1.pub
openssl rsa -in out/r1.key -des3 -out out/r1_traditional.key -passout "pass:R1Pass123" -traditional
openssl req -new -key out/r1.key -out out/r1.csr -subj "/CN=R1" -addext "subjectAltName=IP:10.10.0.1,DNS:r1.virl.lab"
openssl x509 -req -in out/r1.csr -CA out/rootCA.pem -CAkey out/rootCA.key -CAcreateserial -out out/r1.pem -days 7300 -sha256 -copy_extensions copyall
```

Optional cleanup (so only the files needed for import remain):

```bash
rm -f out/r1.key out/r1.csr out/rootCA.srl
```

**Router R2 (same pattern):**

```bash
openssl genrsa -out out/r2.key 2048
openssl rsa -in out/r2.key -pubout -out out/r2.pub
openssl rsa -in out/r2.key -des3 -out out/r2_traditional.key -passout "pass:R2Pass123" -traditional
openssl req -new -key out/r2.key -out out/r2.csr -subj "/CN=R2" -addext "subjectAltName=IP:10.10.0.2,DNS:r2.virl.lab"
openssl x509 -req -in out/r2.csr -CA out/rootCA.pem -CAkey out/rootCA.key -CAcreateserial -out out/r2.pem -days 7300 -sha256 -copy_extensions copyall
rm -f out/r2.key out/r2.csr out/rootCA.srl
```

On Windows (PowerShell), use `out\r1.key` etc. and `Remove-Item out\r1.key -Force` for cleanup.

### Step F: Import into IOS-XE

Create the trustpoint and import in one go:

```text
crypto pki trustpoint CA-ROOT-SELF
 enrollment terminal
 revocation-check none
exit

crypto pki import CA-ROOT-SELF pem terminal password TopoGenPKI2025
```

Then paste, in the order the router prompts (often **CA cert** → **private key** → **router cert**; follow the prompts):

1. Contents of **rootCA.pem**
2. Contents of **router_encrypted.key** (or **router.key** if unencrypted)
3. Contents of **router.pem**

Type **quit** after each block if prompted, then **quit** again to exit the command.

### Cisco documentation

For official syntax, enrollment options (SCEP vs terminal), and PKI behavior on IOS-XE:

- [Cisco IOS-XE PKI Configuration Guide (XE 16)](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_conn_pki/configuration/xe-16/sec-pki-xe-16-book/sec-pki-enroll.html)  
  Key sections: **Certificate enrollment via terminal**, **Importing and exporting RSA keys**, **PKI interoperability**.
