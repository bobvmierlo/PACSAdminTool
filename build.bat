@echo off
echo ============================================
echo  PACS Admin Tool - Build Script
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

echo [1/4] Syncing version info files...
python update_version_info.py
if errorlevel 1 (
    echo ERROR: version sync failed.
    pause
    exit /b 1
)

echo.
echo [2/4] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo.
echo [3/4] Building executable with PyInstaller...
pyinstaller pacs_tool.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Done!
echo.
echo Output: dist\PacsAdminTool.exe
echo.
echo The .exe is fully self-contained - no installation required.
echo Copy dist\PacsAdminTool.exe anywhere and run it directly.
echo.
pause
