#!/bin/bash
echo "============================================"
echo " PACS Admin Tool - Build Script"
echo "============================================"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    exit 1
fi

echo "[1/3] Installing dependencies..."
pip3 install -r requirements.txt || { echo "ERROR: pip install failed."; exit 1; }

echo
echo "[2/3] Building with PyInstaller..."
pyinstaller pacs_tool.spec --clean --noconfirm || { echo "ERROR: PyInstaller failed."; exit 1; }

echo
echo "[3/3] Done!"
echo
echo "Output: dist/PacsAdminTool"
echo
echo "The binary is fully self-contained."
echo "On macOS you may need to: xattr -cr dist/PacsAdminTool"
