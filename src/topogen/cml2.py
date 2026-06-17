# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-06-04
#
# - Called by: src/topogen/render.py (offline --terraform-cml2 flow)
# - Reads from: generated offline CML YAML artifact name
# - Writes to: CML2 Terraform lifecycle scaffold under offline lab output root
# - Calls into: pathlib.Path
#
# Purpose: Build and write optional CiscoDevNet/cml2 Terraform lifecycle output.
# Blast Radius: Low - affects only offline generation when --terraform-cml2 is enabled.

from pathlib import Path

from topogen.models import TopogenError


CML2_MAIN_TF = """# Run Terraform from this cml2/ directory so the default topology_file
# resolves to the generated CML YAML beside this directory:
# terraform -chdir=<lab>/cml2 <command>

provider "cml2" {
  address     = var.address
  username    = var.username
  password    = var.password
  token       = var.token
  skip_verify = var.skip_verify
}

resource "cml2_lifecycle" "lab" {
  topology = file(var.topology_file)
  state    = var.lab_state
  wait     = var.wait
}
"""


CML2_VERSIONS_TF = """terraform {
  required_version = ">= 1.8.0"

  required_providers {
    cml2 = {
      source  = "CiscoDevNet/cml2"
      version = "~> 0.8"
    }
  }
}
"""


CML2_OUTPUTS_TF = """output "lab_id" {
  description = "CML lab UUID created from the generated topology."
  value       = cml2_lifecycle.lab.lab_id
}

output "lifecycle_id" {
  description = "Terraform lifecycle resource UUID."
  value       = cml2_lifecycle.lab.id
}

output "lab_state" {
  description = "Current CML lab runtime state."
  value       = cml2_lifecycle.lab.state
}

output "booted" {
  description = "Whether all lab nodes reached BOOTED when wait is enabled."
  value       = cml2_lifecycle.lab.booted
}

output "nodes" {
  description = "CML node/interface details, including discovered IP addresses where available."
  value       = cml2_lifecycle.lab.nodes
}

output "node_count" {
  description = "Number of nodes reported by the lifecycle resource."
  value       = length(cml2_lifecycle.lab.nodes)
}
"""


CML2_GITIGNORE = """.terraform/
*.tfstate*
terraform.tfvars
"""


def cml2_variables_tf(topology_file: str) -> str:
    """Return variables.tf with a relative default path to the generated YAML."""
    return f'''variable "address" {{
  description = "CML controller URL, for example https://cml.example.com."
  type        = string
}}

variable "username" {{
  description = "CML username. Leave null when using token authentication."
  type        = string
  default     = null
  sensitive   = true
}}

variable "password" {{
  description = "CML password. Leave null when using token authentication."
  type        = string
  default     = null
  sensitive   = true
}}

variable "token" {{
  description = "CML API token. Leave null when using username/password authentication."
  type        = string
  default     = null
  sensitive   = true
}}

variable "skip_verify" {{
  description = "Skip TLS certificate verification for disposable lab controllers with self-signed certificates."
  type        = bool
  default     = false
}}

variable "topology_file" {{
  description = "Path to the generated CML YAML artifact, relative to the cml2/ directory by default."
  type        = string
  default     = "../{topology_file}"
}}

variable "lab_state" {{
  description = "Desired CML lab state after apply."
  type        = string
  default     = "STARTED"

  validation {{
    condition     = contains(["DEFINED_ON_CORE", "STARTED", "STOPPED"], var.lab_state)
    error_message = "lab_state must be one of DEFINED_ON_CORE, STARTED, or STOPPED."
  }}
}}

variable "wait" {{
  description = "Wait for the lab to fully boot before Terraform returns."
  type        = bool
  default     = false
}}
'''


def _write_static_text(output_path: Path, content: str, overwrite: bool = False) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    output_path.write_text(content, encoding="utf-8")
    return output_path


def write_cml2_lifecycle_scaffold(
    cml2_root: Path,
    *,
    topology_file: str,
    overwrite: bool = False,
) -> list[Path]:
    """Write the CiscoDevNet/cml2 Terraform lifecycle scaffold under cml2_root."""
    return [
        _write_static_text(cml2_root / "main.tf", CML2_MAIN_TF, overwrite=overwrite),
        _write_static_text(cml2_root / "versions.tf", CML2_VERSIONS_TF, overwrite=overwrite),
        _write_static_text(
            cml2_root / "variables.tf",
            cml2_variables_tf(topology_file),
            overwrite=overwrite,
        ),
        _write_static_text(cml2_root / "outputs.tf", CML2_OUTPUTS_TF, overwrite=overwrite),
        _write_static_text(cml2_root / ".gitignore", CML2_GITIGNORE, overwrite=overwrite),
    ]
