#requires -Version 7.0
param(
    [string]$Python = "",
    [string]$Version = ""
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseRoot = Join-Path $project 'release'
$buildScript = Join-Path $project 'build.ps1'
$exeName = 'Pokemmo孵蛋助手.exe'
$appSource = Get-Content -LiteralPath (Join-Path $project 'app.py') -Raw -Encoding UTF8
$sourceVersionMatch = [regex]::Match($appSource, '(?m)^APP_VERSION = "([^"\r\n]+)"')
if (-not $sourceVersionMatch.Success) { throw 'APP_VERSION was not found in app.py' }
$sourceVersion = $sourceVersionMatch.Groups[1].Value
if (-not $Version) { $Version = $sourceVersion }
$normalizedVersion = $Version.Trim().TrimStart('v', 'V')
if ($normalizedVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid release version: $Version. Use a value such as 0.2.5."
}
if ($normalizedVersion -ne $sourceVersion) {
    throw "Release version $normalizedVersion differs from APP_VERSION $sourceVersion"
}
$metadata = Get-Content -LiteralPath (Join-Path $project 'version_info.txt') -Raw -Encoding UTF8
foreach ($field in @('FileVersion', 'ProductVersion')) {
    if (-not $metadata.Contains("StringStruct('$field', '$normalizedVersion')")) {
        throw "Windows $field does not match $normalizedVersion"
    }
}
$zipPath = Join-Path $releaseRoot "Pokemmo孵蛋助手V$normalizedVersion.zip"
$versionRoot = Join-Path $releaseRoot "V$normalizedVersion"
$exePath = Join-Path $versionRoot $exeName
$canonicalExePath = Join-Path $releaseRoot $exeName

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
New-Item -ItemType Directory -Force -Path $versionRoot | Out-Null
$buildArgs = @{ OneFile = $true; OutputDirectory = $versionRoot }
if ($Python) { $buildArgs.Python = $Python }
& $buildScript @buildArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $exePath)) {
    throw "Release executable was not generated: $exePath"
}

# Validate the actual frozen executable before creating a distributable ZIP.
$actualVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($exePath).FileVersion
if ($actualVersion -ne $normalizedVersion) {
    throw "Built executable version $actualVersion does not match $normalizedVersion"
}
$reportPath = Join-Path $versionRoot 'self-test.json'
if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath -Force }
$selfTestArgs = '--self-test "' + $reportPath + '"'
$process = Start-Process -FilePath $exePath -WorkingDirectory $versionRoot -ArgumentList $selfTestArgs -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(180000)) {
    $process.Kill($true)
    throw 'Packaged self-test timed out after 180 seconds'
}
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) {
    throw "Packaged self-test failed; inspect $reportPath"
}
$selfTest = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $selfTest.ok -or -not $selfTest.frozen -or $selfTest.version -ne $normalizedVersion) {
    throw "Packaged self-test did not verify version $normalizedVersion"
}

$guideTarget = Join-Path $versionRoot '使用说明.txt'
$noticesTarget = Join-Path $versionRoot '第三方组件与数据声明.md'
Copy-Item -LiteralPath (Join-Path $project 'DISTRIBUTION_README.txt') -Destination $guideTarget -Force
Copy-Item -LiteralPath (Join-Path $project 'THIRD_PARTY_NOTICES.md') -Destination $noticesTarget -Force
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $exePath
$hashLine = "$($hash.Hash.ToLowerInvariant())  $exeName"
$hashPath = Join-Path $versionRoot 'SHA256.txt'
Set-Content -LiteralPath $hashPath -Value $hashLine -Encoding UTF8
$packageFiles = @($exePath, $guideTarget, $noticesTarget, $hashPath, $reportPath)
Compress-Archive -LiteralPath $packageFiles -DestinationPath $zipPath -CompressionLevel Optimal -Force

$zipHash = Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath
$checksumsPath = Join-Path $releaseRoot 'SHA256SUMS.txt'
@(
    $hashLine
    "$($zipHash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($zipPath))"
) | Set-Content -LiteralPath $checksumsPath -Encoding UTF8

# A running old loose EXE must not prevent the versioned release from building.
try {
    Copy-Item -LiteralPath $exePath -Destination $canonicalExePath -Force -ErrorAction Stop
} catch {
    Write-Warning "Canonical EXE is in use; kept the new EXE in $versionRoot. The ZIP is unaffected."
}
Write-Host "Release executable: $exePath"
Write-Host "Release package:    $zipPath"
Write-Host "Self-test report:   $reportPath"
Write-Host "Checksums:          $checksumsPath"
Write-Host "SHA-256:            $($hash.Hash)"
