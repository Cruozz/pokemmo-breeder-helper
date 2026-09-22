param([Parameter(Mandatory = $true)][string]$SourcePath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$resDir = Join-Path $PSScriptRoot '..\app\src\main\res'
$artDir = Join-Path $resDir 'drawable-nodpi'
New-Item -ItemType Directory -Force -Path $artDir | Out-Null
Copy-Item -LiteralPath $SourcePath -Destination (Join-Path $artDir 'launch_art.png')
$art = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $SourcePath))
try {
  $side = [Math]::Min($art.Width, $art.Height)
  $crop = [System.Drawing.Rectangle]::new([int](($art.Width - $side) / 2), [int](($art.Height - $side) / 2), $side, $side)
  $sizes = @{ 'mipmap-mdpi' = 48; 'mipmap-hdpi' = 72; 'mipmap-xhdpi' = 96; 'mipmap-xxhdpi' = 144; 'mipmap-xxxhdpi' = 192; 'drawable-nodpi' = 432 }
  foreach ($entry in $sizes.GetEnumerator()) {
    $folder = Join-Path $resDir $entry.Key
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $bitmap = [System.Drawing.Bitmap]::new($entry.Value, $entry.Value)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
      $graphics.DrawImage($art, [System.Drawing.Rectangle]::new(0, 0, $entry.Value, $entry.Value), $crop, [System.Drawing.GraphicsUnit]::Pixel)
      $bitmap.Save((Join-Path $folder 'breeder_launcher.png'), [System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
  }
} finally { $art.Dispose() }
