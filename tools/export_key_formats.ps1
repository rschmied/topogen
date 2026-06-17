# Export one private key in every common PEM format so you can test which IOS accepts.
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-02-21
#
# - Called by: Users (CLI); docs/MANUAL-PKI-IMPORT-TEST.md
# - Reads from: out/r1.key (unencrypted)
# - Writes to: out/ (r1_plain.key, r1_des.key, r1_3des.key, r1_traditional.key, r1_pkcs8_*.key, etc.)
# - Calls into: openssl
#
# Run from repo root:  powershell -ExecutionPolicy Bypass -File .\tools\export_key_formats.ps1
# Requires: existing out/r1.key (unencrypted). If missing, run gen_pki_openssl.ps1 first.
# Passphrase for encrypted outputs: TopoGenPKI2025

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
$Out = Join-Path $RepoRoot "out"
$KeyIn = Join-Path $Out "r1.key"
$Pass = "TopoGenPKI2025"

$openssl = $null
if (Get-Command openssl -ErrorAction SilentlyContinue) { $openssl = "openssl" }
elseif (Test-Path "C:\Program Files\Git\usr\bin\openssl.exe") { $openssl = "C:\Program Files\Git\usr\bin\openssl.exe" }
elseif (Test-Path "C:\Program Files (x86)\Git\usr\bin\openssl.exe") { $openssl = "C:\Program Files (x86)\Git\usr\bin\openssl.exe" }
if (-not $openssl) { throw "OpenSSL not found." }
if (-not (Test-Path $KeyIn)) { throw "Missing out/r1.key. Run gen_pki_openssl.ps1 first." }

Push-Location $Out
try {
    $formats = @(
        @{ Name = "r1_plain.key";       Cmd = @("rsa", "-in", "r1.key", "-out", "r1_plain.key") },
        @{ Name = "r1_des.key";         Cmd = @("rsa", "-in", "r1.key", "-des", "-out", "r1_des.key", "-passout", "pass:$Pass") },
        @{ Name = "r1_3des.key";        Cmd = @("rsa", "-in", "r1.key", "-des3", "-out", "r1_3des.key", "-passout", "pass:$Pass") },
        @{ Name = "r1_pkcs8_3des.key";  Cmd = @("pkcs8", "-topk8", "-v1", "PBE-SHA1-3DES", "-in", "r1.key", "-out", "r1_pkcs8_3des.key", "-passout", "pass:$Pass") },
        @{ Name = "r1_pkcs8_des.key";   Cmd = @("pkcs8", "-topk8", "-v1", "PBE-SHA1-DES", "-in", "r1.key", "-out", "r1_pkcs8_des.key", "-passout", "pass:$Pass") }
    )
    foreach ($f in $formats) {
        Write-Host "Writing $($f.Name)..."
        & $openssl $f.Cmd
        if (-not $?) { Write-Warning "  OpenSSL failed for $($f.Name)" }
    }
    Write-Host ""
    Write-Host "Done. Try each key on the router (paste when it asks for private key). Use password: $Pass"
    Write-Host "  r1_plain.key       = unencrypted"
    Write-Host "  r1_des.key         = RSA PRIVATE KEY, single DES"
    Write-Host "  r1_3des.key        = RSA PRIVATE KEY, 3DES"
    Write-Host "  r1_pkcs8_3des.key  = ENCRYPTED PRIVATE KEY, PBE-SHA1-3DES"
    Write-Host "  r1_pkcs8_des.key   = ENCRYPTED PRIVATE KEY, PBE-SHA1-DES"
}
finally { Pop-Location }
