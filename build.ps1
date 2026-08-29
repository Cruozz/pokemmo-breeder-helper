param(
    [switch]$Console,
    [string]$Python = "",
    [switch]$OneFile,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$vendor = Join-Path $project 'vendor'

function Resolve-Python([string]$requested) {
    if ($requested) {
        $command = Get-Command $requested -ErrorAction SilentlyContinue
        if ($command) {
            $candidate = $command.Source
        } elseif (Test-Path $requested) {
            $candidate = (Resolve-Path $requested).Path
        } else {
            throw "Python executable not found: $requested"
        }
        $version = (& $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        if ($LASTEXITCODE -ne 0 -or $version -notin @('3.10', '3.11', '3.12')) {
            throw "Python $version is incompatible. rapidocr_onnxruntime 1.4.4 requires Python 3.10-3.12."
        }
        return $candidate
    }

    $projectPython = Join-Path $project '.runtime\python312\python.exe'
    if (Test-Path $projectPython) {
        return (Resolve-Path $projectPython).Path
    }

    $launcher = Get-Command 'py' -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($selector in @('-3.12', '-3.11', '-3.10')) {
            try {
            $candidate = (& $launcher.Source $selector -c "import sys; print(sys.executable)" 2>$null)
            } catch {
                continue
            }
            if ($LASTEXITCODE -eq 0 -and $candidate) {
                $candidate = $candidate.Trim()
                $version = (& $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
                if ($LASTEXITCODE -eq 0 -and $version -in @('3.10', '3.11', '3.12')) {
                    return $candidate
                }
            }
        }
    }

    $command = Get-Command 'python' -ErrorAction SilentlyContinue
    if ($command) {
        $version = (& $command.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        if ($LASTEXITCODE -eq 0 -and $version -in @('3.10', '3.11', '3.12')) {
            return $command.Source
        }
    }
    throw "Compatible Python not found. Install Python 3.10-3.12 or pass -Python."
}

$python = Resolve-Python $Python
if (-not (Test-Path (Join-Path $vendor 'PyInstaller'))) {
    throw "Local dependency directory not found: $vendor. Run .\setup.ps1 first."
}

$pythonRoot = (& $python -c "import sys; print(sys.prefix)").Trim()
$tkinterBinary = Join-Path $pythonRoot 'DLLs\_tkinter.pyd'
$tclBinary = Join-Path $pythonRoot 'DLLs\tcl86t.dll'
$tkBinary = Join-Path $pythonRoot 'DLLs\tk86t.dll'
$tclData = Join-Path $pythonRoot 'tcl\tcl8.6'
$tkData = Join-Path $pythonRoot 'tcl\tk8.6'
$speciesData = Join-Path $project 'data'
$uiAssets = Join-Path $project 'assets'
$appIcon = Join-Path $uiAssets 'app-icon.ico'
$versionFile = Join-Path $project 'version_info.txt'
foreach ($required in @($tkinterBinary, $tclBinary, $tkBinary, $tclData, $tkData)) {
    if (-not (Test-Path $required)) {
        throw "The selected Python is missing a Tk runtime file: $required"
    }
}
if (-not (Test-Path $versionFile)) {
    throw "Windows version metadata not found: $versionFile"
}
if (-not (Test-Path $appIcon)) {
    throw "Windows application icon not found: $appIcon"
}

if ($OutputDirectory) {
    if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
        $distPath = $OutputDirectory
    } else {
        $distPath = Join-Path $project $OutputDirectory
    }
} else {
    $distPath = Join-Path $project 'dist'
}
$bundleMode = if ($OneFile) { '--onefile' } else { '--onedir' }
$bundleName = if ($OneFile) { 'Pokemmo孵蛋助手-晨若' } else { 'PokeMMO-Breeder-Helper' }
$workPath = Join-Path $project $(if ($OneFile) { 'build-onefile' } else { 'build' })

$runner = "import sys, runpy; sys.path.insert(0, r'$vendor'); runpy.run_module('PyInstaller', run_name='__main__')"
$windowMode = if ($Console) { '--console' } else { '--windowed' }
$pyinstallerArgs = @(
    '--noconfirm',
    '--clean',
    $windowMode,
    $bundleMode,
    '--name',
    $bundleName,
    '--distpath',
    $distPath,
    '--workpath',
    $workPath,
    '--version-file',
    $versionFile,
    '--icon',
    $appIcon,
    '--paths',
    $vendor,
    '--additional-hooks-dir',
    (Join-Path $project 'hooks'),
    '--collect-all',
    'rapidocr_onnxruntime',
    '--hidden-import',
    'tkinter',
    '--hidden-import',
    'tkinter.ttk',
    '--hidden-import',
    'tkinter.filedialog',
    '--hidden-import',
    'tkinter.messagebox',
    '--hidden-import',
    '_tkinter',
    '--add-binary',
    "${tkinterBinary};.",
    '--add-binary',
    "${tclBinary};.",
    '--add-binary',
    "${tkBinary};.",
    '--add-data',
    "${tclData};tcl\tcl8.6",
    '--add-data',
    "${tkData};tcl\tk8.6",
    '--add-data',
    "${speciesData};data",
    '--add-data',
    "${uiAssets};assets",
    (Join-Path $project 'app.py')
)

& $python -c $runner @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$outputPath = if ($OneFile) {
    Join-Path $distPath "$bundleName.exe"
} else {
    Join-Path $distPath $bundleName
}
Write-Host "Build output: $outputPath"
