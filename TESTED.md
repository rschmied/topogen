# Tested Platforms

<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.1.2
Date Modified: 2026-02-21

- Called by: Developers via DEVELOPER.md link, CI/CD systems for platform validation
- Reads from: Manual observations from development/testing (AI-first documentation)
- Writes to: None (documentation only)
- Calls into: None (reference file)

Purpose: Documents validated Python versions, CML servers, node images, and dependencies
         for TopoGen. Enables CI/CD matrix testing and platform compatibility checks.

Blast Radius: None (documentation only, does not affect code execution)
-->

This file documents the platforms and versions that have been actively used and validated with TopoGen. This is primarily for CI/CD pipelines and automated testing.

## Python Environment

- **Python**: 3.12.0 (actively used)
- **Minimum**: 3.12+ (per pyproject.toml)
- **pip**: 24.3.1 (package manager)

## External Tools

- **Git**: 2.50.1.windows.1 (version control)
- **PowerShell**: 5.x (Windows scripting, validation commands)
- **Bash**: Git Bash on Windows (script execution)
- **VS Code**: (IDE - version not tracked, latest stable recommended)

## Dependencies (from pyproject.toml)

```
virl2-client >= 2.7.0
jinja2 >= 3
networkx >= 3
pyserde[toml] >= 0.22.2
enlighten >= 1
```

**Optional**:
```
gooey >= 1.0.8 (GUI)
numpy >= 2.2.0
scipy >= 1.14.1
```

**Dev**:
```
mypy >= 1.16.0
ruff >= 0.8.3
types-networkx >= 3.5.0.20250531
```

## CML Environment

### CML Servers
- **2.6.1** (personal) - Validated with offline YAML generation and online lab creation
- **2.7.0** (enterprise) - Validated with virl2-client 2.7.0

### Node Images
- **CSR1000v 17.3** - PKI server (crypto pki server), IKEv2, DMVPN, OSPF, EIGRP
  - Note: PKI server requires IOS-XE 17.x+
- **IOSv 15.9** - OSPF, EIGRP, DMVPN Phase 2
- **ASAv 9.x** - IKEv2 VPN endpoints (observed in user labs)

### smart_annotations (CML 2.8+)
TopoGen offline YAML includes `smart_annotations: []` in all generated files (added with the intent/annotation feature). This field was introduced in CML 2.8. Behavior on CML versions earlier than 2.8 is unknown — older parsers may silently ignore the field or reject the import. Not tested on any version earlier than 2.9. Tested on CML 2.10 (not yet publicly available at time of writing). If you are running CML 2.7 or earlier and import fails, the `smart_annotations: []` line is the likely cause.

## Operating System

- **Windows 11** - Primary development and testing environment
  - Path handling with spaces validated
  - PowerShell and Command Prompt tested

## Validated Features

### Core Functionality
- Offline YAML generation (flat, flat-pair, DMVPN modes)
- Online lab creation via CML API
- OOB management network (--mgmt, --mgmt-bridge)
- External connector (System Bridge mode)
- Lab auto-start (--start flag)

### PKI Features (Current Work)
- CA-ROOT node creation (CSR1000v)
- PKI server initialization (crypto pki server CA-ROOT)
- Database storage on flash (database url flash:)
- Named RSA key generation (CA-ROOT.server)
- NTP master configuration
- HTTP/HTTPS server for SCEP
- Routing protocol auto-selection (OSPF/EIGRP)

### Scale Testing
- 4-node labs with PKI (validated)
- 100+ node labs mentioned in logs (to be formally validated)

## Known Limitations

- PKI CA-ROOT requires CSR1000v (IOSv not yet tested for PKI server)
- External connector only supports System Bridge mode (NAT mode not implemented)
- Multi-CA hierarchy (3+ CAs) not yet implemented

## Update Policy

This file should be updated when:
1. New CML server versions are validated
2. New node image versions are tested
3. New Python versions are confirmed working
4. Major dependency version changes are validated
5. New features are tested and confirmed working

For CI/CD automation, parse this file or use the dependency declarations in `pyproject.toml` directly.
