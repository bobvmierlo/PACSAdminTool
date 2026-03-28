# pacs_tool.spec
# PyInstaller spec for PACS Admin Tool
# Build with: pyinstaller pacs_tool.spec

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Collect all pynetdicom and pydicom data/submodules
pynetdicom_datas, pynetdicom_binaries, pynetdicom_hiddenimports = collect_all('pynetdicom')
pydicom_datas, pydicom_binaries, pydicom_hiddenimports = collect_all('pydicom')

all_datas = (
    pynetdicom_datas
    + pydicom_datas
    + [('locales/*.json',       'locales')]
    + [('hl7_templates/*.hl7',  'hl7_templates')]
    + [('icon.png',             '.')]
    + [('icon.ico',             '.')]
)
all_binaries  = pynetdicom_binaries + pydicom_binaries
all_hidden    = (
    pynetdicom_hiddenimports
    + pydicom_hiddenimports
    + collect_submodules('pynetdicom')
    + collect_submodules('pydicom')
    + ['hl7', 'tkinter', 'tkinter.ttk', 'tkinter.messagebox',
       'tkinter.filedialog', 'tkinter.scrolledtext',
       'threading', 'socket', 'json', 'csv', 'logging']
    + collect_submodules('pystray')
    + ['PIL', 'PIL.Image']
)

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'scipy', 'cv2',
              'pandas', 'IPython', 'jupyter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PacsAdminTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # No console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    version='version_info_gui.py',
)
