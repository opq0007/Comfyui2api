$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$FrontendBuild = Join-Path $PSScriptRoot "build-frontend.ps1"
$DistRoot = Join-Path $Root "dist\comfyui2api"

function Resolve-NativeCommand([string]$Name) {
    foreach ($candidate in @("$Name.cmd", $Name)) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
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
    throw "$Name was not found on PATH."
}

function Invoke-Native {
    $command = $args[0]
    $commandArgs = @($args | Select-Object -Skip 1)
    & $command @commandArgs
    if ($LASTEXITCODE) {
        throw "Command failed with exit code ${LASTEXITCODE}: $command $($commandArgs -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $FrontendBuild)) {
    throw "Missing frontend build script: $FrontendBuild"
}

Write-Host "Building frontend..."
& $FrontendBuild
if ($LASTEXITCODE) {
    throw "Frontend build failed with exit code $LASTEXITCODE"
}

Write-Host "Building Python executables..."
$uv = Resolve-NativeCommand "uv"
Push-Location $Root
try {
    Invoke-Native $uv sync --locked
    Invoke-Native $uv run --with pyinstaller pyinstaller packaging/comfyui2api.spec --clean --noconfirm
}
finally {
    Pop-Location
}

Write-Host "Preparing runtime folders..."
New-Item -ItemType Directory -Force -Path (Join-Path $DistRoot "comfyui-api-workflows") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DistRoot "runs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DistRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DistRoot "logs") | Out-Null

Write-Host "Done."
