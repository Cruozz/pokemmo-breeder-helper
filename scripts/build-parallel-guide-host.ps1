# Builds the small child-window host; the offline site is packaged separately by PyInstaller.
param([string]$OutputDirectory = "")
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$output = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $project '.runtime/parallel-guide-host' }
$sdkVersion = '1.0.4258.31'
$sdkHash = '56F7F4B8BF9AEE4B8EFEFBBDD4F67D5F74EBD1B100ED0806DA71BF76AF481AA9'
$sdkZip = Join-Path $project ".runtime/webview2-$sdkVersion.zip"
$sdk = Join-Path $project ".runtime/webview2-$sdkVersion"
New-Item -ItemType Directory -Path $output -Force | Out-Null
if (-not (Test-Path -LiteralPath $sdkZip)) {
    Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$sdkVersion/microsoft.web.webview2.$sdkVersion.nupkg" -OutFile $sdkZip
}
if ((Get-FileHash -LiteralPath $sdkZip -Algorithm SHA256).Hash -ne $sdkHash) { throw 'WebView2 SDK SHA-256 mismatch.' }
if (-not (Test-Path -LiteralPath (Join-Path $sdk 'lib/net462/Microsoft.Web.WebView2.Core.dll'))) {
    Expand-Archive -LiteralPath $sdkZip -DestinationPath $sdk -Force
}
$loader = Join-Path $sdk 'runtimes/win-x64/native/WebView2Loader.dll'
$signature = Get-AuthenticodeSignature -LiteralPath $loader
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'WebView2 Microsoft signature verification failed.' }
foreach ($name in @('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll')) {
    Copy-Item -LiteralPath (Join-Path $sdk "lib/net462/$name") -Destination $output -Force
}
Copy-Item -LiteralPath $loader -Destination $output -Force
foreach ($name in @('LICENSE.txt', 'NOTICE.txt')) {
    Copy-Item -LiteralPath (Join-Path $sdk $name) -Destination (Join-Path $output "WebView2-$name") -Force
}
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework C# compiler is required.' }
$compileArgs = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/utf8output',
    "/out:$(Join-Path $output 'ParallelGuideHost.exe')", '/reference:System.dll', '/reference:System.Core.dll',
    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
    "/reference:$(Join-Path $output 'Microsoft.Web.WebView2.Core.dll')", "/reference:$(Join-Path $output 'Microsoft.Web.WebView2.WinForms.dll')",
    (Join-Path $project 'desktop-guide/Program.cs'))
& $compiler @compileArgs
if ($LASTEXITCODE -ne 0) { throw 'Guide host compilation failed.' }
Write-Host "Guide host: $output"
