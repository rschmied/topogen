# Run Terraform from this nac/ directory so yaml_files = ["nac.yaml"] resolves
# to nac.yaml beside main.tf. From the lab root, use:
# terraform -chdir=<lab>/nac <command>
#
# NOTE: the module is pointed at the single nac.yaml via yaml_files. Do NOT use
# yaml_directories = ["."] here: it recurses this directory (and .terraform/)
# and ingests the Ansible/informational YAML, which breaks the module's
# yaml_merge (top-level sequences are not valid NaC model fragments).

module "iosxe" {
  source     = "netascode/nac-iosxe/iosxe"
  version    = "0.1.0"
  yaml_files = ["nac.yaml"]
}

provider "iosxe" {
  # The CiscoDevNet/iosxe provider reads IOSXE_URL, IOSXE_USERNAME, and
  # IOSXE_PASSWORD (or its documented IOSXE_* environment variables).
  # Do not put lab URLs, usernames, or passwords in Terraform files.
  #
  # LAB ONLY: insecure disables TLS certificate verification; acceptable only
  # for throwaway lab gear with self-signed certificates. Never use this for
  # production NaC.
  insecure = true
}
