#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
traydio - A lightweight internet radio player for Linux KDE Plasma 6

This module initializes the application and launches the main window.
"""

import sys
from PyQt6.QtWidgets import QApplication

from traydio.app import TraydioApp


def main():
    """
    Main entry point for the application.
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
