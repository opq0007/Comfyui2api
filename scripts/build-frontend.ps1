# Compile the Vite dashboard and copy it into the Python package so a single
# comfyui2api process can serve both /ui and /v1.
#
# Production assets use base "/ui/" and call same-origin /v1 and /runs
# (see frontend/vite.config.ts and frontend/src/lib/api.ts). The Vite
# proxy is dev-only and is not needed after this copy.

[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Frontend = Join-Path $Root "frontend"
$FrontendDist = Join-Path $Frontend "dist"
$WebUiDist = Join-Path $Root "src\comfyui2api\webui_dist"

function Write-Step([string]$Message) {
    Write-Host "[build-frontend] $Message"
}

function Resolve-Pnpm {
    foreach ($name in @("pnpm.cmd", "pnpm")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -eq $cmd) {
            continue
        }
        $source = [string]$cmd.Source
        if ($source -like "*.ps1") {
            $sibling = [IO.Path]::ChangeExtension($source, ".cmd")
            if (Test-Path -LiteralPath $sibling) {
                return $sibling
            }
        }
        return $source
    }
    throw "pnpm was not found. Install Node.js and pnpm, or enable Corepack: corepack enable"
}

function Invoke-Native {
    $command = $args[0]
    $commandArgs = @($args | Select-Object -Skip 1)
    & $command @commandArgs
    # Prefer truthiness so a leftover $null LASTEXITCODE (common when a .ps1
    # shim wraps a native tool on Windows PowerShell 5.1) is treated as success.
    if ($LASTEXITCODE) {
        throw "Command failed with exit code ${LASTEXITCODE}: $command $($commandArgs -join ' ')"
    }
}

function Assert-FrontendLayout {
    if (-not (Test-Path -LiteralPath $Frontend)) {
        throw "Frontend directory not found: $Frontend"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Frontend "package.json"))) {
        throw "frontend/package.json is missing."
    }
}

function Sync-WebUiDist {
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDist "index.html"))) {
        throw "Frontend build did not produce dist/index.html"
    }

    $assetDir = Join-Path $FrontendDist "assets"
    $builtAssets = @()
    if (Test-Path -LiteralPath $assetDir) {
        $builtAssets = @(Get-ChildItem -LiteralPath $assetDir -File)
    }
    if ($builtAssets.Count -eq 0) {
        throw "Frontend build did not produce any files under dist/assets"
    }

    if (Test-Path -LiteralPath $WebUiDist) {
        $resolved = (Resolve-Path -LiteralPath $WebUiDist).Path
        $rootPrefix = $Root.TrimEnd("\", "/") + [IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected path: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }

    New-Item -ItemType Directory -Force -Path $WebUiDist | Out-Null
    Copy-Item -Path (Join-Path $FrontendDist "*") -Destination $WebUiDist -Recurse -Force

    $index = Join-Path $WebUiDist "index.html"
    $copiedAssets = Join-Path $WebUiDist "assets"
    if (-not (Test-Path -LiteralPath $index)) {
        throw "Copy failed: $index is missing"
    }
    $copiedFiles = @()
    if (Test-Path -LiteralPath $copiedAssets) {
        $copiedFiles = @(Get-ChildItem -LiteralPath $copiedAssets -File)
    }
    if ($copiedFiles.Count -eq 0) {
        throw "Copy failed: $copiedAssets is empty"
    }

    $html = [System.IO.File]::ReadAllText($index)
    $missing = @()
    foreach ($match in [regex]::Matches($html, "/ui/assets/([^""'\s>]+)")) {
        $name = $match.Groups[1].Value
        $path = Join-Path $copiedAssets $name
        if (-not (Test-Path -LiteralPath $path)) {
            $missing += $name
        }
    }
    if ($missing.Count -gt 0) {
        throw "Copied index.html references missing assets: $($missing -join ', ')"
    }

    Write-Step "Synced $($copiedFiles.Count) asset file(s) to $WebUiDist"
}

Assert-FrontendLayout
$pnpm = Resolve-Pnpm
Write-Step "Project root: $Root"
Write-Step "pnpm: $pnpm"

Push-Location $Frontend
try {
    if (-not $SkipInstall) {
        Write-Step "Installing frontend dependencies..."
        Invoke-Native $pnpm install
    }
    Write-Step "Building frontend (base=/ui/, same-origin /v1)..."
    Invoke-Native $pnpm build
}
finally {
    Pop-Location
}

Write-Step "Copying dist -> src\comfyui2api\webui_dist ..."
Sync-WebUiDist
Write-Step "Done. start.bat can now serve /ui from the Python process."
