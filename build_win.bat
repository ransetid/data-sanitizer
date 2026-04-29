@echo off
REM ─────────────────────────────────────────────────────────────────
REM Windows 打包脚本
REM 产物：dist\DataSanitizer.exe（单文件）
REM
REM 用法：
REM   cd tools\data-sanitizer
REM   build_win.bat
REM ─────────────────────────────────────────────────────────────────

setlocal
set APP_NAME=DataSanitizer
set VERSION=1.0.0

echo ══════════════════════════════════════════
echo   数据脱敏工具 Windows 打包
echo   产物：dist\%APP_NAME%.exe
echo ══════════════════════════════════════════

REM ── 1. 检查 Python ────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.9+ 并加入 PATH
    pause
    exit /b 1
)

REM ── 2. 安装 PyInstaller ────────────────────────────────────────
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 PyInstaller...
    pip install pyinstaller
)

REM ── 3. 安装依赖 ───────────────────────────────────────────────
echo [1/3] 安装 Python 依赖...
pip install -r requirements.txt --quiet

REM ── 4. 清理 ───────────────────────────────────────────────────
echo [2/3] 清理旧构建...
if exist build rd /s /q build
if exist dist rd /s /q dist

REM ── 5. 打包 ───────────────────────────────────────────────────
echo [3/3] PyInstaller 打包中（可能需要 1-3 分钟）...
python -m PyInstaller DataSanitizer.spec --noconfirm

if not exist "dist\%APP_NAME%.exe" (
    echo [错误] 打包失败，未找到 dist\%APP_NAME%.exe
    pause
    exit /b 1
)

echo.
echo ✅ 打包完成！
echo    EXE：dist\%APP_NAME%.exe
echo.
echo 使用方式：直接双击 DataSanitizer.exe 运行，无需安装 Python
echo 词库文件：首次运行后位于 %%APPDATA%%\DataSanitizer\keywords.txt
pause
