param(
  [switch]$SkipBackend,
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$atlasDir = Join-Path $repoRoot "apps\atlas"
$tauriDir = Join-Path $atlasDir "src-tauri"

if (-not (Test-Path -LiteralPath $pythonExe)) {
  throw "Python environment not found: $pythonExe"
}

Write-Host "Checking Atlas version consistency..." -ForegroundColor Cyan
Push-Location $repoRoot
try {
  & $pythonExe scripts\check_atlas_version.py
  if ($LASTEXITCODE -ne 0) {
    throw "Atlas version check failed with exit code $LASTEXITCODE."
  }
} finally {
  Pop-Location
}

if (-not $SkipBackend) {
  Write-Host "Running backend test suite..." -ForegroundColor Cyan
  Push-Location $repoRoot
  try {
    & $pythonExe -m unittest discover -s tests -p "test_*.py"
    if ($LASTEXITCODE -ne 0) {
      throw "Backend tests failed with exit code $LASTEXITCODE."
    }
  } finally {
    Pop-Location
  }
}

if (-not $SkipFrontend) {
  if (-not (Test-Path -LiteralPath $atlasDir)) {
    throw "Atlas desktop directory not found: $atlasDir"
  }

  Write-Host "Running desktop release build chain..." -ForegroundColor Cyan
  Push-Location $atlasDir
  try {
    npm.cmd run build:release
    if ($LASTEXITCODE -ne 0) {
      throw "Desktop release build failed with exit code $LASTEXITCODE."
    }
  } finally {
    Pop-Location
  }

  if (-not (Test-Path -LiteralPath $tauriDir)) {
    throw "Atlas Tauri directory not found: $tauriDir"
  }

  Write-Host "Running Rust desktop shell compile check..." -ForegroundColor Cyan
  Push-Location $tauriDir
  try {
    cargo check
    if ($LASTEXITCODE -ne 0) {
      throw "Rust compile check failed with exit code $LASTEXITCODE."
    }
  } finally {
    Pop-Location
  }
}

Write-Host "Repository verification complete." -ForegroundColor Green
