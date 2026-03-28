# pacs_web.spec
# PyInstaller spec for PACS Admin Tool (Web Server)
# Build with: pyinstaller pacs_web.spec

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect all pynetdicom and pydicom data/submodules
pynetdicom_datas, pynetdicom_binaries, pynetdicom_hiddenimports = collect_all('pynetdicom')
pydicom_datas, pydicom_binaries, pydicom_hiddenimports = collect_all('pydicom')

all_datas = (
    pynetdicom_datas
    + pydicom_datas
    + [('locales/*.json',       'locales')]
    + [('hl7_templates/*.hl7',  'hl7_templates')]
    + [('web/static/*',         'web/static')]
)
all_binaries  = pynetdicom_binaries + pydicom_binaries
all_hidden    = (
    pynetdicom_hiddenimports
    + pydicom_hiddenimports
    + collect_submodules('pynetdicom')
    + collect_submodules('pydicom')
    + ['hl7', 'flask', 'flask_socketio',
       'simple_websocket', 'engineio', 'socketio',
       'threading', 'socket', 'json', 'logging']
)

a = Analysis(
    ['webmain.py'],
    pathex=['.'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'scipy', 'PIL', 'cv2',
              'pandas', 'IPython', 'jupyter',
              'tkinter', 'tkinter.ttk', 'tkinter.messagebox',
              'tkinter.filedialog', 'tkinter.scrolledtext'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PacsAdminToolWeb',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window — runs silently (e.g. Task Scheduler)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico',  # Uncomment and add icon.ico if desired
)
