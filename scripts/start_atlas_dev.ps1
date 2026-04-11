$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$atlasDir = (Resolve-Path (Join-Path $repoRoot "apps\atlas")).Path
$vitePort = 1420
$debugExe = Join-Path $atlasDir "src-tauri\target\debug\atlas-desktop.exe"

if (-not (Test-Path $atlasDir)) {
  throw "Atlas desktop directory not found: $atlasDir"
}

function Get-AtlasDesktopProcess {
  $processes = Get-Process atlas-desktop -ErrorAction SilentlyContinue
  foreach ($process in $processes) {
    $path = ""
    try {
      $path = $process.Path
    } catch {
      $path = ""
    }

    if (-not $path -or $path -like "$atlasDir*") {
      return $process
    }
  }

  return $null
}

function Get-PortOwner([int]$Port) {
  $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $connection) {
    return $null
  }
  return Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" -ErrorAction SilentlyContinue
}

function Get-AtlasBackendProcess {
  $pythonProcesses = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue
  foreach ($process in $pythonProcesses) {
    $commandLine = [string]$process.CommandLine
    if ($commandLine.Contains("atlas_local.api") -and $commandLine.Contains($repoRoot)) {
      return $process
    }
  }
  return $null
}

function Test-AtlasViteProcess($ProcessInfo) {
  if (-not $ProcessInfo) {
    return $false
  }

  $name = [string]$ProcessInfo.Name
  $commandLine = (([string]$ProcessInfo.CommandLine) -replace "/", "\")
  return $name -match '^node(\.exe)?$' -and $commandLine.Contains($atlasDir) -and $commandLine -match 'vite(\.js)?'
}

function Focus-AtlasWindow($ProcessInfo) {
  if (-not $ProcessInfo) {
    return
  }

  if (-not ("AtlasWindow" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class AtlasWindow {
  [DllImport("user32.dll")]
  public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
  }

  if ($ProcessInfo.MainWindowHandle -ne 0) {
    [AtlasWindow]::ShowWindowAsync($ProcessInfo.MainWindowHandle, 9) | Out-Null
    [AtlasWindow]::SetForegroundWindow($ProcessInfo.MainWindowHandle) | Out-Null
  }
}

function Start-AtlasDesktopExecutable {
  if (-not (Test-Path $debugExe)) {
    return $false
  }

  Start-Process -FilePath $debugExe -WorkingDirectory (Split-Path $debugExe -Parent) | Out-Null
  return $true
}

function Stop-AtlasOwnedProcess($ProcessInfo, [string]$Label) {
  if (-not $ProcessInfo) {
    return
  }

  $processId = $ProcessInfo.Id
  if (-not $processId) {
    $processId = $ProcessInfo.ProcessId
  }

  if (-not $processId) {
    return
  }

  Write-Host "Stopping $Label (PID $processId)." -ForegroundColor DarkYellow
  Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}

$existingAtlas = Get-AtlasDesktopProcess
$portOwner = Get-PortOwner -Port $vitePort
$backendProcess = Get-AtlasBackendProcess
$atlasViteRunning = Test-AtlasViteProcess $portOwner

if ($existingAtlas -and $atlasViteRunning -and $backendProcess) {
  Write-Host "Atlas is already running. Reusing the existing window." -ForegroundColor Green
  Focus-AtlasWindow $existingAtlas
  exit 0
}

if ($existingAtlas -and $atlasViteRunning -and -not $backendProcess) {
  Write-Host "Atlas frontend is open but the managed backend is down. Relaunching the desktop window." -ForegroundColor Yellow
  Stop-Process -Id $existingAtlas.Id -Force
  Start-Sleep -Milliseconds 700
  if (Start-AtlasDesktopExecutable) {
    exit 0
  }
}

if (-not $existingAtlas -and $atlasViteRunning) {
  Write-Host "Atlas dev server is already running. Launching the desktop window." -ForegroundColor Green
  if (Start-AtlasDesktopExecutable) {
    exit 0
  }
  Write-Host "No reusable desktop binary was found. Recycling the old dev session first." -ForegroundColor Yellow
}

if ($atlasViteRunning) {
  Stop-AtlasOwnedProcess $portOwner "Atlas dev server"
  if ($backendProcess) {
    Stop-AtlasOwnedProcess $backendProcess "Atlas backend"
  }
  Start-Sleep -Milliseconds 700
}

if ($portOwner -and -not $atlasViteRunning) {
  $commandLine = ([string]$portOwner.CommandLine).Trim()
  throw "Port $vitePort is already in use by PID $($portOwner.ProcessId) ($($portOwner.Name)). Command: $commandLine"
}

Set-Location $atlasDir

Write-Host "Starting Atlas from source in $atlasDir" -ForegroundColor Cyan
Write-Host "This launcher uses the current repo state, not the installed AppData build." -ForegroundColor DarkGray
Write-Host ""

npm run tauri dev
