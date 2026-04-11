param(
  [switch]$IncludeVenv,
  [switch]$IncludeData
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Remove-RepoPath([string]$RelativePath) {
  $fullPath = Join-Path $repoRoot $RelativePath
  if (-not (Test-Path -LiteralPath $fullPath)) {
    return
  }

  if (-not $fullPath.StartsWith($repoRoot)) {
    throw "Refusing to delete outside repo root: $fullPath"
  }

  try {
    Remove-Item -LiteralPath $fullPath -Recurse -Force
    Write-Host "Removed $RelativePath" -ForegroundColor DarkGray
  } catch {
    Write-Warning "Could not remove ${RelativePath}: $($_.Exception.Message)"
  }
}

$targets = @(
  "apps\atlas\src-tauri\target",
  "apps\atlas\src-tauri\resources\backend",
  "apps\atlas\src-tauri\resources\prompts",
  "apps\atlas\dist",
  "apps\atlas\output",
  "apps\atlas\.playwright-cli",
  ".playwright-cli",
  ".pytest_cache",
  "output",
  "test-results"
)

if ($IncludeVenv) {
  $targets += ".venv"
}

if ($IncludeData) {
  $targets += ".data"
}

foreach ($target in $targets) {
  Remove-RepoPath $target
}

$pycacheDirs = Get-ChildItem -Path $repoRoot -Recurse -Directory -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -eq "__pycache__" -and $_.FullName -notmatch "\\\.venv\\" }

foreach ($dir in $pycacheDirs) {
  $relative = $dir.FullName.Substring($repoRoot.Length).TrimStart("\")
  Remove-RepoPath $relative
}

$eggInfoDirs = Get-ChildItem -Path $repoRoot -Recurse -Directory -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "*.egg-info" -and $_.FullName -notmatch "\\\.venv\\" }

foreach ($dir in $eggInfoDirs) {
  $relative = $dir.FullName.Substring($repoRoot.Length).TrimStart("\")
  Remove-RepoPath $relative
}

Write-Host "Next Atlas launch may take longer because the desktop binary can be rebuilt from scratch." -ForegroundColor DarkGray
Write-Host "Repository cleanup complete." -ForegroundColor Green
