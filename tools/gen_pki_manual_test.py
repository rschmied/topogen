#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.2
# Date Modified: 2026-02-21
#
# - Called by: Users (CLI); docs/MANUAL-PKI-IMPORT-TEST.md
# - Reads from: Repo root, out/
# - Writes to: out/ (ca-*.pem, r1-*.pem)
# - Calls into: cryptography, optionally openssl
"""
Generate CA + one router cert for manual PKI import testing on IOS-XE.
Run once: pip install cryptography && python tools/gen_pki_manual_test.py
Writes PEMs to out/ and prints IOS-XE import steps.

Note: This script creates a new Root CA on every run (random serial, not_valid_before=now),
so the CA fingerprint changes each time. For a stable fingerprint (e.g. one CA across
hundreds of labs / thousands of routers), generate the Root CA once with the OpenSSL
scripts (tools/gen_pki_openssl.sh or .ps1) or the one-time OpenSSL commands in
docs/MANUAL-PKI-IMPORT-TEST.md, then keep rootCA.key/rootCA.pem and never regenerate.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
)
except ImportError:
    print("Install cryptography: pip install cryptography", file=sys.stderr)
    sys.exit(1)

_UTC_NOW = lambda: datetime.now(timezone.utc)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Passphrase for router private keys (IOS requires "password" on import). Use with: password <this>
ROUTER_KEY_PASSPHRASE = b"TopoGenPKI2025"

# 3DES (DES-EDE3-CBC) is widely supported by Cisco IOS for PEM key import; AES-256-CBC often is not.
_OPENSSL_3DES_CIPHER = "des3"


def _find_openssl() -> str | None:
    """Return path to openssl executable, or None. Prefer PATH; on Windows prefer native builds over Git's MSYS openssl."""
    exe = shutil.which("openssl")
    if exe:
        return exe
    if sys.platform == "win32":
        # Prefer native Windows OpenSSL (works from Python); Git's openssl can fail with "couldn't create signal pipe".
        for path in (
            Path(r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe"),
            Path(r"C:\Program Files (x86)\OpenSSL-Win32\bin\openssl.exe"),
            Path(r"C:\Program Files\Git\usr\bin\openssl.exe"),
            Path(r"C:\Program Files (x86)\Git\usr\bin\openssl.exe"),
        ):
            if path.exists():
                return str(path)
    return None


def _reencrypt_pem_key_3des(key_pem_unencrypted: bytes, passphrase: bytes) -> bytes | None:
    """Re-encrypt PEM private key with 3DES via OpenSSL so Cisco IOS can decode it. Returns None if openssl fails."""
    openssl = _find_openssl()
    if not openssl:
        return None
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False) as f:
        tmp_in = f.name
        f.write(key_pem_unencrypted)
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False) as f:
            tmp_out = f.name
        try:
            proc = subprocess.run(
                [
                    openssl, "rsa",
                    "-in", tmp_in,
                    "-out", tmp_out,
                    f"-{_OPENSSL_3DES_CIPHER}",
                    "-passout", f"pass:{passphrase.decode('utf-8')}",
                ],
                capture_output=True,
                timeout=10,
            )
            if proc.returncode != 0:
                if proc.stderr:
                    print(proc.stderr.decode("utf-8", errors="replace"), file=sys.stderr)
                return None
            return Path(tmp_out).read_bytes()
        finally:
            Path(tmp_out).unlink(missing_ok=True)
    except FileNotFoundError:
        return None
    finally:
        Path(tmp_in).unlink(missing_ok=True)


def _get_domain() -> str:
    """Use TopoGen Config.domainname (config.toml) so we use the same variable as TopoGen."""
    try:
        from topogen.config import Config
        cfg = Config.load(str(_REPO_ROOT / "config.toml"))
        return cfg.domainname
    except Exception:
        pass
    return "virl.lab"


def generate_ca() -> tuple[bytes, bytes]:
    """Self-signed Root CA, RSA 2048. Returns (ca_private_key_pem, ca_cert_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    domain = _get_domain()
    fqdn = f"CA-ROOT.{domain}"
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, fqdn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TopoGen"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_UTC_NOW())
        .not_valid_after(_UTC_NOW() + timedelta(days=7300))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256(), default_backend())
    )
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    cert_pem = cert.public_bytes(Encoding.PEM)
    return key_pem, cert_pem


def generate_router_cert(
    hostname: str,
    ip_address: str,
    ca_key_pem: bytes,
    ca_cert_pem: bytes,
    domain: str | None = None,
) -> tuple[bytes, bytes]:
    """Router RSA 2048 key + cert signed by CA. SAN = IP + FQDN. Returns (key_pem, cert_pem)."""
    if domain is None:
        domain = _get_domain()
    ca_key = serialization.load_pem_private_key(ca_key_pem, password=None, backend=default_backend())
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem, default_backend())
    fqdn = f"{hostname}.{domain}"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, fqdn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TopoGen"),
    ])
    san = x509.SubjectAlternativeName([
        x509.DNSName(fqdn),
        x509.DNSName(hostname),
        x509.IPAddress(__parse_ip(ip_address)),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_UTC_NOW())
        .not_valid_after(_UTC_NOW() + timedelta(days=7300))
        .add_extension(san, critical=False)
        .sign(ca_key, hashes.SHA256(), default_backend())
    )
    key_pem_unencrypted = key.private_bytes(
        Encoding.PEM,
        PrivateFormat.TraditionalOpenSSL,
        NoEncryption(),
    )
    # IOS often cannot decode AES-256-CBC PEM keys; re-encrypt with 3DES via OpenSSL.
    key_pem = _reencrypt_pem_key_3des(key_pem_unencrypted, ROUTER_KEY_PASSPHRASE)
    if key_pem is None:
        # Fallback if openssl is missing: use library default (may fail on IOS with "Unable to decode key").
        import warnings
        warnings.warn(
            "OpenSSL not found or failed: router key is AES-256-CBC; IOS may reject it. "
            "On Windows, install native OpenSSL (see docs/MANUAL-PKI-IMPORT-TEST.md); Git's OpenSSL often fails from Python.",
            UserWarning,
            stacklevel=2,
        )
        key_pem = key.private_bytes(
            Encoding.PEM,
            PrivateFormat.TraditionalOpenSSL,
            BestAvailableEncryption(ROUTER_KEY_PASSPHRASE),
        )
    cert_pem = cert.public_bytes(Encoding.PEM)
    return key_pem, cert_pem


def __parse_ip(ip_str: str):
    from ipaddress import ip_address as _ip
    return _ip(ip_str.strip().split("/")[0])


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    r2_only = "--r2-only" in sys.argv
    if r2_only:
        ca_key_path = out_dir / "ca-key.pem"
        ca_cert_path = out_dir / "ca-cert.pem"
        if not ca_key_path.exists() or not ca_cert_path.exists():
            print("Missing out/ca-key.pem or out/ca-cert.pem. Run without --r2-only first.", file=sys.stderr)
            sys.exit(1)
        ca_key_pem = ca_key_path.read_bytes()
        ca_cert_pem = ca_cert_path.read_bytes()
        r2_key_pem, r2_cert_pem = generate_router_cert("R2", "10.10.0.2", ca_key_pem, ca_cert_pem)
        (out_dir / "r2-key.pem").write_bytes(r2_key_pem)
        (out_dir / "r2-cert.pem").write_bytes(r2_cert_pem)
        print("Wrote out/r2-key.pem, out/r2-cert.pem (R2, 10.10.0.2, signed by existing CA)")
        print("Router key passphrase: TopoGenPKI2025  (use: crypto pki import Router-cert pem terminal password TopoGenPKI2025)")
        return

    # CA
    ca_key_pem, ca_cert_pem = generate_ca()
    (out_dir / "ca-key.pem").write_bytes(ca_key_pem)
    (out_dir / "ca-cert.pem").write_bytes(ca_cert_pem)
    print("Wrote out/ca-key.pem, out/ca-cert.pem")

    # One router (R1, 10.10.0.1)
    r1_key_pem, r1_cert_pem = generate_router_cert("R1", "10.10.0.1", ca_key_pem, ca_cert_pem)
    (out_dir / "r1-key.pem").write_bytes(r1_key_pem)
    (out_dir / "r1-cert.pem").write_bytes(r1_cert_pem)
    print("Wrote out/r1-key.pem, out/r1-cert.pem")
    print("Router key passphrase: TopoGenPKI2025  (use: password TopoGenPKI2025 on import)")

    # IOS-XE import steps
    print()
    print("--- Manual import on router (config mode) ---")
    print("1) Create trustpoint (no SCEP, no key gen):")
    print("   crypto pki trustpoint CA-ROOT-SELF")
    print("    revocation-check none")
    print("   exit")
    print()
    print("2) Import certificate:")
    print("   crypto pki import CA-ROOT-SELF certificate pem terminal")
    print("   (paste contents of out/r1-cert.pem, then type quit)")
    print()
    print("3) Import private key:")
    print("   crypto pki import CA-ROOT-SELF private-key pem terminal password TopoGenPKI2025")
    print("   (paste contents of out/r1-key.pem, then type quit)")
    print()
    print("4) Verify: show crypto pki certificates CA-ROOT-SELF")
    print()
    print("For CA chain (if router needs to trust the CA): import ca-cert.pem as a separate")
    print("trustpoint or as the certificate of the CA-ROOT-SELF trustpoint (depends on IOS-XE).")


if __name__ == "__main__":
    main()
