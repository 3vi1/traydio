#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point for running traydio as a module with 'python -m traydio'.
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSlot
try:
    from PyQt6.QtDBus import QDBusConnection, QDBusInterface
    _QT_DBUS_AVAILABLE = True
except Exception:
    _QT_DBUS_AVAILABLE = False
from traydio.app import TraydioApp

DBUS_SERVICE = "org.traydio.App"
DBUS_PATH = "/org/traydio/App"
DBUS_INTERFACE = "org.traydio.App"


class _DBusController(QObject):
    def __init__(self, app_instance: TraydioApp):
        super().__init__()
        self._app = app_instance

    @pyqtSlot()
    def TogglePlayback(self):  # noqa: N802
        if self._app is not None:
            self._app.toggle_playback()


def main():
    """
    Main entry point for the application when run as a module.
    Initializes and runs the application.
    """
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Allow app to run when no windows are shown
    app.setApplicationName("traydio")
    app.setApplicationDisplayName("traydio")

    # D-Bus single-instance: if service already owned, send TogglePlayback and exit
    if _QT_DBUS_AVAILABLE:
        bus = QDBusConnection.sessionBus()
        if bus.isConnected():
            if not bus.registerService(DBUS_SERVICE):
                try:
                    iface = QDBusInterface(DBUS_SERVICE, DBUS_PATH, DBUS_INTERFACE, bus)
                    iface.call("TogglePlayback")
                except Exception:
                    pass
                sys.exit(0)
    
    # Create and start the app
    tray_app = TraydioApp()
    tray_app.show()
    
    # Register D-Bus object if available
    if _QT_DBUS_AVAILABLE:
        bus = QDBusConnection.sessionBus()
        if bus.isConnected():
            controller = _DBusController(tray_app)
            try:
                bus.registerObject(
                    DBUS_PATH,
                    DBUS_INTERFACE,
                    controller,
                    QDBusConnection.RegisterOption.ExportAllSlots,
                )
            except TypeError:
                bus.registerObject(
                    DBUS_PATH,
                    controller,
                    QDBusConnection.RegisterOption.ExportAllSlots,
                )

            def _cleanup_dbus():
                try:
                    bus.unregisterObject(DBUS_PATH)
                except Exception:
                    pass
                try:
                    bus.unregisterService(DBUS_SERVICE)
                except Exception:
                    pass

            app.aboutToQuit.connect(_cleanup_dbus)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
