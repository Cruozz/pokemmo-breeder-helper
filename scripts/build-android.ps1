#requires -Version 7.0
param(
    [string]$Python = '',
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [switch]$DeviceTests
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $localPython = Join-Path $project '.runtime/python312/python.exe'
    if (Test-Path -LiteralPath $localPython) { $Python = $localPython }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
$Python = (Get-Command $Python -ErrorAction Stop).Source
$version = (& $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $version -ne '3.12') { throw 'Android requires a Python 3.12 build interpreter. Pass -Python.' }
if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin/java.exe'))) {
    throw 'Set JAVA_HOME to JDK 21 or pass -JavaHome.'
}
if (-not $AndroidSdk) { $AndroidSdk = Join-Path $env:LOCALAPPDATA 'Android/Sdk' }
if (-not (Test-Path -LiteralPath (Join-Path $AndroidSdk 'platform-tools/adb.exe'))) { throw 'Android SDK platform-tools not found. Pass -AndroidSdk.' }
$previousJava = $env:JAVA_HOME
$previousSdk = $env:ANDROID_HOME
try {
    $env:JAVA_HOME = $JavaHome
    $env:ANDROID_HOME = $AndroidSdk
    $tasks = @(':app:testDebugUnitTest', ':app:lintDebug', ':app:assembleDebug')
    $options = @("-PplannerBuildPython=$Python", '--console=plain')
    if ($DeviceTests) {
        $devices = @(& (Join-Path $AndroidSdk 'platform-tools/adb.exe') devices | Where-Object { $_ -match '\sdevice$' })
        if ($devices.Count -ne 1) { throw 'Connect exactly one authorized device for this test run.' }
        $tasks += ':app:connectedDebugAndroidTest'
        $options += '-PisolatedDeviceTests=true'
    }
    Push-Location (Join-Path $project 'android-app')
    try {
        & ./gradlew.bat @tasks @options
        if ($LASTEXITCODE -ne 0) { throw "Android verification failed ($LASTEXITCODE)." }
    } finally { Pop-Location }
    Write-Host 'APK: android-app/app/build/outputs/apk/debug/app-debug.apk'
    if ($DeviceTests) { Write-Host 'This APK uses .devtest; run without -DeviceTests to build the user APK.' }
} finally {
    $env:JAVA_HOME = $previousJava
    $env:ANDROID_HOME = $previousSdk
}
