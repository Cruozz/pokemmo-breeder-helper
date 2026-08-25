param(
    [string]$Python = ""
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
New-Item -ItemType Directory -Path $vendor -Force | Out-Null
& $python -m pip install --upgrade --target $vendor -r (Join-Path $project 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE"
}

Write-Host "Dependencies installed to: $vendor"
