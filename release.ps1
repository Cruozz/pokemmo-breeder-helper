param(
    [string]$Python = "",
    [string]$Version = "0.19"
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseRoot = Join-Path $project 'release'
$buildScript = Join-Path $project 'build.ps1'
$exeName = 'Pokemmo孵蛋助手-晨若.exe'
$normalizedVersion = $Version.Trim().TrimStart('v', 'V')
if ($normalizedVersion -notmatch '^\d+(\.\d+){1,2}$') {
    throw "Invalid release version: $Version. Use a value such as 0.1 or 0.2."
}
$zipPath = Join-Path $releaseRoot "Pokemmo孵蛋助手V$normalizedVersion.zip"
$versionRoot = Join-Path $releaseRoot "V$normalizedVersion"
$exePath = Join-Path $versionRoot $exeName
$canonicalExePath = Join-Path $releaseRoot $exeName

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
New-Item -ItemType Directory -Force -Path $versionRoot | Out-Null

$buildArgs = @{
    OneFile = $true
    OutputDirectory = $versionRoot
}
if ($Python) {
    $buildArgs.Python = $Python
}
& $buildScript @buildArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $exePath)) {
    throw "Release executable was not generated: $exePath"
}

$guideTarget = Join-Path $versionRoot '使用说明.txt'
$noticesTarget = Join-Path $versionRoot '第三方组件与数据声明.md'
Copy-Item -LiteralPath (Join-Path $project 'DISTRIBUTION_README.txt') -Destination $guideTarget -Force
Copy-Item -LiteralPath (Join-Path $project 'THIRD_PARTY_NOTICES.md') -Destination $noticesTarget -Force

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $exePath
$hashLine = "$($hash.Hash.ToLowerInvariant())  $exeName"
$hashPath = Join-Path $versionRoot 'SHA256.txt'
Set-Content -LiteralPath $hashPath -Value $hashLine -Encoding UTF8

$packageFiles = @($exePath, $guideTarget, $noticesTarget, $hashPath)
Compress-Archive -LiteralPath $packageFiles -DestinationPath $zipPath -CompressionLevel Optimal -Force

# Keep the traditional loose EXE when it is not currently running.  The ZIP
# and versioned directory are already complete even if Windows has the old
# canonical EXE locked, so a live previous release no longer blocks packaging.
try {
    Copy-Item -LiteralPath $exePath -Destination $canonicalExePath -Force -ErrorAction Stop
} catch {
    Write-Warning "Canonical EXE is in use; kept the new EXE in $versionRoot. The ZIP is unaffected."
}

Write-Host "Release executable: $exePath"
Write-Host "Release package:    $zipPath"
Write-Host "SHA-256:            $($hash.Hash)"
