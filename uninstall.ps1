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
    Interactive uninstaller for fireflyframework-agentic.

.DESCRIPTION
    Removes fireflyframework-agentic with interactive confirmation, package
    detection, and optional cleanup of cached files and artifacts.

.PARAMETER NonInteractive
    Run in non-interactive mode with default options.

.PARAMETER SkipCleanup
    Skip the optional cleanup step (cache and artifact removal).

.EXAMPLE
    .\uninstall.ps1
    .\uninstall.ps1 -NonInteractive
    irm https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/uninstall.ps1 | iex
#>

[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$SkipCleanup
)

$ErrorActionPreference = "Stop"

# ── Constants ────────────────────────────────────────────────────────────────

$script:VERSION = "26.01.01"
$script:PACKAGE = "fireflyframework-agentic"
$script:PACKAGE_IMPORT = "fireflyframework_agentic"

# ── State ────────────────────────────────────────────────────────────────────

$script:PythonCmd = ""
$script:HasUV = $false
$script:InstalledVersion = ""
$script:InstallLocation = ""
$script:IsInteractive = -not $NonInteractive

if ($null -eq $Host.UI -or $null -eq $Host.UI.RawUI) {
    $script:IsInteractive = $false
}

# ── Utility functions ────────────────────────────────────────────────────────

function Show-Banner {
    Write-Host ""
    Write-Host "  _____.__                _____.__" -ForegroundColor Cyan
    Write-Host "_/ ____\__|______   _____/ ____\  | ___.__."-ForegroundColor Cyan
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
    Write-Host " Uninstaller" -ForegroundColor DarkGray
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

# ── Python detection ─────────────────────────────────────────────────────────

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

# ── Detection ────────────────────────────────────────────────────────────────

function Find-Installation {
    Write-Section "Detecting Installation"

    $script:PythonCmd = Find-Python
    if ($null -eq $script:PythonCmd) {
        Write-Err "Python not found. Cannot detect package installation."
        exit 1
    }

    # Check if package is importable
    try {
        $script:InstalledVersion = & $script:PythonCmd -c "import $($script:PACKAGE_IMPORT); print($($script:PACKAGE_IMPORT).__version__)" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Found $($script:PACKAGE) v$($script:InstalledVersion)"
        } else { throw "not importable" }
    } catch {
        # Fallback to pip show
        try {
            $pipOutput = & $script:PythonCmd -m pip show $script:PACKAGE 2>&1
            if ($LASTEXITCODE -eq 0) {
                $script:InstalledVersion = ($pipOutput | Select-String "^Version:").ToString().Split(":")[1].Trim()
                Write-Ok "Found $($script:PACKAGE) v$($script:InstalledVersion) (pip)"
            } else { throw "not installed" }
        } catch {
            Write-Warn "$($script:PACKAGE) does not appear to be installed."
            exit 0
        }
    }

    # Detect location
    try {
        $pipOutput = & $script:PythonCmd -m pip show $script:PACKAGE 2>&1
        if ($LASTEXITCODE -eq 0) {
            $locationLine = $pipOutput | Select-String "^Location:"
            if ($locationLine) {
                $script:InstallLocation = $locationLine.ToString().Split(":", 2)[1].Trim()
                Write-Info "Location: $($script:InstallLocation)"
            }
        }
    } catch { }

    # Detect UV
    try {
        $null = & uv --version 2>&1
        if ($LASTEXITCODE -eq 0) { $script:HasUV = $true }
    } catch { }
}

# ── Uninstallation ───────────────────────────────────────────────────────────

function Confirm-Uninstall {
    Write-Section "Confirmation"

    Write-Host "  The following package will be removed:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    • $($script:PACKAGE) v$($script:InstalledVersion)" -ForegroundColor White
    if ($script:InstallLocation) {
        Write-Host "      Location: $($script:InstallLocation)" -ForegroundColor DarkGray
    }
    Write-Host ""

    if (-not (Read-YesNo "Proceed with uninstallation?")) {
        Write-Info "Uninstallation cancelled."
        exit 0
    }
}

function Remove-Package {
    Write-Section "Removing Package"

    if ($script:HasUV) {
        Write-Info "Removing $($script:PACKAGE) via UV..."
        try {
            & uv pip uninstall $script:PACKAGE 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "Removed $($script:PACKAGE) via UV"
                return
            }
        } catch { }
        Write-Warn "UV removal failed, trying pip..."
    }

    Write-Info "Removing $($script:PACKAGE) via pip..."
    try {
        & $script:PythonCmd -m pip uninstall -y $script:PACKAGE 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Removed $($script:PACKAGE) via pip"
        } else { throw "removal failed" }
    } catch {
        Write-Err "Could not remove $($script:PACKAGE)"
        Write-Err "Please try manually: $($script:PythonCmd) -m pip uninstall $($script:PACKAGE)"
        exit 1
    }
}

function Clear-Artifacts {
    if ($SkipCleanup) {
        Write-Info "Skipping cleanup (--SkipCleanup)"
        return
    }

    Write-Section "Cleanup"

    # Clean pip cache
    if (Read-YesNo "Remove cached package files?" $false) {
        Write-Info "Cleaning pip cache..."
        try {
            & $script:PythonCmd -m pip cache purge 2>&1 | Out-Null
            Write-Ok "Cache cleaned"
        } catch {
            Write-Warn "Could not clean cache"
        }
    } else {
        Write-Info "Skipping cache cleanup"
    }

    # Clean source directory if present
    if (Test-Path $script:PACKAGE) {
        if (Read-YesNo "Remove local source directory '$($script:PACKAGE)\'?" $false) {
            Write-Info "Removing source directory..."
            Remove-Item -Recurse -Force $script:PACKAGE
            Write-Ok "Source directory removed"
        } else {
            Write-Info "Keeping source directory"
        }
    }

    # Clean __pycache__
    $pycacheDirs = Get-ChildItem -Path . -Filter "__pycache__" -Directory -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match $script:PACKAGE_IMPORT }
    if ($pycacheDirs -and $pycacheDirs.Count -gt 0) {
        if (Read-YesNo "Remove __pycache__ artifacts ($($pycacheDirs.Count) directories)?" $false) {
            $pycacheDirs | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
            Write-Ok "Cache artifacts removed"
        }
    }
}

function Test-Removal {
    Write-Section "Verification"

    Write-Info "Verifying removal..."
    try {
        & $script:PythonCmd -c "import $($script:PACKAGE_IMPORT)" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Err "Package is still importable — removal may be incomplete"
            Write-Warn "Try: $($script:PythonCmd) -m pip uninstall $($script:PACKAGE)"
        } else { throw "gone" }
    } catch {
        Write-Ok "Package successfully removed"
    }
}

function Show-Farewell {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║" -ForegroundColor Green -NoNewline
    Write-Host "  fireflyframework-agentic" -ForegroundColor White -NoNewline
    Write-Host " has been uninstalled.                " -NoNewline
    Write-Host "║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Info "Thank you for using fireflyframework-agentic!"
    Write-Host ""
    Write-Host "  Reinstall anytime:" -ForegroundColor DarkGray
    Write-Host "  irm https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.ps1 | iex" -ForegroundColor White
    Write-Host ""
    Write-Host "  Repository:  https://github.com/fireflyframework/fireflyframework-agentic" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

function Main {
    Show-Banner
    Find-Installation
    Confirm-Uninstall
    Remove-Package
    Clear-Artifacts
    Test-Removal
    Show-Farewell
}

Main
