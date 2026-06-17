# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-13
#
# TG-190 CSR1000v matrix: generate + cml2 init/plan/apply + live OOB validation.
# All scenarios: --mgmt --mgmt-vrf Mgmt-vrf --mgmt-bridge
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$NodeCount = 2,
    [ValidateSet("flat", "bootstrap", "both")]
    [string]$Modes = "both",
    [switch]$PlanOnly,
    [switch]$DestroyPriorCsrLabs
)

$ErrorActionPreference = "Stop"
$matrixRoot = Join-Path $RepoRoot "out\TG-190-csr-matrix"
$evidenceRoot = Join-Path $matrixRoot "evidence"
New-Item -ItemType Directory -Force -Path $matrixRoot, $evidenceRoot | Out-Null
$logPath = Join-Path $matrixRoot "matrix-run.log"

function Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $Msg"
    Write-Host $line
    Add-Content -Path $logPath -Value $line
}

$scenarios = @(
    @{ Id = "CSR-01"; Title = "TG-190-csr-01-dhcpv6"; Note = "IPv6-only DHCPv6"; Extra = @("--mgmt-ipv6-dhcp") },
    @{ Id = "CSR-02"; Title = "TG-190-csr-02-slaac"; Note = "IPv6-only SLAAC"; Extra = @("--mgmt-ipv6-slaac") },
    @{ Id = "CSR-03"; Title = "TG-190-csr-03-dual"; Note = "Dual-stack DHCP"; Extra = @("--mgmt-ipv4-dhcp", "--mgmt-ipv6-dhcp") },
    @{ Id = "CSR-04"; Title = "TG-190-csr-04-ipv4"; Note = "IPv4-only (bridge compat)"; Extra = @() },
    @{ Id = "CSR-06"; Title = "TG-190-csr-06-legacy-dhcpv6"; Note = "Legacy dhcpv6 mode"; Extra = @("--mgmt-ipv6-mode", "dhcpv6") },
    @{ Id = "CSR-07"; Title = "TG-190-csr-07-legacy-slaac"; Note = "Legacy slaac mode"; Extra = @("--mgmt-ipv6-mode", "slaac") }
)

$modeList = if ($Modes -eq "both") { @("flat", "bootstrap") } else { @($Modes) }
$allResults = @()

Set-Location $RepoRoot

if ($DestroyPriorCsrLabs) {
    Log "Destroying prior TG-190-csr-* labs (terraform state)..."
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Get-ChildItem (Join-Path $RepoRoot "out") -Directory -Filter "TG-190-csr-*" | ForEach-Object {
        $cml2 = Join-Path $_.FullName "cml2"
        if (Test-Path (Join-Path $cml2 "terraform.tfstate")) {
            Push-Location $cml2
            try {
                terraform destroy -auto-approve -input=false 2>&1 | Out-Null
                Log "destroyed $($_.Name)"
            } finally { Pop-Location }
        }
    }
    $ErrorActionPreference = $prev
}

foreach ($deployMode in $modeList) {
    Log "========== DEPLOY MODE: $deployMode =========="
    foreach ($s in $scenarios) {
        $title = $s.Title
        if ($deployMode -eq "bootstrap") { $title = "$title-boot" }

        $labRoot = Join-Path $RepoRoot "out\$title"
        $yamlPath = Join-Path $labRoot "$title.yaml"
        $cml2Dir = Join-Path $labRoot "cml2"
        $entry = [ordered]@{
            scenario = $s.Id
            mode     = $deployMode
            title    = $title
            note     = $s.Note
            generate = $null
            init     = $null
            plan     = $null
            apply    = $null
            validate = $null
            lab_id   = $null
        }

        Log "--- $($s.Id) $title ($deployMode) ---"

        $genArgs = @(
            "-m", "topogen",
            "--cml-version", "0.3.1",
            "$NodeCount",
            "--mode", "flat",
            "-T", "csr-ospf",
            "--device-template", "csr1000v",
            "-L", $title,
            "--offline-yaml", $yamlPath,
            "--nac", "--terraform-cml2",
            "--mgmt", "--mgmt-vrf", "Mgmt-vrf",
            "--mgmt-bridge",
            "--overwrite"
        ) + $s.Extra
        if ($deployMode -eq "bootstrap") { $genArgs += "--bootstrap" }

        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $genOut = & python @genArgs 2>&1 | Out-String
        $entry.generate = ($LASTEXITCODE -eq 0)
        if (-not $entry.generate) {
            Log "FAIL generate"
            $allResults += [pscustomobject]$entry
            $ErrorActionPreference = $prev
            continue
        }
        Log "PASS generate"

        Push-Location $cml2Dir
        try {
            terraform init -input=false 2>&1 | Out-File (Join-Path $labRoot "cml2-init.log") -Encoding utf8
            $entry.init = ($LASTEXITCODE -eq 0)
            if (-not $entry.init) { Log "FAIL init"; $allResults += [pscustomobject]$entry; continue }

            terraform plan -input=false -var="wait=true" 2>&1 | Out-File (Join-Path $labRoot "cml2-plan.log") -Encoding utf8
            $entry.plan = ($LASTEXITCODE -eq 0)
            if (-not $entry.plan) { Log "FAIL plan"; $allResults += [pscustomobject]$entry; continue }

            if (-not $PlanOnly) {
                terraform apply -auto-approve -input=false -var="wait=true" 2>&1 |
                    Out-File (Join-Path $labRoot "cml2-apply.log") -Encoding utf8
                $entry.apply = ($LASTEXITCODE -eq 0)
                if ($entry.apply) {
                    $entry.lab_id = (terraform output -raw lab_id 2>$null).Trim()
                    Log "PASS apply lab_id=$($entry.lab_id)"

                    $evidence = Join-Path $evidenceRoot "$($s.Id)-$deployMode.json"
                    python (Join-Path $RepoRoot "scripts\validate_csr_oob_live.py") `
                        --lab-id $entry.lab_id `
                        --scenario $s.Id `
                        --max-attempts 6 `
                        --wait-seconds 30 `
                        --out $evidence 2>&1 | Out-File (Join-Path $labRoot "validate.log") -Encoding utf8
                    $entry.validate = ($LASTEXITCODE -eq 0)
                    Log $(if ($entry.validate) { "PASS validate (R1 OOB)" } else { "FAIL validate - see $evidence" })
                } else {
                    Log "FAIL apply"
                }
            } else {
                $entry.apply = "skipped"
                Log "SKIP apply (-PlanOnly)"
            }
        } finally {
            Pop-Location
            $ErrorActionPreference = $prev
        }
        $allResults += [pscustomobject]$entry
    }
}

$reportPath = Join-Path $matrixRoot "results.json"
$allResults | ConvertTo-Json -Depth 4 | Set-Content $reportPath -Encoding utf8
Log "Report: $reportPath"
$allResults | Format-Table scenario, mode, apply, validate, lab_id -AutoSize
if (($allResults | Where-Object { $_.validate -eq $false }).Count -gt 0) { exit 1 }
