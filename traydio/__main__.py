#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point for running traydio as a module with 'python -m traydio'.
"""

import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QSharedMemory
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
    
    # Single instance check
    shared_memory = QSharedMemory("traydio-single-instance")
    if not shared_memory.create(1):
        # Another instance is already running
        QMessageBox.warning(None, "traydio", "Another instance of traydio is already running.")
        sys.exit(1)
    
    # Create and start the app
    tray_app = TraydioApp()
    tray_app.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
