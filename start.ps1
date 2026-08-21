param(
    [string]$ListenHost,
    [int]$Port,
    [string]$Python,
    [string]$EnvFile,
    [switch]$SkipComfyCheck,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$defaultEnvFile = Join-Path $projectRoot ".env"

function Write-Info([string]$Message) {
    Write-Host "[comfyui2api] $Message"
}

function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-Uv() {
    $cmd = Get-Command "uv" -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw "uv was not found. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    }
    return $cmd.Source
}

function Set-EnvDefault([string]$Name, [string]$Value) {
    $current = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($current)) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
}

function Import-EnvFile([string]$Path) {
    if (-not (Test-Path $Path)) {
        return
    }

    # PowerShell 5.1's Get-Content defaults to the active ANSI codepage, which
    # mangles UTF-8 files (Chinese comments are read as garbage and adjacent
    # key=value lines get visually merged). Read the file as raw UTF-8 bytes
    # so we get exactly the same byte stream that python-dotenv would parse.
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    # Tolerate a UTF-8 BOM if the user (or a tool) added one.
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $bytes = $bytes[3..($bytes.Length - 1)]
    }
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    # .env files use LF line endings; tolerate CRLF as well.
    $text = $text -replace "`r`n", "`n"
    $lines = $text -split "`n"

    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        # Drop an optional leading '#' / '##' / '###' comment marker so we can
        # parse a key=value that happens to be documented inline (e.g. a comment
        # that says "### ... ADMIN_TOKEN=<value>" on the same line).
        $stripped = $trimmed -replace '^#+', ''
        $candidate = $stripped.TrimStart()
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if ($candidate -notmatch "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$") {
            continue
        }

        $name = $Matches[1]
        $value = $Matches[2]

        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        # Only forward non-empty values to python-dotenv. python-dotenv is
        # called later with override=False, so an empty PowerShell value would
        # otherwise shadow the real .env value (env var is "set", even to "").
        if ($value.Length -gt 0) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Ensure-UvEnvironment([string]$UvExe) {
    $args = @("sync", "--locked")
    if ($Python) {
        if (-not (Test-Path $Python)) {
            throw "Python executable not found: $Python"
        }
        $args += @("--python", (Resolve-Path $Python).Path)
    }
    Write-Info "Syncing project environment with uv ..."
    & $UvExe @args
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to sync project environment with uv."
    }
    if (-not (Test-Path $venvPython)) {
        throw "uv did not create the expected project environment at $venvPython"
    }
}

function Test-ComfyReachable([string]$BaseUrl) {
    $healthUrl = $BaseUrl.TrimEnd("/") + "/system_stats"
    try {
        $null = Invoke-WebRequest -Uri $healthUrl -Method Get -TimeoutSec 5
        Write-Info "ComfyUI reachable at $BaseUrl"
    } catch {
        Write-Warning "ComfyUI is not reachable at $BaseUrl. The API will still start, but requests may fail until ComfyUI is available."
    }
}

function Get-TcpExcludedPortRanges() {
    $lines = netsh interface ipv4 show excludedportrange protocol=tcp 2>$null
    $ranges = @()
    foreach ($line in $lines) {
        if ($line -match "^\s*(\d+)\s+(\d+)\s*") {
            $ranges += [pscustomobject]@{
                Start = [int]$Matches[1]
                End = [int]$Matches[2]
            }
        }
    }
    return $ranges
}

function Find-TcpExcludedPortRange([int]$Port) {
    foreach ($range in Get-TcpExcludedPortRanges) {
        if ($Port -ge $range.Start -and $Port -le $range.End) {
            return $range
        }
    }
    return $null
}

function Resolve-ListenIPAddress([string]$ListenHostValue) {
    $raw = ($ListenHostValue | ForEach-Object { $_.Trim() })
    if ([string]::IsNullOrWhiteSpace($raw) -or $raw -eq "0.0.0.0") {
        return [System.Net.IPAddress]::Any
    }
    if ($raw -eq "::" -or $raw -eq "[::]") {
        return [System.Net.IPAddress]::IPv6Any
    }
    $ip = $null
    if ([System.Net.IPAddress]::TryParse($raw, [ref]$ip)) {
        return $ip
    }
    try {
        $resolved = [System.Net.Dns]::GetHostAddresses($raw) | Select-Object -First 1
        if ($resolved) {
            return $resolved
        }
    } catch {
    }
    return [System.Net.IPAddress]::Any
}

function Test-TcpBindable([string]$ListenHostValue, [int]$Port) {
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new((Resolve-ListenIPAddress $ListenHostValue), $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            try {
                $listener.Stop()
            } catch {
            }
        }
    }
}

function Resolve-ListenPort([string]$ListenHostValue, [int]$RequestedPort) {
    $port = [Math]::Max(1, [Math]::Min(65535, $RequestedPort))
    $excluded = Find-TcpExcludedPortRange -Port $port
    $bindable = Test-TcpBindable -ListenHostValue $ListenHostValue -Port $port
    if (-not $excluded -and $bindable) {
        return $port
    }

    if ($excluded) {
        Write-Warning "Port $port is in a Windows excluded TCP range ($($excluded.Start)-$($excluded.End))."
    } else {
        Write-Warning "Port $port is not bindable on $ListenHostValue. It may already be in use or blocked."
    }

    for ($candidate = $port + 1; $candidate -le 65535; $candidate++) {
        if ((Find-TcpExcludedPortRange -Port $candidate) -or -not (Test-TcpBindable -ListenHostValue $ListenHostValue -Port $candidate)) {
            continue
        }
        Write-Warning "Falling back to available port $candidate."
        return $candidate
    }

    throw "No available TCP port was found starting from $port."
}

Set-Location $projectRoot

$uvExe = Resolve-Uv

if (-not $EnvFile -and (Test-Path $defaultEnvFile)) {
    $EnvFile = $defaultEnvFile
}
if ($EnvFile) {
    if (-not (Test-Path $EnvFile)) {
        throw "ENV file not found: $EnvFile"
    }
    $resolvedEnvFile = (Resolve-Path $EnvFile).Path
    [Environment]::SetEnvironmentVariable("ENV_FILE", $resolvedEnvFile, "Process")
    Import-EnvFile -Path $resolvedEnvFile
}

if ($PSBoundParameters.ContainsKey("ListenHost")) {
    [Environment]::SetEnvironmentVariable("API_LISTEN", $ListenHost, "Process")
}
if ($PSBoundParameters.ContainsKey("Port")) {
    [Environment]::SetEnvironmentVariable("API_PORT", "$Port", "Process")
}

Set-EnvDefault "COMFYUI_BASE_URL" "http://127.0.0.1:8188"
Set-EnvDefault "IMAGE_UPLOAD_MODE" "comfy"
Set-EnvDefault "API_LISTEN" "0.0.0.0"
Set-EnvDefault "API_PORT" "8000"

$resolvedComfyBase = [Environment]::GetEnvironmentVariable("COMFYUI_BASE_URL", "Process")
$resolvedUploadMode = [Environment]::GetEnvironmentVariable("IMAGE_UPLOAD_MODE", "Process")
$resolvedHost = [Environment]::GetEnvironmentVariable("API_LISTEN", "Process")
$resolvedPort = [int][Environment]::GetEnvironmentVariable("API_PORT", "Process")
$selectedPort = Resolve-ListenPort -ListenHostValue $resolvedHost -RequestedPort $resolvedPort
if ($selectedPort -ne $resolvedPort) {
    [Environment]::SetEnvironmentVariable("API_PORT", "$selectedPort", "Process")
}
$resolvedPort = [Environment]::GetEnvironmentVariable("API_PORT", "Process")

Ensure-UvEnvironment -UvExe $uvExe
$pythonExe = (Resolve-Path $venvPython).Path

Write-Info "Project root: $projectRoot"
Write-Info "uv: $uvExe"
Write-Info "Python: $pythonExe"
Write-Info "ENV_FILE: $([Environment]::GetEnvironmentVariable('ENV_FILE', 'Process'))"
Write-Info "COMFYUI_BASE_URL: $resolvedComfyBase"
Write-Info "IMAGE_UPLOAD_MODE: $resolvedUploadMode"
Write-Info "Listening on: http://$resolvedHost`:$resolvedPort"

if (-not $SkipComfyCheck) {
    Test-ComfyReachable -BaseUrl $resolvedComfyBase
}

if ($CheckOnly) {
    Write-Info "Check only mode finished."
    exit 0
}

Write-Info "Starting comfyui2api ..."
& $uvExe run --locked --no-sync -m comfyui2api
exit $LASTEXITCODE
