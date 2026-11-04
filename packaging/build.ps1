# 打包脚本：单文件、无控制台、启动即请求管理员权限
# 用法:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Clean]
#
# 注意：本文件必须以 UTF-8 with BOM 保存，而且**只能有一个 BOM**。
# Windows PowerShell 5.1 读无 BOM 的 UTF-8 会按 ANSI(GBK) 解码，
# 中文全部乱码并吃掉字符串引号，报 MissingCatchOrFinally 之类的语法错。
# BOM 叠成两个更隐蔽：多出来的那个被当成 "?"（Where-Object 的别名）执行，
# 报一句 CommandNotFound 之后脚本照跑，看着像没事。
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ExeName = "无音消除助手"
Push-Location $Root
try {
    # exe 正在运行会被独占，PyInstaller 覆盖时只会抛一句 WinError 5
    # 分发包里的 exe 带版本后缀，所以按前缀匹配
    $running = Get-Process -Name "$ExeName*" -ErrorAction SilentlyContinue
    if ($running) {
        $ids = ($running | ForEach-Object { $_.Id }) -join ", "
        throw "请先关闭正在运行的「$ExeName」（进程 $ids），否则无法覆盖 exe"
    }

    # ---- 构建身份 ----------------------------------------------------
    # 版本号写死过一次教训：代码改了好几轮，产物名和标题栏还是 1.0.0，
    # 完全分不清手上的 exe 是新代码还是旧代码。这里把版本 + commit 打进包里。
    Write-Host "==> 记录构建身份" -ForegroundColor Cyan
    $Ver = (& py -3.14 -c "import sys; sys.path.insert(0,'src'); import wuwa_elim; print(wuwa_elim.__version__)")
    if (-not $Ver) { throw "读不到 src\wuwa_elim\__init__.py 里的 __version__" }
    $Ver = $Ver.Trim()
    $PjVer = Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"' |
             ForEach-Object { $_.Matches[0].Groups[1].Value }
    if ($PjVer -ne $Ver) { throw "版本对不上：__version__=$Ver，pyproject.toml=$PjVer" }

    $Commit = (& git rev-parse --short HEAD)
    $Dirty = -not [string]::IsNullOrWhiteSpace((& git status --porcelain 2>$null))
    if (-not $Commit) { $Commit = "nogit" }
    $BuiltAt = Get-Date -Format "yyyy-MM-dd HH:mm"
    $Tag = $Ver + "-" + $Commit + $(if ($Dirty) { "-dirty" } else { "" })

    # 交给 spec 打进包；version.describe() 运行时读它
    $info = [ordered]@{ version = $Ver; commit = $Commit; dirty = $Dirty
                        built_at = $BuiltAt; branch = (& git rev-parse --abbrev-ref HEAD) }
    $infoJson = $info | ConvertTo-Json -Compress
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot "build-info.json"),
                            $infoJson, (New-Object Text.UTF8Encoding $false))
    Write-Host "    本次构建：$Tag" -ForegroundColor Yellow

    if (-not (Test-Path "packaging\app.ico")) {
        Write-Host "==> 生成图标" -ForegroundColor Cyan
        py -3.14 packaging\make_icon.py
    }

    # dist 里只能有这一次的产物：留着上一版的分发包，最容易出现
    # "代码更新了，但发出去的还是旧 exe"。旧包一律先清掉，删不掉就报错。
    Write-Host "==> 清理旧产物" -ForegroundColor Cyan
    if ($Clean -and (Test-Path "build")) {
        Remove-Item -Recurse -Force "build" -ErrorAction Stop
    }
    if (Test-Path "dist") {
        Remove-Item -Recurse -Force "dist" -ErrorAction Stop
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

    # 最后一道闸：产物必须比所有源码新，否则说明打进去的是旧代码
    $stale = Get-ChildItem -Recurse -Include *.py, *.ico, *.spec -Path src, packaging, tests |
             Where-Object { $_.LastWriteTime -gt (Get-Item $exe).LastWriteTime }
    if ($stale) {
        $names = ($stale | ForEach-Object { $_.FullName }) -join "`n      "
        throw "这些文件比刚打出来的 exe 还新，产物不可信：`n      $names"
    }

    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "==> 产物: $exe ($size MB)" -ForegroundColor Green

    $stage = Join-Path $Root "dist\wuwa-elim-$Tag"
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    # 分发文件名也带上身份，别人手里那份旧 zip 一眼就能看出来
    $distExe = Join-Path $stage "无音消除助手-$Tag.exe"
    Copy-Item $exe $distExe
    Copy-Item (Join-Path $Root "README.md") $stage
    Copy-Item (Join-Path $PSScriptRoot "使用说明.txt") $stage
    Copy-Item (Join-Path $PSScriptRoot "build-info.json") $stage

    $zip = Join-Path $Root "dist\wuwa-elim-$Tag-win64.zip"
    Remove-Item $zip -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
    Write-Host "==> 分发包: $zip" -ForegroundColor Green
    Write-Host "==> 运行后标题栏会显示 v$Ver · $Commit$(if ($Dirty) { '-dirty' })" -ForegroundColor Green
}
finally {
    Pop-Location
}
