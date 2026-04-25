param(
  [string]$PackageIdentityName = $env:ATLAS_MSIX_IDENTITY_NAME,
  [string]$Publisher = $env:ATLAS_MSIX_PUBLISHER,
  [string]$PublisherDisplayName = $env:ATLAS_MSIX_PUBLISHER_DISPLAY_NAME,
  [switch]$SkipTauriBuild
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$atlasDir = Join-Path $repoRoot "apps\atlas"
$tauriDir = Join-Path $atlasDir "src-tauri"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$releaseDir = Join-Path $tauriDir "target\release"
$releaseExe = Join-Path $releaseDir "atlas-desktop.exe"
$releaseResources = Join-Path $releaseDir "resources"
$iconDir = Join-Path $tauriDir "icons"
$msixRoot = Join-Path $repoRoot "output\msix"
$stageRoot = Join-Path $msixRoot "stage"
$packageRoot = Join-Path $stageRoot "AtlasChat"
$packageAssets = Join-Path $packageRoot "Assets"
$packageOutput = Join-Path $msixRoot "packages"

function Assert-PathInside {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Parent
  )

  $fullPath = [System.IO.Path]::GetFullPath($Path)
  $fullParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
  if (-not $fullPath.StartsWith($fullParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to operate outside $fullParent`: $fullPath"
  }
  return $fullPath
}

function Find-WindowsSdkTool {
  param([Parameter(Mandatory = $true)][string]$Name)

  $existing = Get-Command $Name -ErrorAction SilentlyContinue
  if ($existing) {
    return $existing.Source
  }

  $programFilesX86 = ${env:ProgramFiles(x86)}
  if (-not $programFilesX86) {
    throw "ProgramFiles(x86) is not available; cannot locate Windows SDK tool $Name."
  }

  $sdkBin = Join-Path $programFilesX86 "Windows Kits\10\bin"
  if (-not (Test-Path -LiteralPath $sdkBin)) {
    throw "Windows SDK bin directory was not found: $sdkBin"
  }

  $tool = Get-ChildItem -Path $sdkBin -Recurse -Filter $Name -File |
    Where-Object { $_.FullName -match "\\x64\\$([regex]::Escape($Name))$" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1

  if (-not $tool) {
    throw "Windows SDK tool $Name was not found. Install the Windows 10/11 SDK."
  }

  return $tool.FullName
}

function Convert-ToMsixVersion {
  param([Parameter(Mandatory = $true)][string]$Version)

  if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$') {
    throw "Atlas version '$Version' is not compatible with MSIX versioning."
  }

  return "$($Matches[1]).$($Matches[2]).$($Matches[3]).0"
}

function Escape-Xml {
  param([Parameter(Mandatory = $true)][string]$Value)
  return [System.Security.SecurityElement]::Escape($Value)
}

if (-not (Test-Path -LiteralPath $atlasDir)) {
  throw "Atlas desktop directory not found: $atlasDir"
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
  throw "Python environment not found: $pythonExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $atlasDir "node_modules"))) {
  throw "Frontend dependencies not found. Run 'npm install' in apps\atlas first."
}

if (-not $PackageIdentityName) {
  $PackageIdentityName = "AtlasChat"
  Write-Warning "ATLAS_MSIX_IDENTITY_NAME is not set. Using placeholder Package/Identity/Name '$PackageIdentityName'. Use the exact Partner Center Product identity before Store upload."
}

if (-not $Publisher) {
  $Publisher = "CN=atlaschat"
  Write-Warning "ATLAS_MSIX_PUBLISHER is not set. Using placeholder Package/Identity/Publisher '$Publisher'. Use the exact Partner Center Product identity before Store upload."
}

if (-not $PublisherDisplayName) {
  $PublisherDisplayName = "atlaschat"
}

$version = (& $pythonExe scripts\check_atlas_version.py).Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) {
  throw "Atlas version check failed."
}

$msixVersion = Convert-ToMsixVersion $version
$outputMsix = Join-Path $packageOutput "Atlas-Chat-$msixVersion-x64.msix"
$makeAppx = Find-WindowsSdkTool "makeappx.exe"

if (-not $SkipTauriBuild) {
  Write-Host "Building Atlas release binary before MSIX packaging..." -ForegroundColor Cyan
  & (Join-Path $PSScriptRoot "build_atlas_release.ps1")
  if ($LASTEXITCODE -ne 0) {
    throw "Atlas release build failed with exit code $LASTEXITCODE."
  }
}

if (-not (Test-Path -LiteralPath $releaseExe)) {
  throw "Release executable not found: $releaseExe"
}

if (-not (Test-Path -LiteralPath $releaseResources)) {
  throw "Release resources not found: $releaseResources"
}

$stageRoot = Assert-PathInside -Path $stageRoot -Parent $repoRoot
$packageOutput = Assert-PathInside -Path $packageOutput -Parent $repoRoot

if (Test-Path -LiteralPath $stageRoot) {
  Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $packageRoot, $packageAssets, $packageOutput | Out-Null

Copy-Item -LiteralPath $releaseExe -Destination (Join-Path $packageRoot "atlas-desktop.exe")
Copy-Item -LiteralPath $releaseResources -Destination $packageRoot -Recurse

$assetNames = @(
  "Square44x44Logo.png",
  "Square150x150Logo.png",
  "StoreLogo.png"
)

foreach ($assetName in $assetNames) {
  $assetSource = Join-Path $iconDir $assetName
  if (-not (Test-Path -LiteralPath $assetSource)) {
    throw "Required MSIX visual asset not found: $assetSource"
  }
  Copy-Item -LiteralPath $assetSource -Destination (Join-Path $packageAssets $assetName)
}

$manifestPath = Join-Path $packageRoot "AppxManifest.xml"
$identityNameXml = Escape-Xml $PackageIdentityName
$publisherXml = Escape-Xml $Publisher
$publisherDisplayNameXml = Escape-Xml $PublisherDisplayName

$manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">
  <Identity
    Name="$identityNameXml"
    Publisher="$publisherXml"
    Version="$msixVersion"
    ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>Atlas Chat</DisplayName>
    <PublisherDisplayName>$publisherDisplayNameXml</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.22631.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application Id="AtlasChat" Executable="atlas-desktop.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="Atlas Chat"
        Description="Local AI workspace for Ollama"
        BackgroundColor="#191a1d"
        Square150x150Logo="Assets\Square150x150Logo.png"
        Square44x44Logo="Assets\Square44x44Logo.png" />
    </Application>
  </Applications>
  <Capabilities>
    <Capability Name="internetClient" />
    <Capability Name="privateNetworkClientServer" />
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"@

Set-Content -LiteralPath $manifestPath -Value $manifest -Encoding UTF8

Write-Host "Packing Atlas MSIX..." -ForegroundColor Cyan
& $makeAppx pack /d $packageRoot /p $outputMsix /o
if ($LASTEXITCODE -ne 0) {
  throw "makeappx failed with exit code $LASTEXITCODE."
}

$signature = Get-AuthenticodeSignature -LiteralPath $outputMsix
$relativePackage = $outputMsix.Substring($repoRoot.Length).TrimStart("\")
$relativeManifest = $manifestPath.Substring($repoRoot.Length).TrimStart("\")

Write-Host ""
Write-Host "MSIX package:" -ForegroundColor Green
Write-Host " - $relativePackage"
Write-Host ""
Write-Host "Generated manifest:" -ForegroundColor Green
Write-Host " - $relativeManifest"
Write-Host ""
Write-Host "Package identity:" -ForegroundColor Green
Write-Host " - Name: $PackageIdentityName"
Write-Host " - Publisher: $Publisher"
Write-Host " - Publisher display name: $PublisherDisplayName"
Write-Host " - Version: $msixVersion"
Write-Host ""
Write-Host "Signature status: $($signature.Status)"
Write-Host "For Microsoft Store MSIX upload, use the exact Product identity values from Partner Center. Store certification re-signs accepted MSIX packages."
