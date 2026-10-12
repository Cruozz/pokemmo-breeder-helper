param([string]$Python = '', [string]$OutputDirectory, [string]$Version)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid cached-runtime version.' }
$payloadRoot = Join-Path $project ".runtime/cached-payload/V$Version"
$buildArgs = @{ OutputDirectory = $payloadRoot }
if ($Python) { $buildArgs.Python = $Python }
& (Join-Path $project 'build.ps1') @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'Core runtime build failed.' }
$bundle = Join-Path $payloadRoot 'PokeMMO-Breeder-Helper'
foreach ($document in @('THIRD_PARTY_NOTICES.md', 'DISTRIBUTION_README.txt')) {
    Copy-Item -LiteralPath (Join-Path $project $document) -Destination (Join-Path $bundle "_internal/$document") -Force
}
$payload = Join-Path $payloadRoot 'runtime.zip'
if (Test-Path -LiteralPath $payload) { Remove-Item -LiteralPath $payload -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($bundle, $payload, [System.IO.Compression.CompressionLevel]::Optimal, $false)
$payloadHash = (Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant()
$coreHash = (Get-FileHash -LiteralPath (Join-Path $bundle 'PokeMMO-Breeder-Helper.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
$source = Get-Content -LiteralPath (Join-Path $project 'desktop-launcher/Program.cs') -Raw -Encoding UTF8
$source = $source.Replace('__VERSION__', $Version).Replace('__PAYLOAD_HASH__', $payloadHash).Replace('__CORE_HASH__', $coreHash)
$generated = Join-Path $payloadRoot 'Launcher.cs'
[System.IO.File]::WriteAllText($generated, $source, [System.Text.UTF8Encoding]::new($false))
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'The Windows .NET Framework compiler is required.' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$launcher = Join-Path $OutputDirectory 'Pokemmo孵蛋助手.exe'
& $compiler '/nologo' '/target:winexe' '/platform:x64' '/optimize+' '/utf8output' "/out:$launcher" "/win32icon:$(Join-Path $project 'assets/app-icon.ico')" "/resource:$payload,RuntimePayload" '/reference:System.dll' '/reference:System.Core.dll' '/reference:System.Windows.Forms.dll' '/reference:System.Drawing.dll' '/reference:System.IO.Compression.dll' '/reference:System.IO.Compression.FileSystem.dll' $generated
if ($LASTEXITCODE -ne 0) { throw 'Single EXE launcher build failed.' }
Write-Host "Cached-runtime executable: $launcher"
