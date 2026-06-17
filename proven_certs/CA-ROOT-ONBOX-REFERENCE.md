<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.3
Date Modified: 2026-02-22

- Called by: Users documenting the on-box CA-ROOT (IOS-XE PKI server) state
- Reads from: None (reference only)
- Writes to: None
- Calls into: None

Purpose: Full reference for the CA-ROOT certificate server when running on IOS-XE (e.g. in CML).
         Lab use only. Includes server status, fingerprint, public key, and exported private key.
-->

# CA-ROOT on-box reference (IOS-XE PKI server)

Full capture from an IOS-XE CA-ROOT device (e.g. in CML). Lab use only.

## show crypto pki server CA-ROOT

```
Certificate Server CA-ROOT:
    Status: enabled
    State: enabled
    Server's configuration is locked  (enter "shut" to unlock it)
    Issuer name: CN=CA-ROOT
    CA cert fingerprint: 6FE17753 BC6791CA BE38722A 63E4401F
    Granting mode is: auto
    Last certificate issued serial number (hex): 1
    CA certificate expiration timer: 22:07:38 UTC Feb 17 2046
    CRL NextUpdate timer: 04:07:38 UTC Feb 23 2026
    Current primary storage dir: flash:
    Database Level: Complete - all issued certs written as <serialnum>.cer
```

## show crypto pki certificates verbose CA-ROOT

```
CA-ROOT#show crypto pki certificates verbose CA-ROOT
CA Certificate
  Status: Available
  Version: 3
  Certificate Serial Number (hex): 01
  Certificate Usage: Signature
  Issuer:
    cn=CA-ROOT
  Subject:
    cn=CA-ROOT
  Validity Date:
    start date: 00:08:38 UTC Feb 22 2026
    end   date: 00:08:38 UTC Feb 17 2046
  Subject Key Info:
    Public Key Algorithm: rsaEncryption
    RSA Public Key: (2048 bit)
  Signature Algorithm: MD5 with RSA Encryption
  Fingerprint MD5: 796D8F17 F3E22A2E DADC2587 211ABA9A
  Fingerprint SHA1: 481A6986 4DEEE366 883F1E48 6BE3451D D037CF70
  X509v3 extensions:
    X509v3 Key Usage: 86000000
      Digital Signature
      Key Cert Sign
      CRL Signature
    X509v3 Subject Key ID: 9E5BA777 18286333 F7D8A36A 6C99633E 26560D07
    X509v3 Basic Constraints:
        CA: TRUE
    X509v3 Authority Key ID: 9E5BA777 18286333 F7D8A36A 6C99633E 26560D07
    Authority Info Access:
Cert install time: 00:08:38 UTC Feb 22 2026
  Associated Trustpoints: CA-ROOT-SELF CA-ROOT
  Storage: nvram:CA-ROOT#1CA.cer
CA-ROOT#
```

Use this to see full CA cert details and **Fingerprint MD5/SHA1** for the cert this CA-ROOT is using (e.g. for `enrollment fingerprint` in client configs). Serial 01 and install time indicate a fresh self-enrolled CA; fingerprint will differ from another lab’s CA.

**Validity vs. original exported cert (6FE17753):** The **end** date is the same (Feb 17 2046) because both use the same lifetime. The **start** date differs: the original was created ~22:07 UTC Feb 22 2026 (see "CA certificate expiration timer" and key generation time in this doc); the cert above was created 00:08:38 UTC Feb 22 2026. Different creation time → different notBefore → different fingerprint even with the same CN and end date.

## crypto key export rsa CA-ROOT pem terminal 3des cisco123

Export command used: `crypto key export rsa CA-ROOT pem terminal 3des cisco123`  
Password: **cisco123**

### Public key (PEM)

```
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAnd4RUJoZNbYpMQiXA/qb
B9VrmjLjGGezE6Q/VDhpXZR3Fj56+EDSfLVE+wBjkM87QK9B7PNbxWcCw/bHRmol
hCar2/S0xQOkX3jMsGa2wTDC/Mc8u0rYS+Jb1xtr5lhbiuocX13P1u+2sM/wyhlw
BaqDFXdNJXVq9i+qsV53zam7GWabP3ukOvjaBfdXZ692KxYXVq/NDNXgT1d0Z1so
+zex7IwiMWKY3AH+V8GeNMegDfv/+oqhnEDFESPVmiTo8PSggNdMg3so68ExOF0B
c9GRKtpX8pS8GGBty1p3c9GWolpYDGUsz6Djm9H37bUWaqSdhkYkZVoPdoSsZHXx
fQIDAQAB
-----END PUBLIC KEY-----
```

base64 len 1642

### Private key (PEM, 3DES-encrypted, password cisco123)

```
-----BEGIN RSA PRIVATE KEY-----
Proc-Type: 4,ENCRYPTED
DEK-Info: DES-EDE3-CBC,130309A7311079CA

0kyk15GaEper7+w8AooHRl+js5keLoja/ir5DnwyAbdwugsyvCxIDBGs7APC81de
TsBumwHDoxW171FmDOagn5yhnEun+vxYAsToS0u2ZZhrKN9O+kmIfVs963TkVQXX
B0mWBoOwVOgZ+2wH74qKu8meovk6TIFcz9qvqXaJvVS0hcce5diYx58jSV4PgeLr
v2K1KK/6ag0qGh5jnAV4LyZEpuaB2eaKsCXAwxkgqtFAk7TZasEaH7FMUYUGRzZ7
VhdOpgYMRxCDn3/8WXK/bON6sGlEYZ75VlLqbDLASstJh6RMNvwnNaAnNXx4ssX+
TIeYkrFecBJcL4Axcc7yc4UPxVqtOQkiGAxbqPDP+SiWy6MJOMy8jUN/HscQUvz5
MFLJtIyvbNJjAAX2cTFZ4Fe1ukxZ6WECbFRjUgPLjAxstuigQXPM+NyNMtt1jqKR
FRGXzN27SKd60pl/uYKAPWp/NPtoPKz9SOa/D1Y5/jh5wRwcNsP1W/fuLQ0goNU4
xPDk1lYNqK5OtiTlRtYYTsjd3qvAFg40Eqly2IxlXu5JX9Lgw9yFwYBmU53cEgUY
e5gL1zGASKWoBTqZjDljn0Wgy1THoqHMDUA/K9h8ZywT39sOtS5gNg/hmEWW0QZC
5r9kSjNk59BdYTey40V0tjy8F/U0I62kGRuZo+iVGTaziLqL68Y0sD3TOGwQLh/O
xRYVkpW9VDbo6mvnQJ3KkrPobKBDC+kqBy64e15f5d3gAQ7mO4UMzI+y7LPrzeoV
9s336Quloda16LgCYrGaeajZODJ1MJu4bZLs03q0Y8IYATz5/xOaWF108FotP7DZ
xxbGmTIN/5vUbPq/5SvP97i2NZaG1Kkv1EaH5EYY+NVM4x4qJLxBV+ugWFRyule4
ilC11Ro1xQgUgmxMmE2y2rpyzg+zOnthFaSsvSvWWAym03eT4btc4r/sHcv/FgC2
jpn+o/YrRf5lWr7knVmOWkAmAvIYstM2vM3R3Mf/EEL6okbSSnXpNZJ9oMH0Otzh
S09cXrgQOpPSaDIMRXPLrqbViN6kRIz5ulYC6xnlDJDsyFbgcjE4eEDgDH5muojK
oFbTF/iZQCGVQkgp+g2/42dIcpqV1wj6SJXk6xPhsKANTA3DCC7zp97lCih1gSMt
PB61NqznPzpuBpMn1TZVj8gE9ZgkgCFmevWbQXayYYWQ0lJNP7jpOuJ+VQ+mSG70
MhCXnqtWYCT3sNjyPEmKPEdhJsuE4UpnWnzP4180IcUe6PlRVlM+yy22gpm9/BD+
3o/juxKWiuAyreQI0pz5UnFzgcQNPGn2jLf5L/CZpV6b7uhk2CVG/oQRPe+qpkpE
UpMK2e8O7INHaPRnUluI7faUeLURcB917fYxS374+EsBHZ5guWhF19milkmH9WKu
3hH68PdMnQApMrIFXEaWWf+IVLO9ovWxtozsS2Ld1S7LfBS+EiQAkRYrskaHa3uf
N+3k6lEFxjT8tz1IzYImdUe3W7Fgzb0L5kteqpjuyjtVoGe2jZwlCCx0n8DgJdKI
cIWOR3xDsl2yiedOe7nEF8yl6SDMmgy+4rHQxasd1ZeYy4JUh7nacg==
-----END RSA PRIVATE KEY-----
```

## show crypto key my rsa CA-ROOT

```
CA-ROOT#sh crypto key my rsa CA-ROOT
% Key pair was generated at: 22:07:18 UTC Feb 22 2026
Key name: CA-ROOT
Key type: RSA KEYS
 Storage Device: private-config
 Usage: General Purpose Key
 Key is exportable. Redundancy enabled.
 Key Data:
  30820122 300D0609 2A864886 F70D0101 01050003 82010F00 3082010A 02820101
  009DDE11 509A1935 B6293108 9703FA9B 07D56B9A 32E31867 B313A43F 5438695D
  9477163E 7AF840D2 7CB544FB 006390CF 3B40AF41 ECF35BC5 6702C3F6 C7466A25
  8426ABDB F4B4C503 A45F78CC B066B6C1 30C2FCC7 3CBB4AD8 4BE25BD7 1B6BE658
  5B8AEA1C 5F5DCFD6 EFB6B0CF F0CA1970 05AA8315 774D2575 6AF62FAA B15E77CD
  A9BB1966 9B3F7BA4 3AF8DA05 F75767AF 762B1617 56AFCD0C D5E04F57 74675B28
  FB37B1EC 8C223162 98DC01FE 57C19E34 C7A00DFB FFFA8AA1 9C40C511 23D59A24
  E8F0F4A0 80D74C83 7B28EBC1 31385D01 73D1912A DA57F294 BC18606D CB5A7773
  D196A25A 580C652C CFA0E39B D1F7EDB5 166AA49D 86462465 5A0F7684 AC6475F1
  7D020301 0001
CA-ROOT#
```

---

## Test: Rebuild this CA

To verify you can reuse this CA (same fingerprint everywhere), you need the **CA certificate** in addition to the key above. Then you can restore the trust anchor on another device or confirm clients see the same fingerprint.

### 1. Get the CA certificate PEM (on original CA-ROOT)

On the router that is running this CA:

```
show crypto pki certificates CA-ROOT-SELF
```

Copy the **Certificate** section (from `-----BEGIN CERTIFICATE-----` through `-----END CERTIFICATE-----`) and add it below (or save as `proven_certs/ca-ROOT-cert.pem`). If the server uses a different trustpoint name, use that in the command. Alternatively, the PKI server may have written the CA cert to flash (e.g. in the database dir); you can copy that file and paste its contents here.

**CA certificate (paste here after exporting from router):**

```
-----BEGIN CERTIFICATE-----
(paste from show crypto pki certificates)
-----END CERTIFICATE-----
```

### 2. Test A — Verify fingerprint on a client router

On a **client** router (e.g. R1 in the same lab):

1. Create trustpoint: `crypto pki trustpoint CA-ROOT-SELF` / `enrollment terminal` / `revocation-check none` / `exit`.
2. Import the CA certificate only:  
   `crypto pki import CA-ROOT-SELF certificate pem terminal`  
   Paste the CA cert PEM (from step 1), then **quit**.
3. Verify:  
   `show crypto pki certificates CA-ROOT-SELF`  
   The CA certificate fingerprint should be **6FE17753 BC6791CA BE38722A 63E4401F** (same as this reference).

### 3. Test B — Restore CA server on another device (optional)

To run the same CA identity on a **new** CA-ROOT router (e.g. after replacing the node):

1. Create trustpoint (e.g. CA-ROOT-SELF) with `enrollment terminal`, `revocation-check none`.
2. Import the **private key**:  
   `crypto key import rsa CA-ROOT pem terminal`  
   Paste the **public key** from this doc, then **quit**. Paste the **private key** (from this doc), then **quit**; when prompted for the passphrase, enter **cisco123**.
3. Import the **CA certificate**:  
   `crypto pki import CA-ROOT-SELF certificate pem terminal`  
   Paste the CA cert PEM (from step 1), then **quit**.
4. Configure the PKI server to use this key/cert (server config and `crypto pki server CA-ROOT` with the same database/URL as your lab). Platform behavior may differ; if the server insists on generating its own key, you may need to use a static/imported root flow instead.

After step 2 and 3, `show crypto pki certificates` should show the same CA cert and fingerprint **6FE17753 BC6791CA BE38722A 63E4401F**.
