# Reproducible build: coefficients -> HLS IP -> Vivado implementation.
# Usage:  powershell -ExecutionPolicy Bypass -File fpga\build\build_all.ps1 [-Promote] [-SkipHls]
[CmdletBinding()]
param(
    [switch]$Promote,   # copy verified bit/HWH/reports into fpga/build
    [switch]$SkipHls    # reuse an existing exported IP
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$fw = Join-Path $repo 'fpga'
$hw = Join-Path $fw 'src'
$out = Join-Path $hw 'build\video_effects_output'
$reports = Join-Path $repo 'fpga\report'
$final = Join-Path $repo 'fpga\build'
$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }

function Require-Command([string]$name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name was not found on PATH. Add the Vivado/Vitis HLS 2024.1 bin directory, or set it before running this script."
    }
}

function Step([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

Push-Location $repo
try {
    Step '0/5 tool check'
    Require-Command $python
    if (-not $SkipHls) { Require-Command 'vitis_hls' }
    Require-Command 'vivado'
    Write-Host "repository: $repo"

    Step '1/5 FIR coefficient banks'
    & $python (Join-Path $hw 'scripts\generate_coeffs.py')
    if ($LASTEXITCODE -ne 0) { throw 'coefficient generation failed' }

    if (-not $SkipHls) {
        Step '2/5 Vitis HLS: C simulation, synthesis, co-simulation, IP export'
        & vitis_hls -f (Join-Path $hw 'scripts\build_hls.tcl')
        if ($LASTEXITCODE -ne 0) { throw 'HLS build failed' }
    } else {
        Step '2/5 Vitis HLS skipped (-SkipHls)'
    }

    Step '3/5 Vivado: synthesize, place, route, write bitstream'
    & vivado -mode batch -source (Join-Path $hw 'scripts\build_video_effects.tcl')
    if ($LASTEXITCODE -ne 0) { throw 'Vivado build failed' }

    Step '4/5 collect reports'
    New-Item -ItemType Directory -Force -Path $reports | Out-Null
    foreach ($name in @('timing.rpt', 'utilization.rpt', 'drc.rpt')) {
        $source = Join-Path $out $name
        if (-not (Test-Path $source)) { throw "missing build report: $source" }
        Copy-Item $source (Join-Path $reports $name) -Force
        Write-Host "collected $name"
    }
    foreach ($name in @('audio_fir_csynth.rpt', 'audio_fir_cosim.rpt')) {
        $source = Join-Path $hw "build\fir_accel\solution1\syn\report\$name"
        if ($name -eq 'audio_fir_cosim.rpt') { $source = Join-Path $hw "build\fir_accel\solution1\sim\report\$name" }
        if (Test-Path $source) {
            New-Item -ItemType Directory -Force -Path (Join-Path $reports 'hls') | Out-Null
            Copy-Item $source (Join-Path $reports 'hls' $name) -Force
            Write-Host "collected hls/$name"
        }
    }

    Step '5/5 verify and optionally promote'
    $timing = Get-Content (Join-Path $out 'timing.rpt') -Raw
    if ($timing -notmatch 'All user specified timing constraints are met') {
        throw 'timing constraints are not met; refusing to promote this build'
    }
    foreach ($name in @('audio_live.bit', 'audio_live.hwh', 'BUILD_OK')) {
        if (-not (Test-Path (Join-Path $out $name))) { throw "missing build artifact: $name" }
    }
    Write-Host 'timing constraints met, artifacts present'
    if ($Promote) {
        New-Item -ItemType Directory -Force -Path $final | Out-Null
        Copy-Item (Join-Path $out 'audio_live.bit') $final -Force
        Copy-Item (Join-Path $out 'audio_live.hwh') $final -Force
        Copy-Item (Join-Path $out 'BUILD_OK') $final -Force
        foreach ($name in @('timing.rpt', 'utilization.rpt', 'drc.rpt')) {
            Copy-Item (Join-Path $out $name) $final -Force
        }
        Write-Host "promoted build to $final"
        Write-Host 'remember to refresh metrics/logs and fpga/report/ppa_evolution.csv'
    } else {
        Write-Host 'build kept in fpga/src/build/video_effects_output (use -Promote to publish it)'
    }
    Write-Host "`nBUILD OK" -ForegroundColor Green
} finally {
    Pop-Location
}
