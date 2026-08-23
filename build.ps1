param(
    [switch]$Console,
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
    throw "找不到 Python。请安装 Python 3.10+，或使用 -Python 指定 python.exe。"
}

$python = Resolve-Python $Python
if (-not (Test-Path (Join-Path $vendor 'PyInstaller'))) {
    throw "未找到本地依赖目录：$vendor。请先运行 .\setup.ps1。"
}

$pythonRoot = (& $python -c "import sys; print(sys.prefix)").Trim()
$tkinterBinary = Join-Path $pythonRoot 'DLLs\_tkinter.pyd'
$tclBinary = Join-Path $pythonRoot 'DLLs\tcl86t.dll'
$tkBinary = Join-Path $pythonRoot 'DLLs\tk86t.dll'
$tclData = Join-Path $pythonRoot 'tcl\tcl8.6'
$tkData = Join-Path $pythonRoot 'tcl\tk8.6'
foreach ($required in @($tkinterBinary, $tclBinary, $tkBinary, $tclData, $tkData)) {
    if (-not (Test-Path $required)) {
        throw "当前 Python 缺少 Tk 运行文件：$required。请安装带 Tcl/Tk 的 Python。"
    }
}

$runner = "import sys, runpy; sys.path.insert(0, r'$vendor'); runpy.run_module('PyInstaller', run_name='__main__')"
$windowMode = if ($Console) { '--console' } else { '--windowed' }
$pyinstallerArgs = @(
    '--noconfirm',
    '--clean',
    $windowMode,
    '--onedir',
    '--name',
    'PokeMMO-Breeder-Helper',
    '--paths',
    $vendor,
    '--additional-hooks-dir',
    (Join-Path $project 'hooks'),
    '--collect-all',
    'rapidocr_onnxruntime',
    '--collect-all',
    'onnxruntime',
    '--collect-all',
    'cv2',
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
    (Join-Path $project 'app.py')
)

& $python -c $runner @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败，退出码：$LASTEXITCODE"
}

Write-Host "Build output: $(Join-Path $project 'dist\PokeMMO-Breeder-Helper')"
