#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
traydio - A lightweight internet radio player for Linux KDE Plasma 6

This module initializes the application and launches the main window.
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSlot
try:
    from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
    _QT_DBUS_AVAILABLE = True
except Exception:
    _QT_DBUS_AVAILABLE = False

from traydio.app import TraydioApp


DBUS_SERVICE = "org.traydio.App"
DBUS_PATH = "/org/traydio/App"
DBUS_INTERFACE = "org.traydio.App"


class _DBusController(QObject):
    """Minimal D-Bus controller exposing TogglePlayback."""
    def __init__(self, app_instance: TraydioApp):
        super().__init__()
        self._app = app_instance

    # Exposed as D-Bus method via registerObject ExportAllSlots
    # Name must match exactly for KDE shortcut bindings
    @pyqtSlot()
    def TogglePlayback(self):  # noqa: N802 (DBus method naming is CamelCase)
        if self._app is not None:
            self._app.toggle_playback()


def main():
    """
    Main entry point for the application.
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
                    # Existing instance found: toggle playback then exit
                    iface = QDBusInterface(DBUS_SERVICE, DBUS_PATH, DBUS_INTERFACE, bus)
                    iface.call("TogglePlayback")
                except Exception:
                    # Fall back to a no-op exit if D-Bus call fails
                    pass
                sys.exit(0)
        # else: continue without D-Bus (bus unavailable)

    # Create and start the app
    tray_app = TraydioApp()
    tray_app.show()

    # If QtDBus available, register object to expose TogglePlayback
    if _QT_DBUS_AVAILABLE:
        bus = QDBusConnection.sessionBus()
        if bus.isConnected():
            controller = _DBusController(tray_app)
            try:
                # Prefer overload with explicit interface name
                bus.registerObject(
                    DBUS_PATH,
                    DBUS_INTERFACE,
                    controller,
                    QDBusConnection.RegisterOption.ExportAllSlots,
                )
            except TypeError:
                # Fallback to simpler overload if bindings differ
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
