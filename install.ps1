# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#Requires -Version 5.1

<#
.SYNOPSIS
    Interactive installer for fireflyframework-agentic.

.DESCRIPTION
    Installs fireflyframework-agentic from source with interactive TUI, requirement
    detection, and progress indicators.

.PARAMETER NonInteractive
    Run in non-interactive mode with default options.

.PARAMETER Extras
    Optional extras to install (rest, kafka, rabbitmq, redis, queues, all).

.EXAMPLE
    .\install.ps1
    .\install.ps1 -NonInteractive -Extras all
    irm https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.ps1 | iex
#>

[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [ValidateSet("", "rest", "kafka", "rabbitmq", "redis", "queues", "all")]
    [string]$Extras = ""
)

$ErrorActionPreference = "Stop"

# ── Constants ────────────────────────────────────────────────────────────────

$script:VERSION = "26.01.01"
$script:PACKAGE = "fireflyframework-agentic"
$script:REPO_URL = "https://github.com/fireflyframework/fireflyframework-agentic.git"
$script:MIN_PYTHON_MAJOR = 3
$script:MIN_PYTHON_MINOR = 13
$script:SPINNER_FRAMES = @("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

# ── State ────────────────────────────────────────────────────────────────────

$script:PythonCmd = ""
$script:HasUV = $false
$script:HasGit = $false
$script:SelectedExtras = $Extras
$script:IsInteractive = -not $NonInteractive

# Detect piped execution
if ($null -eq $Host.UI -or $null -eq $Host.UI.RawUI) {
    $script:IsInteractive = $false
}

# ── Utility functions ────────────────────────────────────────────────────────

function Show-Banner {
    Write-Host ""
    Write-Host "  _____.__                _____.__" -ForegroundColor Cyan
    Write-Host "_/ ____\__|______   _____/ ____\  | ___.__." -ForegroundColor Cyan
    Write-Host "\   __\|  \_  __ \_/ __ \   __\|  |<   |  |" -ForegroundColor Cyan
    Write-Host " |  |  |  ||  | \/\  ___/|  |  |  |_\___  |" -ForegroundColor Cyan
    Write-Host " |__|  |__||__|    \___  >__|  |____/ ____|" -ForegroundColor Cyan
    Write-Host "                       \/           \/" -ForegroundColor Cyan
    Write-Host "  _____                                                 __     /\" -ForegroundColor Cyan
    Write-Host "_/ ____\___________    _____   ______  _  _____________|  | __ \ \" -ForegroundColor Cyan
    Write-Host "\   __\_  __ \__  \  /     \_/ __ \ \/ \/ /  _ \_  __ \  |/ /  \ \" -ForegroundColor Cyan
    Write-Host " |  |   |  | \// __ \|  Y Y  \  ___/\     (  <_> )  | \/    <    \ \" -ForegroundColor Cyan
    Write-Host " |__|   |__|  (____  /__|_|  /\___  >\/\_/ \____/|__|  |__|_ \    \ \" -ForegroundColor Cyan
    Write-Host "                   \/      \/     \/                        \/     \/" -ForegroundColor Cyan
    Write-Host "  ________                  _____  .__" -ForegroundColor Cyan
    Write-Host " /  _____/  ____   ____    /  _  \ |__|" -ForegroundColor Cyan
    Write-Host "/   \  ____/ __ \ /    \  /  /_\  \|  |" -ForegroundColor Cyan
    Write-Host "\    \_\  \  ___/|   |  \/    |    \  |" -ForegroundColor Cyan
    Write-Host " \______  /\___  >___|  /\____|__  /__|" -ForegroundColor Cyan
    Write-Host "        \/     \/     \/         \/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  fireflyframework-agentic" -ForegroundColor White -NoNewline
    Write-Host " v$script:VERSION" -ForegroundColor DarkGray
    Write-Host "  The production-grade GenAI metaframework built on Pydantic AI" -ForegroundColor DarkGray
    Write-Host "  Copyright 2026 Firefly Software Solutions Inc. Apache License 2.0." -ForegroundColor DarkGray
    Write-Host ""
}

function Write-Info    { param([string]$Message) Write-Host "  i  $Message" -ForegroundColor Blue }
function Write-Ok      { param([string]$Message) Write-Host "  ✔  $Message" -ForegroundColor Green }
function Write-Warn    { param([string]$Message) Write-Host "  ⚠  $Message" -ForegroundColor Yellow }
function Write-Err     { param([string]$Message) Write-Host "  ✖  $Message" -ForegroundColor Red }
function Write-Section { param([string]$Title)   Write-Host "`n  ─── $Title ───`n" -ForegroundColor Magenta }

function Read-YesNo {
    param(
        [string]$Message,
        [bool]$Default = $true
    )
    if (-not $script:IsInteractive) { return $Default }
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    Write-Host "  ?  $Message $hint " -ForegroundColor Cyan -NoNewline
    $answer = Read-Host
    if ([string]::IsNullOrWhiteSpace($answer)) {
        return $Default
    }
    return $answer -match "^[Yy]"
}

function Read-Choice {
    param(
        [string]$Message,
        [string[]]$Options
    )
    if (-not $script:IsInteractive) { return 1 }
    Write-Host "  ?  $Message" -ForegroundColor Cyan
    for ($i = 0; $i -lt $Options.Length; $i++) {
        Write-Host "     $($i + 1)) $($Options[$i])" -ForegroundColor White
    }
    Write-Host "  >  " -ForegroundColor Cyan -NoNewline
    $choice = Read-Host
    if ([string]::IsNullOrWhiteSpace($choice)) { return 1 }
    return [int]$choice
}

function Start-Spinner {
    param([string]$Message)
    $script:SpinnerJob = Start-Job -ScriptBlock {
        param($msg, $frames)
        $i = 0
        while ($true) {
            Write-Host "`r  $($frames[$i])  $msg" -NoNewline
            $i = ($i + 1) % $frames.Length
            Start-Sleep -Milliseconds 80
        }
    } -ArgumentList $Message, $script:SPINNER_FRAMES
}

function Stop-Spinner {
    param(
        [bool]$Success,
        [string]$Message
    )
    if ($null -ne $script:SpinnerJob) {
        Stop-Job -Job $script:SpinnerJob -ErrorAction SilentlyContinue
        Remove-Job -Job $script:SpinnerJob -Force -ErrorAction SilentlyContinue
        $script:SpinnerJob = $null
    }
    Write-Host "`r                                                                        `r" -NoNewline
    if ($Success) {
        Write-Ok $Message
    } else {
        Write-Err $Message
    }
}

function Show-Progress {
    param(
        [int]$Current,
        [int]$Total,
        [string]$Label
    )
    $pct = [math]::Floor(($Current / $Total) * 100)
    $filled = [math]::Floor(($Current / $Total) * 40)
    $empty = 40 - $filled
    $bar = ("█" * $filled) + ("░" * $empty)
    Write-Host "`r  [$bar] $("{0,3}" -f $pct)%  $Label" -NoNewline -ForegroundColor Cyan
    if ($Current -eq $Total) { Write-Host "" }
}

# ── Requirement checks ──────────────────────────────────────────────────────

function Find-Python {
    $candidates = @("python", "python3", "py")
    foreach ($cmd in $candidates) {
        try {
            $null = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0) { return $cmd }
        } catch { }
    }
    return $null
}

function Test-PythonVersion {
    param([string]$PythonCmd)
    $versionStr = & $PythonCmd --version 2>&1
    if ($versionStr -match "(\d+)\.(\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        $version = $Matches[0]
        if ($major -gt $script:MIN_PYTHON_MAJOR -or
            ($major -eq $script:MIN_PYTHON_MAJOR -and $minor -ge $script:MIN_PYTHON_MINOR)) {
            return @{ Valid = $true; Version = $version }
        }
        return @{ Valid = $false; Version = $version }
    }
    return @{ Valid = $false; Version = "unknown" }
}

function Test-Requirements {
    Write-Section "Checking Requirements"

    $step = 0; $total = 4

    # ── Platform ─────────────────────────────────────────────────────────
    $step++
    Show-Progress $step $total "Detecting platform"
    $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
    $osVersion = [Environment]::OSVersion.VersionString
    Write-Ok "Platform: Windows $arch ($osVersion)"

    # ── Python ───────────────────────────────────────────────────────────
    $step++
    Show-Progress $step $total "Checking Python"
    $script:PythonCmd = Find-Python
    if ($null -eq $script:PythonCmd) {
        Write-Err "Python not found."
        Write-Err "Please install Python $($script:MIN_PYTHON_MAJOR).$($script:MIN_PYTHON_MINOR)+ from https://www.python.org/downloads/"
        exit 1
    }
    $pyResult = Test-PythonVersion $script:PythonCmd
    if ($pyResult.Valid) {
        Write-Ok "Python $($pyResult.Version) ($($script:PythonCmd))"
    } else {
        Write-Err "Python $($pyResult.Version) found, but $($script:MIN_PYTHON_MAJOR).$($script:MIN_PYTHON_MINOR)+ is required."
        Write-Err "Please upgrade Python from https://www.python.org/downloads/"
        exit 1
    }

    # ── UV ───────────────────────────────────────────────────────────────
    $step++
    Show-Progress $step $total "Checking UV"
    try {
        $uvVer = & uv --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $uvVer -match "[\d.]+") {
            Write-Ok "UV $($Matches[0])"
            $script:HasUV = $true
        } else { throw "not found" }
    } catch {
        Write-Warn "UV not found"
        if (Read-YesNo "Install UV (recommended package manager)?") {
            Write-Info "Installing UV..."
            try {
                Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
                $script:HasUV = $true
                Write-Ok "UV installed successfully"
            } catch {
                Write-Warn "Could not install UV. Falling back to pip."
            }
        } else {
            Write-Info "Falling back to pip for installation"
        }
    }

    # ── Git ──────────────────────────────────────────────────────────────
    $step++
    Show-Progress $step $total "Checking Git"
    try {
        $gitVer = & git --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $gitVer -match "[\d.]+") {
            Write-Ok "Git $($Matches[0])"
            $script:HasGit = $true
        } else { throw "not found" }
    } catch {
        Write-Warn "Git not found (required only for source installation)"
    }

    Write-Host ""
}

# ── Installation ─────────────────────────────────────────────────────────────

function Select-Extras {
    Write-Section "Extras Selection"

    Write-Info "Select which optional components to install:"
    Write-Host ""

    $options = @(
        "Core only (no optional dependencies)",
        "REST API (FastAPI + Uvicorn + SSE)",
        "Kafka (aiokafka)",
        "RabbitMQ (aio-pika)",
        "Redis (redis-py)",
        "All queues (Kafka + RabbitMQ + Redis)",
        "Everything (REST + all queues + costs)"
    )

    $choice = Read-Choice "Choose a configuration:" $options

    switch ($choice) {
        2 { $script:SelectedExtras = "rest" }
        3 { $script:SelectedExtras = "kafka" }
        4 { $script:SelectedExtras = "rabbitmq" }
        5 { $script:SelectedExtras = "redis" }
        6 { $script:SelectedExtras = "queues" }
        7 { $script:SelectedExtras = "all" }
        default { $script:SelectedExtras = "" }
    }

    if ($script:SelectedExtras) {
        Write-Ok "Extras: $($script:SelectedExtras)"
    } else {
        Write-Ok "Extras: core only"
    }
}

function Install-FromSource {
    Write-Section "Installing from Source"

    $targetDir = $script:PACKAGE

    # ── Clone ────────────────────────────────────────────────────────────
    if (Test-Path $targetDir) {
        Write-Warn "Directory '$targetDir' already exists."
        if (Read-YesNo "Remove and re-clone?") {
            Remove-Item -Recurse -Force $targetDir
        } else {
            Write-Info "Using existing directory"
        }
    }

    if (-not (Test-Path $targetDir)) {
        Write-Info "Cloning repository..."
        try {
            & git clone $script:REPO_URL $targetDir 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Repository cloned"
            } else { throw "clone failed" }
        } catch {
            Write-Err "Could not clone $($script:REPO_URL)"
            exit 1
        }
    }

    # ── Install dependencies ─────────────────────────────────────────────
    Push-Location $targetDir
    try {
        if ($script:HasUV) {
            $uvArgs = @("sync")
            if ([string]::IsNullOrEmpty($script:SelectedExtras)) {
                # Core only — no extras
            } elseif ($script:SelectedExtras -eq "all") {
                $uvArgs = @("sync", "--all-extras")
            } else {
                # Map comma-separated extras to --extra flags
                $extras = $script:SelectedExtras -split ","
                foreach ($extra in $extras) {
                    $uvArgs += "--extra"
                    $uvArgs += $extra.Trim()
                }
            }
            Write-Info "Installing dependencies via UV ($($uvArgs -join ' '))..."
            & uv @uvArgs 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Dependencies installed via UV"
            } else { throw "uv sync failed" }
        } else {
            $pkgSpec = "."
            if ($script:SelectedExtras) { $pkgSpec = ".[$($script:SelectedExtras)]" }
            Write-Info "Installing dependencies via pip..."
            & $script:PythonCmd -m pip install -e $pkgSpec 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Dependencies installed via pip"
            } else { throw "pip install failed" }
        }
    } catch {
        Write-Err "Dependency installation failed: $_"
        exit 1
    } finally {
        Pop-Location
    }
}

function Test-Installation {
    Write-Section "Verifying Installation"

    Write-Info "Verifying package import..."
    try {
        $ver = & $script:PythonCmd -c "import fireflyframework_agentic; print(fireflyframework_agentic.__version__)" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "fireflyframework-agentic v$ver is ready"
            return $true
        }
    } catch { }
    Write-Warn "Verification failed — package could not be imported"
    Write-Warn "The package may require activating a virtual environment."
    return $false
}

function Show-Summary {
    Write-Section "Installation Complete"

    Write-Host "  ╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║" -ForegroundColor Green -NoNewline
    Write-Host "  fireflyframework-agentic v$($script:VERSION)" -ForegroundColor White -NoNewline
    Write-Host " installed successfully!       " -NoNewline
    Write-Host "║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""

    Write-Info "Quick Start:"
    Write-Host ""
    Write-Host "  # Configure your model provider" -ForegroundColor DarkGray
    Write-Host '  $env:OPENAI_API_KEY = "sk-..."' -ForegroundColor White
    Write-Host '  $env:FIREFLY_AGENTIC_DEFAULT_MODEL = "openai:gpt-4o"' -ForegroundColor White
    Write-Host ""
    Write-Host "  # Create your first agent" -ForegroundColor DarkGray
    Write-Host "  from fireflyframework_agentic.agents import firefly_agent" -ForegroundColor White
    Write-Host ""
    Write-Host '  @firefly_agent(name="assistant", model="openai:gpt-4o")' -ForegroundColor White
    Write-Host "  def instructions(ctx):" -ForegroundColor White
    Write-Host '      return "You are a helpful assistant."' -ForegroundColor White
    Write-Host ""
    Write-Info "Resources:"
    Write-Host "  Documentation:  https://github.com/fireflyframework/fireflyframework-agentic/tree/main/docs" -ForegroundColor DarkGray
    Write-Host "  Tutorial:       https://github.com/fireflyframework/fireflyframework-agentic/blob/main/docs/tutorial.md" -ForegroundColor DarkGray
    Write-Host "  Repository:     https://github.com/fireflyframework/fireflyframework-agentic" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

function Main {
    Show-Banner
    Test-Requirements

    if (-not $script:HasGit) {
        Write-Err "Git is required for installation."
        Write-Err "Please install Git from https://git-scm.com/downloads"
        exit 1
    }

    Select-Extras
    Install-FromSource
    Test-Installation | Out-Null
    Show-Summary
}

Main
