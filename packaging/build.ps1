# 打包脚本：单文件、无控制台、启动即请求管理员权限
# 用法:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Clean]
#
# 注意：本文件必须以 UTF-8 with BOM 保存。
# Windows PowerShell 5.1 读无 BOM 的 UTF-8 会按 ANSI(GBK) 解码，
# 中文全部乱码并吃掉字符串引号，报 MissingCatchOrFinally 之类的语法错。
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ExeName = "无音消除助手"
Push-Location $Root
try {
    # exe 正在运行会被独占，PyInstaller 覆盖时只会抛一句 WinError 5
    $running = Get-Process -Name $ExeName -ErrorAction SilentlyContinue
    if ($running) {
        $ids = ($running | ForEach-Object { $_.Id }) -join ", "
        throw "请先关闭正在运行的「$ExeName」（进程 $ids），否则无法覆盖 exe"
    }

    if (-not (Test-Path "packaging\app.ico")) {
        Write-Host "==> 生成图标" -ForegroundColor Cyan
        py -3.14 packaging\make_icon.py
    }

    if ($Clean) {
        Write-Host "==> 清理 build/dist" -ForegroundColor Cyan
        Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
    }

    Write-Host "==> 检查依赖" -ForegroundColor Cyan
    py -3.14 -m pip install --quiet --upgrade pyinstaller
    py -3.14 -m pip install --quiet -r requirements.txt

    Write-Host "==> 运行测试" -ForegroundColor Cyan
    py -3.14 tests\test_rules.py
    if ($LASTEXITCODE -ne 0) { throw "规则测试未通过，停止打包" }
    py -3.14 tests\test_solver.py
    if ($LASTEXITCODE -ne 0) { throw "回归测试未通过，停止打包" }
    py -3.14 tests\test_settle.py
    if ($LASTEXITCODE -ne 0) { throw "判稳测试未通过，停止打包" }

    Write-Host "==> PyInstaller 打包" -ForegroundColor Cyan
    py -3.14 -m PyInstaller --noconfirm --clean packaging\wuwa_elim.spec
    if ($LASTEXITCODE -ne 0) { throw "打包失败" }

    $exe = Join-Path $Root "dist\$ExeName.exe"
    if (-not (Test-Path $exe)) { throw "没找到产物: $exe" }
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "==> 产物: $exe ($size MB)" -ForegroundColor Green

    $stage = Join-Path $Root "dist\wuwa-elim-1.0.0"
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Copy-Item $exe $stage
    Copy-Item (Join-Path $Root "README.md") $stage
    Copy-Item (Join-Path $PSScriptRoot "使用说明.txt") $stage

    $zip = Join-Path $Root "dist\wuwa-elim-1.0.0-win64.zip"
    Remove-Item $zip -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
    Write-Host "==> 分发包: $zip" -ForegroundColor Green
}
finally {
    Pop-Location
}
