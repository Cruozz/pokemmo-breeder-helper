param(
    [string]$Python = ""
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseRoot = Join-Path $project 'release'
$buildScript = Join-Path $project 'build.ps1'
$exeName = 'Pokemmo孵蛋助手-晨若.exe'
$exePath = Join-Path $releaseRoot $exeName
$zipPath = Join-Path $releaseRoot 'Pokemmo孵蛋助手-晨若-发布包.zip'

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

$buildArgs = @{
    OneFile = $true
    OutputDirectory = $releaseRoot
}
if ($Python) {
    $buildArgs.Python = $Python
}
& $buildScript @buildArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $exePath)) {
    throw "Release executable was not generated: $exePath"
}

$guideTarget = Join-Path $releaseRoot '使用说明.txt'
$noticesTarget = Join-Path $releaseRoot '第三方组件与数据声明.md'
Copy-Item -LiteralPath (Join-Path $project 'DISTRIBUTION_README.txt') -Destination $guideTarget -Force
Copy-Item -LiteralPath (Join-Path $project 'THIRD_PARTY_NOTICES.md') -Destination $noticesTarget -Force

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $exePath
$hashLine = "$($hash.Hash.ToLowerInvariant())  $exeName"
$hashPath = Join-Path $releaseRoot 'SHA256.txt'
Set-Content -LiteralPath $hashPath -Value $hashLine -Encoding UTF8

$packageFiles = @($exePath, $guideTarget, $noticesTarget, $hashPath)
Compress-Archive -LiteralPath $packageFiles -DestinationPath $zipPath -CompressionLevel Optimal -Force

Write-Host "Release executable: $exePath"
Write-Host "Release package:    $zipPath"
Write-Host "SHA-256:            $($hash.Hash)"
