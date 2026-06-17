# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-06-07
#
# Purpose: TG-167 offline validation — --intent-spot matrix with --nac --cml2 (PowerShell).
# Blast Radius: Validation script only (writes under out/intent-spot-matrix/).
#
# Validate --intent-spot matrix: all modes x iosv/csr x flag on/off with --nac --cml2
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ArtifactRoot = (Join-Path $RepoRoot "out\intent-spot-matrix")
)

$ErrorActionPreference = "Stop"
$failed = 0
$passed = 0

function Write-Gate {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    if ($Ok) {
        $script:passed++
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } else {
        $script:failed++
        Write-Host "[FAIL] $Name" -ForegroundColor Red
    }
    if ($Detail) { Write-Host "       $Detail" }
}

Set-Location $RepoRoot
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null

$modes = @("simple", "nx", "flat", "flat-pair", "dmvpn")
$devices = @("iosv", "csr1000v")
$intentFlags = @(
    @{ Name = "no-spot"; Args = @() },
    @{ Name = "intent-spot"; Args = @("--intent-spot") }
)

$rows = @()

foreach ($mode in $modes) {
    foreach ($device in $devices) {
        foreach ($flag in $intentFlags) {
            $lab = "$mode-4-$device-$($flag.Name)"
            $yamlArg = Join-Path $ArtifactRoot "$lab\$lab.yaml"

            $cmd = @(
                "-m", "topogen", "4",
                "-m", $mode,
                "--device-template", $device,
                "--nac", "--cml2",
                "--cml-version", "0.3.1",
                "--overwrite", "-q",
                "--offline-yaml", $yamlArg
            )
            if ($mode -eq "dmvpn") {
                $cmd += @("--dmvpn-hubs", "1")
            }
            $cmd += $flag.Args

            $prev = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & python @cmd 2>&1 | Out-Null
            $rc = $LASTEXITCODE
            $ErrorActionPreference = $prev

            $yamlPath = Join-Path $ArtifactRoot "$lab\$lab.yaml"
            $nacDir = Join-Path $ArtifactRoot "$lab\nac"
            $cml2Dir = Join-Path $ArtifactRoot "$lab\cml2"
            $ok = $true
            $detail = @()

            Write-Gate "$lab generate (rc=$rc)" ($rc -eq 0)

            if (-not (Test-Path $yamlPath)) {
                Write-Gate "$lab yaml exists" $false $yamlPath
                $rows += [pscustomobject]@{ Lab = $lab; Pass = $false; Note = "missing yaml" }
                continue
            }

            $text = Get-Content $yamlPath -Raw
            Write-Gate "$lab annotations" ($text -match "annotations:")
            Write-Gate "$lab notes" ($text -match "(?m)^\s*notes:")
            Write-Gate "$lab no -9999 coords" ($text -notmatch "x:\s*-9999")
            Write-Gate "$lab version 0.3.1" ($text -match "version:\s*'?0\.3\.1'?")

            $wantSpot = ($flag.Name -eq "intent-spot")
            $hasMarker = ($text -match "label:\s*INTENT-SPOT")
            if ($wantSpot) {
                Write-Gate "$lab INTENT-SPOT present" $hasMarker
            } else {
                Write-Gate "$lab INTENT-SPOT absent" (-not $hasMarker)
            }

            Write-Gate "$lab nac/" (Test-Path $nacDir)
            Write-Gate "$lab cml2/main.tf" (Test-Path (Join-Path $cml2Dir "main.tf"))

            if ($wantSpot -and ($text -match "--intent-spot")) {
                Write-Gate "$lab provenance --intent-spot" $true
            } elseif (-not $wantSpot -and ($text -notmatch "--intent-spot")) {
                Write-Gate "$lab provenance no flag" $true
            } else {
                Write-Gate "$lab provenance metadata" $false
            }

            $rows += [pscustomobject]@{
                Lab = $lab
                Pass = ($rc -eq 0)
                Nodes = 4
                Mode = $mode
                Device = $device
                IntentSpot = $wantSpot
            }
        }
    }
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
Write-Host "Passed gates: $passed"
Write-Host "Failed gates: $failed"
Write-Host "Artifacts: $ArtifactRoot"

if ($failed -gt 0) { exit 1 }
exit 0
