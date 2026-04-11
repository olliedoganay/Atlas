$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $repoRoot "apps\atlas\public\AtlasLogo.png"
$preparedPath = Join-Path $repoRoot "apps\atlas\src-tauri\icons\AtlasLogo.prepared.png"
$atlasDir = Join-Path $repoRoot "apps\atlas"

if (-not (Test-Path $sourcePath)) {
  throw "Atlas logo source not found: $sourcePath"
}

Add-Type -AssemblyName System.Drawing

$bitmap = [System.Drawing.Bitmap]::FromFile($sourcePath)
try {
  $minX = $bitmap.Width
  $minY = $bitmap.Height
  $maxX = -1
  $maxY = -1

  for ($y = 0; $y -lt $bitmap.Height; $y++) {
    for ($x = 0; $x -lt $bitmap.Width; $x++) {
      $pixel = $bitmap.GetPixel($x, $y)
      if ($pixel.A -gt 8) {
        if ($x -lt $minX) { $minX = $x }
        if ($y -lt $minY) { $minY = $y }
        if ($x -gt $maxX) { $maxX = $x }
        if ($y -gt $maxY) { $maxY = $y }
      }
    }
  }

  if ($maxX -lt $minX -or $maxY -lt $minY) {
    throw "AtlasLogo.png does not contain visible pixels."
  }

  $cropWidth = $maxX - $minX + 1
  $cropHeight = $maxY - $minY + 1
  $cropRect = New-Object System.Drawing.Rectangle($minX, $minY, $cropWidth, $cropHeight)
  $cropped = $bitmap.Clone($cropRect, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
} finally {
  $bitmap.Dispose()
}

try {
  $canvasSize = 1024
  $padding = 64
  $targetSize = $canvasSize - ($padding * 2)
  $scale = [Math]::Min($targetSize / $cropped.Width, $targetSize / $cropped.Height)
  $drawWidth = [int][Math]::Round($cropped.Width * $scale)
  $drawHeight = [int][Math]::Round($cropped.Height * $scale)
  $drawX = [int][Math]::Round(($canvasSize - $drawWidth) / 2)
  $drawY = [int][Math]::Round(($canvasSize - $drawHeight) / 2)

  $canvas = New-Object System.Drawing.Bitmap($canvasSize, $canvasSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    try {
      $graphics.Clear([System.Drawing.Color]::Transparent)
      $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
      $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
      $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
      $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
      $graphics.DrawImage($cropped, $drawX, $drawY, $drawWidth, $drawHeight)
    } finally {
      $graphics.Dispose()
    }

    $canvas.Save($preparedPath, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $canvas.Dispose()
  }
} finally {
  $cropped.Dispose()
}

Set-Location $atlasDir
npm exec tauri icon src-tauri/icons/AtlasLogo.prepared.png
