#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-02-21
#
# - Called by: Users (CLI)
# - Reads from: out/rootCA.pem (or path passed as arg)
# - Writes to: stdout
# - Calls into: cryptography
"""
Print subject, issuer, dates, serial, and fingerprints for the root CA PEM.
Use for enrollment fingerprint / --pki-ca-fingerprint (IOS-XE static root CA).
Run from repo root: python tools/show_root_ca_info.py [path/to/rootCA.pem]
Defaults: proven_certs/rootCA.pem if present, else out/rootCA.pem.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
except ImportError:
    print("pip install cryptography", file=sys.stderr)
    sys.exit(1)


def fingerprint_hex_blocks(h: bytes, block_size: 4) -> str:
    hex_str = h.hex().upper()
    return " ".join(hex_str[i : i + block_size * 2] for i in range(0, len(hex_str), block_size * 2))


def fingerprint_colon(h: bytes) -> str:
    """Colon-separated hex (e.g. c8:c6:e4:94:...) for copy-paste / OpenSSL style."""
    return ":".join(h.hex().lower()[i : i + 2] for i in range(0, len(h.hex()), 2))


def main() -> None:
    # Default: proven_certs/rootCA.pem if present, else out/rootCA.pem
    if len(sys.argv) > 1:
        pem_path = Path(sys.argv[1])
    else:
        pem_path = Path("proven_certs/rootCA.pem") if Path("proven_certs/rootCA.pem").exists() else Path("out/rootCA.pem")
    if not pem_path.exists():
        print(f"Not found: {pem_path}", file=sys.stderr)
        sys.exit(1)
    pem = pem_path.read_bytes()
    cert = x509.load_pem_x509_certificate(pem, default_backend())
    print("Subject:", cert.subject.rfc4514_string())
    print("Issuer:", cert.issuer.rfc4514_string())
    print("Not valid before:", cert.not_valid_before_utc)
    print("Not valid after:", cert.not_valid_after_utc)
    print("Serial:", hex(cert.serial_number))
    sha256 = cert.fingerprint(hashes.SHA256())
    sha1 = cert.fingerprint(hashes.SHA1())
    md5 = cert.fingerprint(hashes.MD5())
    print("SHA256:", fingerprint_hex_blocks(sha256, 4))
    print("SHA256 (colon):", fingerprint_colon(sha256))
    print("SHA1:  ", fingerprint_hex_blocks(sha1, 4))
    print("SHA1 (colon): ", fingerprint_colon(sha1))
    print("MD5:   ", fingerprint_hex_blocks(md5, 4))


if __name__ == "__main__":
    main()
