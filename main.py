"""
PACS Admin Tool - Main Entry Point
A portable DICOM/HL7 workstation for PACS administrators.
"""

import sys
import os

# Ensure bundled resources work correctly with PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

from gui.app import PACSAdminApp

if __name__ == "__main__":
    app = PACSAdminApp()
    app.run()
