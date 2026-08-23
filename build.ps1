param(
    [switch]$Console
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\Chenruo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonRoot = Split-Path -Parent $python
$vendor = Join-Path $project 'vendor'

if (-not (Test-Path $python)) {
    throw "找不到 Python：$python"
}

$runner = "import sys, runpy; sys.path.insert(0, r'$vendor'); runpy.run_module('PyInstaller', run_name='__main__')"
$windowMode = if ($Console) { '--console' } else { '--windowed' }
& $python -c $runner `
    --noconfirm `
    --clean `
    $windowMode `
    --onedir `
    --name 'PokeMMO-Breeder-Helper' `
    --paths (Join-Path $project 'vendor') `
    --additional-hooks-dir (Join-Path $project 'hooks') `
    --collect-all rapidocr_onnxruntime `
    --collect-all onnxruntime `
    --collect-all cv2 `
    --hidden-import tkinter `
    --hidden-import tkinter.ttk `
    --hidden-import tkinter.filedialog `
    --hidden-import tkinter.messagebox `
    --hidden-import _tkinter `
    --add-binary "$(Join-Path $pythonRoot 'DLLs\_tkinter.pyd');." `
    --add-binary "$(Join-Path $pythonRoot 'DLLs\tcl86t.dll');." `
    --add-binary "$(Join-Path $pythonRoot 'DLLs\tk86t.dll');." `
    --add-data "$(Join-Path $pythonRoot 'tcl\tcl8.6');tcl\tcl8.6" `
    --add-data "$(Join-Path $pythonRoot 'tcl\tk8.6');tcl\tk8.6" `
    (Join-Path $project 'app.py')

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败，退出码：$LASTEXITCODE"
}

Write-Host "Build output: $(Join-Path $project 'dist\PokeMMO-Breeder-Helper')"
