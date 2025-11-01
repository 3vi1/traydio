#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point for running traydio as a module with 'python -m traydio'.
"""

import sys
from PyQt6.QtWidgets import QApplication
from traydio.app import TraydioApp


def main():
    """
    Main entry point for the application when run as a module.
    Initializes and runs the application.
    """
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Allow app to run when no windows are shown
    app.setApplicationName("traydio")
    app.setApplicationDisplayName("traydio")
    
    # Create and start the app
    tray_app = TraydioApp()
    tray_app.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
