#!/usr/bin/env python3
"""Import all 15 IPv6 test labs to CML controller."""

import argparse
import os
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)
logger = logging.getLogger(__name__)

# CML controller details
CML_SERVER = os.getenv("VIRL2_HOST", "192.168.1.183")
CML_USER = os.getenv("VIRL2_USER", "admin")
CML_PASS = os.getenv("VIRL2_PASS", "")
CML_URL = f"https://{CML_SERVER}"

# Labs to import: 15 combinations of (5 modes × 3 ipv6 modes)
LABS = [
    # Static mode
    "tf-simple-static-extmgmt",
    "tf-nx-static-extmgmt",
    "tf-flat-static-extmgmt",
    "tf-flat-pair-static-extmgmt",
    "tf-dmvpn-static-extmgmt",
    # SLAAC mode
    "tf-simple-slaac-extmgmt",
    "tf-nx-slaac-extmgmt",
    "tf-flat-slaac-extmgmt",
    "tf-flat-pair-slaac-extmgmt",
    "tf-dmvpn-slaac-extmgmt",
    # DHCPv6 mode
    "tf-simple-dhcpv6-extmgmt",
    "tf-nx-dhcpv6-extmgmt",
    "tf-flat-dhcpv6-extmgmt",
    "tf-flat-pair-dhcpv6-extmgmt",
    "tf-dmvpn-dhcpv6-extmgmt",
]


def import_labs(base_dir="/tmp", replace=False, start=False):
    """Import all IPv6 matrix labs to CML."""
    try:
        from virl2_client import ClientLibrary
    except ImportError:
        logger.error("virl2_client not installed. Install with: pip install virl2-client")
        sys.exit(1)

    # Connect to CML
    try:
        logger.info(f"Connecting to CML at {CML_URL}")
        client = ClientLibrary(
            url=CML_URL,
            username=CML_USER,
            password=CML_PASS,
            ssl_verify=False
        )
    except Exception as e:
        logger.error(f"Failed to connect to CML: {e}")
        sys.exit(1)

    success_count = 0
    fail_count = 0

    for lab_name in LABS:
        lab_dir = Path(base_dir) / lab_name
        yaml_file = lab_dir / f"{lab_name}.yaml"

        if not yaml_file.exists():
            logger.error(f"YAML not found: {yaml_file}")
            fail_count += 1
            continue

        try:
            logger.info(f"Importing {lab_name}...")
            
            # Read YAML
            with open(yaml_file, 'r') as f:
                yaml_content = f.read()

            # Check if lab exists
            existing_lab = None
            try:
                existing_lab = client.get_lab_by_title(lab_name)
            except:
                pass

            # Remove if replace flag set
            if existing_lab and replace:
                logger.info(f"  Removing existing lab {lab_name}")
                client.remove_lab(existing_lab.id)
                existing_lab = None

            # Import lab
            if existing_lab:
                logger.warning(f"  Lab {lab_name} already exists, skipping")
            else:
                lab = client.import_lab(yaml_content)
                logger.info(f"  ✓ Imported {lab_name} (ID: {lab.id})")
                
                # Start if requested
                if start:
                    try:
                        lab.start()
                        logger.info(f"  ✓ Started {lab_name}")
                    except Exception as e:
                        logger.warning(f"  Failed to start {lab_name}: {e}")
                
                success_count += 1

        except Exception as e:
            logger.error(f"Failed to import {lab_name}: {e}")
            fail_count += 1

    logger.info(f"\nImport complete: {success_count} success, {fail_count} failed")
    return fail_count == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import IPv6 test matrix labs to CML")
    parser.add_argument("--base-dir", default="/tmp", help="Base directory for lab YAMLs")
    parser.add_argument("--replace", action="store_true", help="Replace existing labs")
    parser.add_argument("--start", action="store_true", help="Start labs after import")
    parser.add_argument("--out-dir", help="Optional output directory for import log")
    
    args = parser.parse_args()
    
    success = import_labs(base_dir=args.base_dir, replace=args.replace, start=args.start)
    sys.exit(0 if success else 1)
