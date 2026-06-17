# Generate PKI for IOSv routers using OpenSSL (PowerShell).
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-02-21
#
# - Called by: Users (CLI); docs/MANUAL-PKI-IMPORT-TEST.md
# - Reads from: Repo root path, out/
# - Writes to: out/ (rootCA.*, r1.*, r2.*, *.p12, etc.)
# - Calls into: openssl
#
# Run from repo root:  powershell -ExecutionPolicy Bypass -File .\tools\gen_pki_openssl.ps1
# If scripts are disabled, the above bypasses for this run only. Or: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# Uses Git's OpenSSL if found (C:\Program Files\Git\usr\bin\openssl.exe); otherwise requires openssl on PATH.
# If you see "couldn't create signal pipe", run this from a normal PowerShell (not inside some sandboxes/IDEs) or run the .sh script in the Git Bash application instead.

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
$Out = Join-Path $RepoRoot "out"
$Pass = "TopoGenPKI2025"

$openssl = $null
if (Get-Command openssl -ErrorAction SilentlyContinue) { $openssl = "openssl" }
elseif (Test-Path "C:\Program Files\Git\usr\bin\openssl.exe") { $openssl = "C:\Program Files\Git\usr\bin\openssl.exe" }
elseif (Test-Path "C:\Program Files (x86)\Git\usr\bin\openssl.exe") { $openssl = "C:\Program Files (x86)\Git\usr\bin\openssl.exe" }
if (-not $openssl) { throw "OpenSSL not found. Install Git for Windows and run from Git Bash, or install native OpenSSL and add to PATH." }

New-Item -ItemType Directory -Force -Path $Out | Out-Null
Push-Location $Out

try {
    Write-Host "Generating Root CA..."
    & $openssl genrsa -out rootCA.key 2048
    & $openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 7300 -out rootCA.pem -subj "/CN=CA-ROOT.virl.lab"

    @("R1:10.10.0.1", "R2:10.10.0.2") | ForEach-Object {
        $name = $_; $r = $name.Split(":")[0]; $ip = $name.Split(":")[1]
        $rLower = $r.ToLowerInvariant()
        Write-Host "Generating $r (IP $ip)..."
        & $openssl genrsa -out "$rLower.key" 2048
        & $openssl rsa -in "$rLower.key" -pubout -out "$rLower.pub"
        & $openssl req -new -key "$rLower.key" -out "$rLower.csr" -subj "/CN=$r" -addext "subjectAltName = IP:$ip, DNS:${rLower}.virl.lab"
        & $openssl x509 -req -in "$rLower.csr" -CA rootCA.pem -CAkey rootCA.key -CAcreateserial -out "$rLower.pem" -days 7300 -sha256 -copy_extensions copyall
        & $openssl pkcs8 -topk8 -v1 PBE-SHA1-3DES -in "$rLower.key" -out "${rLower}_encrypted.key" -passout "pass:$Pass"
        # Traditional PEM: 3DES and single DES (some IOS-XE only accept DES).
        & $openssl rsa -in "$rLower.key" -des3 -out "${rLower}_traditional.key" -passout "pass:$Pass"
        & $openssl rsa -in "$rLower.key" -des -out "${rLower}_des.key" -passout "pass:$Pass"
        Remove-Item -Force "$rLower.csr" -ErrorAction SilentlyContinue
        # PKCS#12 for classic IOS (IOSv): -legacy forces RC2/3DES so IOS can decode (OpenSSL 3 uses AES-256 otherwise).
        & $openssl pkcs12 -export -inkey "$rLower.key" -in "$rLower.pem" -certfile rootCA.pem -out "${rLower}.p12" -passout "pass:$Pass" -legacy 2>$null
        if (-not $?) { & $openssl pkcs12 -export -inkey "$rLower.key" -in "$rLower.pem" -certfile rootCA.pem -out "${rLower}.p12" -passout "pass:$Pass" }
        # Single file for PEM terminal: unencrypted key + router cert + CA cert (paste once).
        $combined = Get-Content "$rLower.key" -Raw; $combined += "`n" + (Get-Content "$rLower.pem" -Raw); $combined += "`n" + (Get-Content "rootCA.pem" -Raw)
        Set-Content -Path "${rLower}_combined.pem" -Value $combined.TrimEnd() -NoNewline
    }
    Remove-Item -Force rootCA.srl -ErrorAction SilentlyContinue
    Write-Host "Done."
    Write-Host "  Classic IOS (IOSv): use r1.p12 with 'crypto pki import TP pkcs12 ...' (pass: $Pass). Trustpoint needs rsakeypair NAME 2048."
    Write-Host "  PEM terminal: paste r1_combined.pem (key+cert+CA in one blob), or r1.key (unencrypted) if router prompts separately."
    Write-Host "  Key-import flow: crypto key import rsa <name> pem terminal -> paste r1.pub, then r1.key; then crypto pki import TP certificate -> paste r1.pem."
}
finally {
    Pop-Location
}
