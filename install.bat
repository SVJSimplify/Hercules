@echo off
REM Hercules v8.2.0 Installer - Windows

setlocal enabledelayedexpansion

cls
echo.
echo ╔════════════════════════════════════════╗
echo ║  Hercules v8.2.0 Installer             ║
echo ║  Hierarchical AI Agent System           ║
echo ╚════════════════════════════════════════╝
echo.

REM Check/Install Python
echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   Python not found. Installing...
    echo.
    echo Choose installation method:
    echo   1. Download from python.org (manual)
    echo   2. Try to install via winget (Windows 10+)
    echo.
    set /p PYTHON_CHOICE="Enter choice (1 or 2): "
    
    if "!PYTHON_CHOICE!"=="2" (
        echo Installing Python via winget...
        winget install -e --id Python.Python.3.11
        if errorlevel 1 (
            echo ✗ winget install failed
            echo Download from: https://python.org
            pause
            exit /b 1
        )
    ) else (
        echo Download from: https://python.org/downloads/
        echo - Select Python 3.11 or later
        echo - Check "Add Python to PATH"
        echo Then re-run this installer
        pause
        exit /b 1
    )
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✓ Found Python !PYTHON_VERSION!
echo.

REM Create directories
echo Creating directories...
if not exist "%USERPROFILE%\.hercules" mkdir "%USERPROFILE%\.hercules"
if not exist "%USERPROFILE%\.hercules\cache" mkdir "%USERPROFILE%\.hercules\cache"
if not exist "%USERPROFILE%\.hercules\plugins" mkdir "%USERPROFILE%\.hercules\plugins"
if not exist "%USERPROFILE%\.hercules\conversations" mkdir "%USERPROFILE%\.hercules\conversations"
echo ✓ Created %USERPROFILE%\.hercules
echo.

REM Install dependencies
echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install gpt4all colorama psutil
echo ✓ Dependencies installed
echo.

REM Create models directory
echo Setting up models directory...
if not exist "%USERPROFILE%\Models" mkdir "%USERPROFILE%\Models"
echo ✓ Created %USERPROFILE%\Models
echo   Download GGUF models to: %%USERPROFILE%%\Models
echo.

REM Create config
echo Creating config...
if not exist "%USERPROFILE%\.hercules\config.json" (
    (
        echo {
        echo   "model_dir": "D:\\Models",
        echo   "auto_save": true,
        echo   "auto_save_interval": 10,
        echo   "theme": "dark",
        echo   "verbose": false,
        echo   "context_window_size": 10,
        echo   "cache_responses": false,
        echo   "default_temp": 0.7,
        echo   "default_tokens": 256
        echo }
    ) > "%USERPROFILE%\.hercules\config.json"
    echo ✓ Created config at %%USERPROFILE%%\.hercules\config.json
)
echo.

REM Create launcher
echo Creating launcher...
(
    echo @echo off
    echo cd /d "%%~dp0"
    echo python hercules.py %%*
) > "%USERPROFILE%\Desktop\Hercules.bat"
echo ✓ Created launcher at %%USERPROFILE%%\Desktop\Hercules.bat
echo.

REM Completion
cls
echo.
echo ╔════════════════════════════════════════╗
echo ║  Installation Complete!                ║
echo ╚════════════════════════════════════════╝
echo.
echo Next steps:
echo   1. Download GGUF models to: %%USERPROFILE%%\Models
echo      From: https://huggingface.co/TheBloke
echo.
echo   2. Run Hercules:
echo      python hercules.py
echo      OR click: %%USERPROFILE%%\Desktop\Hercules.bat
echo.
echo   3. Configure:
echo      Edit: %%USERPROFILE%%\.hercules\config.json
echo.
echo Useful commands:
echo   /help      - Show all commands
echo   /setup     - Select model
echo   /hagent    - 3-layer agent hierarchy
echo   /code      - Claude Code patterns
echo.
echo Documentation:
echo   README.md - Overview
echo   SUBAGENTS_GGUF_GUIDE.md - Detailed guide
echo.
pause
