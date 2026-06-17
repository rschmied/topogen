# TG-162 closeout pipeline — offline gates + optional live CML/NaC apply
# Exit 0 = pass; non-zero = fail (CI-friendly)
# Usage:
#   .\scripts\validate-tg162-dmvpn-live.ps1
#   .\scripts\validate-tg162-dmvpn-live.ps1 -LiveApply
#   .\scripts\validate-tg162-dmvpn-live.ps1 -Regenerate -LiveApply

param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$LabRoot = "",
    [string]$LabTitle = "TG162-LIVE-DMVPN-CSR-N3",
    [ValidateSet("iosv", "csr1000v")]
    [string]$DeviceTemplate = "csr1000v",
    [switch]$SkipPytest,
    [switch]$SkipTerraformPlan,
    [switch]$Regenerate,
    [switch]$LiveApply,
    [switch]$SkipNacDestroy
)

$ErrorActionPreference = "Stop"
$failed = 0

function Write-Gate {
    param([string]$Name, [bool]$Pass, [string]$Detail = "")
    $icon = if ($Pass) { "PASS" } else { "FAIL"; $script:failed++ }
    Write-Host "[$icon] $Name" -ForegroundColor $(if ($Pass) { "Green" } else { "Red" })
    if ($Detail) { Write-Host "       $Detail" }
}

function Test-CmlEnv {
    if (-not $env:TF_VAR_address) { return $false, "TF_VAR_address not set" }
    if (-not $env:TF_VAR_username -and -not $env:TF_VAR_token) {
        return $false, "Set TF_VAR_username/TF_VAR_password or TF_VAR_token"
    }
    return $true, ""
}

Set-Location $RepoRoot

if (-not $LabRoot) {
    $LabRoot = Join-Path (Join-Path $RepoRoot "out") $LabTitle
}

$yamlPath = Join-Path $LabRoot "$LabTitle.yaml"
$cml2Dir = Join-Path $LabRoot "cml2"
$nacDir = Join-Path $LabRoot "nac"
$liveEvidence = Join-Path $LabRoot "live"

# --- Regenerate lab bundle ---
if ($Regenerate) {
    Write-Host "`n=== Regenerate lab bundle ===" -ForegroundColor Cyan
    $genArgs = @(
        "-m", "topogen", "3",
        "--mode", "dmvpn",
        "--dmvpn-hubs", "1",
        "-T", $(if ($DeviceTemplate -eq "csr1000v") { "csr-dmvpn" } else { "iosv-dmvpn" }),
        "--device-template", $DeviceTemplate,
        "-L", $LabTitle,
        "--offline-yaml", $yamlPath,
        "--nac", "--terraform-cml2",
        "--mgmt", "--mgmt-bridge",
        "--overwrite"
    )
    & python @genArgs
    Write-Gate "generate $LabTitle" ($LASTEXITCODE -eq 0)
}

# --- Stage 1: unit tests ---
if (-not $SkipPytest) {
    Write-Host "`n=== Stage 1: DMVPN NaC unit tests ===" -ForegroundColor Cyan
    $pytestOut = python -m pytest tests/test_nac_writer.py -k dmvpn -q 2>&1 | Out-String
    $pytestPass = ($LASTEXITCODE -eq 0) -and ($pytestOut -match "passed")
    Write-Gate "pytest tests/test_nac_writer.py -k dmvpn" $pytestPass $pytestOut.Trim()
} else {
    Write-Host "`n=== Stage 1: skipped (-SkipPytest) ===" -ForegroundColor Yellow
}

# --- Stage 2: terraform plan matrix ---
if (-not $SkipTerraformPlan) {
    Write-Host "`n=== Stage 2: Terraform plan matrix ===" -ForegroundColor Cyan
    $env:TOPOGEN_TERRAFORM_PLAN = "1"
    $planOut = python -m pytest tests/test_nac_terraform_plan.py -m terraform -q 2>&1 | Out-String
    $planPass = ($LASTEXITCODE -eq 0) -and ($planOut -match "passed")
    Remove-Item Env:TOPOGEN_TERRAFORM_PLAN -ErrorAction SilentlyContinue
    Write-Gate "pytest tests/test_nac_terraform_plan.py -m terraform" $planPass $planOut.Trim()
} else {
    Write-Host "`n=== Stage 2: skipped (-SkipTerraformPlan) ===" -ForegroundColor Yellow
}

# --- Stage 3: live CML + NaC apply (optional) ---
if ($LiveApply) {
    Write-Host "`n=== Stage 3: Live CML + NaC apply ===" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $liveEvidence | Out-Null

    $cmlOk, $cmlDetail = Test-CmlEnv
    Write-Gate "CML TF_VAR_* environment" $cmlOk $cmlDetail

    if (-not $cmlOk) {
        Write-Host "Set TF_VAR_address, TF_VAR_username, TF_VAR_password (and TF_VAR_skip_verify for lab TLS)." -ForegroundColor Yellow
    } elseif (-not (Test-Path $cml2Dir)) {
        Write-Gate "cml2 scaffold exists" $false $cml2Dir
    } else {
        Push-Location $cml2Dir
        try {
            terraform init -input=false 2>&1 | Tee-Object -FilePath (Join-Path $liveEvidence "cml2-init.log") | Out-Null
            Write-Gate "terraform init (cml2)" ($LASTEXITCODE -eq 0)

            terraform apply -auto-approve -var="wait=true" -input=false 2>&1 |
                Tee-Object -FilePath (Join-Path $liveEvidence "cml2-apply.log") | Out-Null
            Write-Gate "terraform apply (cml2)" ($LASTEXITCODE -eq 0)

            $labId = (terraform output -raw lab_id 2>$null).Trim()
            Write-Gate "lab_id output" ([bool]$labId) $labId
        } finally {
            Pop-Location
        }

        if ($labId -and (Test-Path $nacDir)) {
            $prevEap = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $emittedSync = Join-Path $nacDir "sync-nac-mgmt.py"
            if (Test-Path $emittedSync) {
                $syncScript = $emittedSync
                $syncArgs = @(
                    $syncScript,
                    "--lab-id", $labId,
                    "--nac-root", $nacDir,
                    "--mode", "dhcp",
                    "--device-template", $DeviceTemplate,
                    "--fix-dhcp"
                )
                $syncGateName = "nac/sync-nac-mgmt.py (dhcp)"
            } else {
                $syncScript = Join-Path $RepoRoot "scripts/sync-nac-mgmt-dhcp.py"
                $syncArgs = @(
                    $syncScript,
                    "--lab-id", $labId,
                    "--nac-root", $nacDir,
                    "--device-template", $DeviceTemplate,
                    "--fix-dhcp"
                )
                $syncGateName = "sync-nac-mgmt-dhcp.py (legacy fallback)"
            }
            $syncOut = python @syncArgs 2>&1 | Out-String
            $syncExit = $LASTEXITCODE
            $ErrorActionPreference = $prevEap
            $syncPass = ($syncExit -eq 0) -and ($syncOut -match '"synced"\s*:\s*[1-9]')
            $syncOut | Out-File -FilePath (Join-Path $liveEvidence "mgmt-dhcp-sync.log") -Encoding utf8
            Write-Gate $syncGateName $syncPass $syncOut.Trim()

            if (-not $env:IOSXE_USERNAME -or -not $env:IOSXE_PASSWORD) {
                Write-Gate "IOSXE_USERNAME / IOSXE_PASSWORD" $false "Required for NaC apply"
            } else {
                Push-Location $nacDir
                try {
                    terraform init -input=false 2>&1 |
                        Tee-Object -FilePath (Join-Path $liveEvidence "nac-init.log") | Out-Null
                    Write-Gate "terraform init (nac)" ($LASTEXITCODE -eq 0)

                    terraform plan -input=false 2>&1 |
                        Tee-Object -FilePath (Join-Path $liveEvidence "nac-plan.log") | Out-Null
                    Write-Gate "terraform plan (nac)" ($LASTEXITCODE -eq 0)

                    terraform apply -auto-approve -input=false 2>&1 |
                        Tee-Object -FilePath (Join-Path $liveEvidence "nac-apply.log") | Out-Null
                    Write-Gate "terraform apply (nac)" ($LASTEXITCODE -eq 0)
                } finally {
                    Pop-Location
                }
            }
        }
    }

    Write-Host "`nManual CLI checks (R1): show run interface Tunnel0 | include tunnel source" -ForegroundColor Yellow
    Write-Host "Evidence directory: $liveEvidence" -ForegroundColor Yellow
} else {
    Write-Host "`n=== Stage 3: skipped (pass -LiveApply to run CML + NaC terraform) ===" -ForegroundColor Yellow
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if ($failed -eq 0) {
    if ($LiveApply) {
        Write-Host "Offline + live apply gates PASSED (verify CLI checks on devices)." -ForegroundColor Green
    } else {
        Write-Host "Offline gates PASSED. Stage 3 (live CML) still required before Jira Done." -ForegroundColor Green
        Write-Host "Lab bundle: $LabRoot"
        Write-Host "Run: .\scripts\validate-tg162-dmvpn-live.ps1 -LiveApply"
    }
    exit 0
} else {
    Write-Host "$failed gate(s) FAILED." -ForegroundColor Red
    exit 1
}
