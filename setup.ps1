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
            return $command.Source
        }
        if (Test-Path $requested) {
            return (Resolve-Path $requested).Path
        }
        throw "找不到指定的 Python：$requested"
    }

    foreach ($name in @('py', 'python')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    throw "找不到 Python。请先安装 Python 3.10+。"
}

$python = Resolve-Python $Python
New-Item -ItemType Directory -Path $vendor -Force | Out-Null
& $python -m pip install --upgrade --target $vendor -r (Join-Path $project 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw "依赖安装失败，退出码：$LASTEXITCODE"
}

Write-Host "依赖已安装到：$vendor"
