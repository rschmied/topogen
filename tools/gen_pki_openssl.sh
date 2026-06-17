#!/usr/bin/env bash
# Generate PKI for IOSv routers using OpenSSL only.
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-02-21
#
# - Called by: Users (CLI); docs/MANUAL-PKI-IMPORT-TEST.md
# - Reads from: Repo root path, out/
# - Writes to: out/ (rootCA.*, r1.*, r2.*, etc.)
# - Calls into: openssl
#
# Run from repo root. Requires: openssl on PATH.
# On Windows: open the "Git Bash" app (do not run `bash` from PowerShell—that starts WSL and can fail with "Nested virtualization is not supported"). In Git Bash, OpenSSL is on PATH.
# Output: out/rootCA.key, out/rootCA.pem, out/r1.key, out/r1.pem, out/r1_encrypted.key, out/r2.key, out/r2.pem, out/r2_encrypted.key

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO_ROOT/out"
mkdir -p "$OUT"
cd "$OUT"

PASS=TopoGenPKI2025

echo "Generating Root CA..."
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 7300 -out rootCA.pem \
  -subj "/CN=CA-ROOT.virl.lab"

for name in R1:10.10.0.1 R2:10.10.0.2; do
  r="${name%%:*}"
  ip="${name##*:}"
  echo "Generating $r (IP $ip)..."
  openssl genrsa -out "${r,,}.key" 2048
  openssl req -new -key "${r,,}.key" -out "${r,,}.csr" \
    -subj "/CN=$r" \
    -addext "subjectAltName = IP:$ip, DNS:${r,,}.virl.lab"
  openssl x509 -req -in "${r,,}.csr" -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
    -out "${r,,}.pem" -days 7300 -sha256 -copy_extensions copyall
  openssl pkcs8 -topk8 -v1 PBE-SHA1-3DES -in "${r,,}.key" -out "${r,,}_encrypted.key" -passout "pass:$PASS"
  rm -f "${r,,}.csr"
done
rm -f rootCA.srl 2>/dev/null || true

echo "Done. Use rootCA.pem, r1.pem, r1_encrypted.key (and r2.*) for crypto pki import ... pem terminal password $PASS"
