#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main application module for traydio.

This module contains the core application class that manages the system tray,
audio playback, and settings.
"""

import os
import json
import logging

from PyQt6.QtCore import QObject, Qt, pyqtSignal, QPoint, QTimer
from PyQt6.QtWidgets import (
    QSystemTrayIcon, QMenu, QSlider,
    QLabel, QMessageBox, QApplication, QDialog, QVBoxLayout
)
from PyQt6.QtGui import QIcon, QCursor, QAction, QPixmap

from traydio.audio import StreamPlayer
from traydio.settings import SettingsDialog
from traydio.config import CONFIG_DIR, CONFIG_FILE, DEFAULT_CONFIG, ensure_config

# Module-level logger configured lazily to avoid filesystem issues on import
logger = logging.getLogger(__name__)
LOGGING_CONFIGURED = False


class TraydioApp(QObject):
    """
    Main application class that handles the system tray icon, menu,
    settings management, and audio playback.
    """
    # Signals
    station_changed = pyqtSignal(str)
    metadata_changed = pyqtSignal(dict)
    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    
    def __init__(self):
        """Initialize the application."""
        super().__init__()
        ensure_config()
        self._configure_logging()

        # Load config
        self.config = self._load_config()
        self.current_station = self.config.get('last_station', '')
        self.playing = self.config.get('playing_on_startup', False)

        # Tray icon state
        self.tray_icon_state = "stopped" if not self.playing else "playing"

        # Keep a reference to a modeless volume popup for reuse
        self.volume_popup = None

        # Set up audio player
        self.player = StreamPlayer(self.config)
        self.player.metadata_changed.connect(self._on_metadata_changed)
        self.player.stream_error.connect(self._on_stream_error)
        try:
            self.player.signals.part_flushed.connect(self._on_part_flushed)
            self.player.signals.cache_limit_warning.connect(self._on_cache_limit_warning)
        except Exception:
            pass
        self.player.set_volume(self.config.get('volume', 1.0))

        # Set up system tray icon
        self.setup_tray()

        # Connect signals
        self.station_changed.connect(self._on_station_changed)
        self.metadata_changed.connect(self._update_tooltip_and_notify)

        # Start playback if configured
        if self.playing and self.current_station:
            self._play_station(self.current_station)

    def _get_tray_icon(self, state=None):
        """
        Get QIcon for the given state (playing, stopped/paused) from config, fallback to default.
        """
        if state is None:
            state = self.tray_icon_state
        icon_path = self.config.get(f'tray_icon_{state}', "")
        if icon_path and os.path.isfile(icon_path):
            icon = QIcon(icon_path)
            if not icon.isNull():
                return icon
        # Fallback to default theme icon
        return QIcon.fromTheme("audio-radio")

    def _configure_logging(self):
        """Configure logging handlers once the config directory is available."""
        global LOGGING_CONFIGURED
        if LOGGING_CONFIGURED:
            return

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        log_path = os.path.join(CONFIG_DIR, 'traydio.log')

        try:
            file_handler = logging.FileHandler(log_path, encoding='utf-8')
        except OSError as exc:
            logger.warning("Unable to open log file '%s': %s", log_path, exc)
        else:
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)

        logger.setLevel(logging.INFO)
        LOGGING_CONFIGURED = True
    
    def setup_tray(self):
        """Set up the system tray icon and menu."""
        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(self._get_tray_icon())
        self.tray_icon.setToolTip("traydio")

        self.tray_menu = QMenu()
        self._build_menu()
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _build_menu(self):
        """Build the system tray menu using QAction items compatible with Wayland."""
        # Now playing (disabled text)
        self.now_playing_text_action = QAction("Not playing", self.tray_menu)
        self.now_playing_text_action.setEnabled(False)
        self.tray_menu.addAction(self.now_playing_text_action)

        # Volume controls (status + open popup)
        self.volume_status_action = QAction(self._current_volume_text(), self.tray_menu)
        self.volume_status_action.setEnabled(False)
        self.tray_menu.addAction(self.volume_status_action)

        self.volume_adjust_action = QAction("Adjust Volume…", self.tray_menu)
        self.volume_adjust_action.triggered.connect(self._show_volume_popup)
        self.tray_menu.addAction(self.volume_adjust_action)

        # Record toggle
        self.record_action = QAction("Record", self.tray_menu)
        self.record_action.setCheckable(True)
        self.record_action.setChecked(False)
        self.record_action.toggled.connect(self._on_record_action_toggled)
        self.tray_menu.addAction(self.record_action)

        self.tray_menu.addSeparator()

        # Stations (checkable list)
        self.station_actions = []
        self.station_separator = None

        # Settings and Quit
        self.settings_action = QAction(QIcon.fromTheme("configure"), "Settings", self.tray_menu)
        self.settings_action.triggered.connect(self._show_settings)
        self.tray_menu.addAction(self.settings_action)

        # About (inserted before Quit)
        self.about_action = QAction(QIcon.fromTheme("help-about"), "About", self.tray_menu)
        self.about_action.triggered.connect(self._show_about_dialog)

        self.quit_action = QAction(QIcon.fromTheme("application-exit"), "Quit", self.tray_menu)
        self.quit_action.triggered.connect(self._quit)
        # Insert About before Quit and then add Quit
        self.tray_menu.addAction(self.about_action)
        self.tray_menu.addAction(self.quit_action)

        self._add_station_menu_items()

    def _current_volume_text(self) -> str:
        pct = int(round(self.config.get('volume', 1.0) * 100))
        return f"Volume: {pct}%"
    
    def _add_station_menu_items(self):
        """Add station menu items to the tray menu."""
        # Clear existing station actions
        for action in self.station_actions:
            self.tray_menu.removeAction(action)
        self.station_actions.clear()
        
        # Check if we need to insert before settings or add to end
        settings_index = -1
        
        # Only look for settings_action if it has been defined already
        # (during initial setup, it won't be defined yet)
        if hasattr(self, 'settings_action'):
            for i, action in enumerate(self.tray_menu.actions()):
                if action == self.settings_action:
                    settings_index = i
                    break
                    
        # Determine if we should insert before Settings or add to end
        has_settings = settings_index >= 0
        
        # Remove existing trailing separator if present
        if hasattr(self, 'station_separator') and self.station_separator is not None:
            self.tray_menu.removeAction(self.station_separator)
            self.station_separator = None

        # Add stations from config
        if 'stations' in self.config and self.config['stations']:
            # Add stations before the Settings action to maintain menu structure
            for station in self.config['stations']:
                action = QAction(station['name'], self.tray_menu)
                action.setCheckable(True)
                action.setChecked(station['name'] == self.current_station)
                action.triggered.connect(lambda checked, s=station['name']: self._play_station(s))
                
                if has_settings:
                    # Insert before Settings (which might have a separator before it)
                    self.tray_menu.insertAction(self.settings_action, action)
                else:
                    # Fallback: add to end of menu
                    self.tray_menu.addAction(action)
                
                self.station_actions.append(action)
            
            if has_settings:
                self.station_separator = self.tray_menu.insertSeparator(self.settings_action)
        else:
            self.station_actions = []
    
    def _on_tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, 
                      QSystemTrayIcon.ActivationReason.MiddleClick):
            # Left-click or Middle-click - toggle playback
            if self.playing:
                self._stop_playback()
            else:
                if self.current_station:
                    self._play_station(self.current_station)
                elif 'stations' in self.config and self.config['stations']:
                    # If no current station but stations exist, play first one
                    self._play_station(self.config['stations'][0]['name'])
    
    def _play_station(self, station_name):
        """
        Play the selected radio station.
        
        Args:
            station_name: Name of the station to play
        """
        logger.info(f"Playing station: {station_name}")
        
        # Find station in config
        station_data = None
        for station in self.config.get('stations', []):
            if station['name'] == station_name:
                station_data = station
                break
        
        if not station_data:
            logger.error(f"Station not found: {station_name}")
            return
        
        # Update current station and UI
        self.current_station = station_name
        self._update_station_checked_state()
        
        # Play the station
        self.player.play_station(station_data)
        self.playing = True

        # Update tray icon state and icon
        self.tray_icon_state = "playing"
        self.tray_icon.setIcon(self._get_tray_icon())
        
        # Update now playing label
        if hasattr(self, 'now_playing_text_action'):
            self.now_playing_text_action.setText(f"Loading {station_name}...")
        
        # Save current station to config
        self.config['last_station'] = station_name
        self._save_config()
        
        # Emit signal
        self.station_changed.emit(station_name)
    
    def _stop_playback(self):
        """Stop the current playback."""
        logger.info("Stopping playback")
        self.player.stop()
        self.playing = False
        self.tray_icon_state = "stopped"
        self.tray_icon.setIcon(self._get_tray_icon())
        if hasattr(self, 'now_playing_text_action'):
            self.now_playing_text_action.setText("Not playing")
        
        # Update config
        self.config['playing_on_startup'] = False
        self._save_config()
    
    def _on_station_changed(self, station_name):
        """
        Handle station changed signal.
        
        Args:
            station_name: Name of the new station
        """
        self.current_station = station_name
    
    def _on_metadata_changed(self, metadata):
        """
        Handle metadata changed signal from player.
        
        Args:
            metadata: Dictionary of metadata from stream
        """
        # Update the metadata display
        title = metadata.get('title', '')
        artist = metadata.get('artist', '')
        
        if title:
            if artist:
                display_text = f"{artist} - {title}"
            else:
                display_text = title
            
            if hasattr(self, 'now_playing_text_action'):
                self.now_playing_text_action.setText(display_text)
        else:
            # Fall back to station name if no title
            if hasattr(self, 'now_playing_text_action'):
                self.now_playing_text_action.setText(self.current_station or "Not playing")
        
        # Emit signal
        self.metadata_changed.emit(metadata)
    
    def _update_tooltip_and_notify(self, metadata):
        """
        Update tooltip and send notification.
        
        Args:
            metadata: Dictionary of metadata from stream
        """
        title = metadata.get('title', '')
        artist = metadata.get('artist', '')
        
        # Update tooltip
        if title:
            if artist:
                tooltip = f"{artist} - {title}"
            else:
                tooltip = title
            
            self.tray_icon.setToolTip(tooltip)
        
        # Send notification
        if title and not self.player.same_metadata_as_previous:
            if artist:
                self.tray_icon.showMessage(
                    artist,  # Title
                    title,   # Body
                    QSystemTrayIcon.MessageIcon.Information,
                    5000  # 5 seconds
                )
            else:
                self.tray_icon.showMessage(
                    "Now Playing",
                    title,
                    QSystemTrayIcon.MessageIcon.Information,
                    5000
                )
    
    def _on_volume_changed(self, value):
        """
        Handle volume slider change.
        
        Args:
            value: Integer volume value (0-100)
        """
        volume = value / 100.0
        self.player.set_volume(volume)
        
        # Save to config
        self.config['volume'] = volume
        self._save_config()
        
        # Update menu text if present
        if hasattr(self, 'volume_status_action'):
            self.volume_status_action.setText(self._current_volume_text())
        
        # Sync volume popup slider without causing recursion
        if self.volume_popup is not None and hasattr(self.volume_popup, 'slider'):
            if self.volume_popup.slider.value() != int(value):
                self.volume_popup.slider.blockSignals(True)
                self.volume_popup.slider.setValue(int(value))
                self.volume_popup.slider.blockSignals(False)

    def _show_volume_popup(self):
        """Show a small modeless volume slider popup (Wayland)."""
        if self.volume_popup is None:
            self.volume_popup = QDialog()
            self.volume_popup.setWindowTitle("Volume")
            self.volume_popup.setWindowFlags(
                Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint
            )

            layout = QVBoxLayout(self.volume_popup)
            label = QLabel(self._current_volume_text())
            layout.addWidget(label)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(self.config.get('volume', 1.0) * 100))

            # Timer to auto-close after inactivity
            close_timer = QTimer(self.volume_popup)
            close_timer.setSingleShot(True)
            # Close the popup when timer fires
            close_timer.timeout.connect(self.volume_popup.accept)

            def schedule_close():
                if close_timer.isActive():
                    close_timer.stop()
                close_timer.start(3000)  # 3 seconds

            def cancel_close():
                if close_timer.isActive():
                    close_timer.stop()

            def on_slider(v):
                # Update label and delegate to existing handler
                label.setText(f"Volume: {int(v)}%")
                self._on_volume_changed(int(v))
                # restart auto-close countdown on each change
                schedule_close()

            slider.valueChanged.connect(on_slider)
            # Manage timer around user interaction
            slider.sliderPressed.connect(cancel_close)
            slider.sliderReleased.connect(schedule_close)
            layout.addWidget(slider)

            # keep references for sync & cleanup
            self.volume_popup.slider = slider
            self.volume_popup.label = label
            self.volume_popup.close_timer = close_timer

            def on_closed(_):
                self.volume_popup = None

            self.volume_popup.finished.connect(on_closed)

        # Update current value in case it changed elsewhere
        current_val = int(round(self.config.get('volume', 1.0) * 100))
        if self.volume_popup.slider.value() != current_val:
            self.volume_popup.slider.blockSignals(True)
            self.volume_popup.slider.setValue(current_val)
            self.volume_popup.slider.blockSignals(False)
        self.volume_popup.label.setText(self._current_volume_text())
        # Ensure timer is not running before showing
        if hasattr(self.volume_popup, 'close_timer') and self.volume_popup.close_timer.isActive():
            self.volume_popup.close_timer.stop()

        # Try to show near the cursor; Wayland may ignore the position
        pos = QCursor.pos()
        # Offset a bit so cursor doesn't cover it
        self.volume_popup.move(pos + QPoint(12, 12))
        self.volume_popup.show()
        self.volume_popup.raise_()
        self.volume_popup.activateWindow()

    def _show_about_dialog(self):
        """Show the About dialog with the bundled about.png image.
        Standard framed, fixed-size, centered on the primary screen. Click anywhere to close.
        Modal, but does not interfere with background playback/recording.
        """
        try:
            img_path = os.path.join(os.path.dirname(__file__), "about.png")
            pix = QPixmap(img_path)
            if pix.isNull():
                QMessageBox.information(None, "About traydio", "About image not found.")
                return

            # Scale down if wider than 50% of available screen width
            screen = QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                max_w = int(avail.width() * 0.5)
                if pix.width() > max_w:
                    pix = pix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)

            dialog = QDialog()
            dialog.setWindowTitle("About traydio")
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel()
            label.setPixmap(pix)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)

            # Size to content and make fixed-size
            dialog.adjustSize()
            dialog.setFixedSize(dialog.sizeHint())

            # Click anywhere to close
            def close_on_click(_event):
                dialog.accept()

            dialog.mousePressEvent = close_on_click  # type: ignore[assignment]
            label.mousePressEvent = close_on_click   # type: ignore[assignment]

            # Center on primary screen
            if screen is not None:
                avail = screen.availableGeometry()
                center = avail.center()
                top_left = center - QPoint(dialog.width() // 2, dialog.height() // 2)
                dialog.move(top_left)

            dialog.exec()
        except Exception as exc:
            logger.error("Failed to show About dialog: %s", exc)
    
    def _on_record_action_toggled(self, checked: bool):
        """Handle record toggled via QAction (Wayland-friendly)."""
        if checked:
            recording_dir = self.config.get('recording_dir', os.path.expanduser('~/Music'))
            recording_format = self.config.get('recording_format', 'mp3')
            self.player.start_recording(recording_dir, recording_format)
            self.recording_started.emit(self.current_station)
        else:
            self.player.stop_recording()
            self.recording_stopped.emit(self.current_station)
    
    def _on_stream_error(self, error_type, error_msg, station_name):
        """
        Handle stream errors.
        
        Args:
            error_type: Type of error
            error_msg: Error message
            station_name: Name of the station that failed
        """
        logger.error(f"Stream error for {station_name}: {error_type} - {error_msg}")
        
        # Find the station data
        station_data = None
        for station in self.config.get('stations', []):
            if station['name'] == station_name:
                station_data = station
                break
        
        if station_data:
            # Try next URL for this station if available
            if 'current_url_index' not in station_data:
                station_data['current_url_index'] = 0
            
            if station_data['current_url_index'] < len(station_data['urls']) - 1:
                # Try next URL
                station_data['current_url_index'] += 1
                self.player.play_station(station_data)
                return
        
        # If we get here, all URLs for the current station failed
        # Try the next station in the list
        station_list = self.config.get('stations', [])
        if not station_list:
            self._stop_playback()
            self.tray_icon.showMessage(
                "Error",
                "No stations available",
                QSystemTrayIcon.MessageIcon.Critical,
                5000
            )
            return
        
        # Find the current station index
        current_idx = -1
        for i, station in enumerate(station_list):
            if station['name'] == station_name:
                current_idx = i
                break
        
        if current_idx >= 0:
            # Move to the next station or wrap around
            next_idx = (current_idx + 1) % len(station_list)
            next_station = station_list[next_idx]
            
            # Reset current URL index for failed station
            if station_data:
                station_data['current_url_index'] = 0
            
            # Play next station
            self._play_station(next_station['name'])
            
            # Show notification about station change
            self.tray_icon.showMessage(
                "Station Changed",
                f"Station {station_name} unavailable, switched to {next_station['name']}",
                QSystemTrayIcon.MessageIcon.Warning,
                5000
            )
        else:
            # Something went wrong, stop playback
            self._stop_playback()

    def _on_part_flushed(self, path: str, tags: dict):
        """Notify when a recording part or full track has been saved."""
        timeout = int(self.config.get('notify_info_timeout_ms', 5000))
        title = tags.get('artist') or "Recording Saved"
        body = tags.get('title') or os.path.basename(path)
        try:
            self.tray_icon.showMessage(
                title,
                body,
                QSystemTrayIcon.MessageIcon.Information,
                timeout
            )
        except Exception:
            pass

    def _on_cache_limit_warning(self, message: str):
        """Warn the user when WAV cache limit is approached and recording is auto-stopped."""
        timeout = int(self.config.get('notify_warning_timeout_ms', 8000))
        try:
            self.tray_icon.showMessage(
                "Recording Stopped",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                timeout
            )
        except Exception:
            pass
    
    def _update_station_checked_state(self):
        """Update the checked state of station menu items."""
        for action in self.station_actions:
            action.setChecked(action.text() == self.current_station)
    
    def _show_settings(self):
        """Show the settings dialog."""
        dialog = SettingsDialog(self.config)
        # Apply live while dialog stays open
        dialog.settings_applied.connect(self._apply_settings)
        if dialog.exec():
            # Apply final settings when user presses OK
            self._apply_settings(dialog.get_config())

    def _apply_settings(self, new_config: dict):
        """Apply settings to the running app and persist them. Silent, no dialogs."""
        old_buffer_settings = self.config.get('buffer_settings', {})

        # Clean legacy paused key if present
        new_config.pop("tray_icon_paused", None)

        # Persist
        self.config = new_config
        self._save_config()

        # Update tray icon immediately
        self.tray_icon.setIcon(self._get_tray_icon())

        # Update stations menu to reflect ordering/labels
        self._add_station_menu_items()

        # Update volume
        volume = self.config.get('volume', 1.0)
        if hasattr(self, 'volume_status_action'):
            self.volume_status_action.setText(self._current_volume_text())
        self.player.set_volume(volume)

        # Update buffer settings on the player if changed
        new_buffer_settings = self.config.get('buffer_settings', {})
        if new_buffer_settings != old_buffer_settings:
            self.player.update_buffer_settings(new_buffer_settings)
    
    def _load_config(self) -> dict:
        """
        Load configuration from file.
        
        Returns:
            Dictionary with configuration
        """
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # Migration: if old 'tray_icon_paused' exists and 'stopped' is empty, promote it.
                paused_val = config.get("tray_icon_paused", "")
                stopped_val = config.get("tray_icon_stopped", "")
                if paused_val and not stopped_val:
                    config["tray_icon_stopped"] = paused_val
                if "tray_icon_paused" in config:
                    config.pop("tray_icon_paused", None)
                return config
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()
    
    def _save_config(self):
        """Save configuration to file."""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            try:
                os.chmod(CONFIG_FILE, 0o600)
            except OSError as exc:
                logger.warning("Unable to enforce permissions on config file: %s", exc)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def _quit(self):
        """Quit the application."""
        # Save current state
        self.config['playing_on_startup'] = self.playing
        self._save_config()
        
        # Stop playback and recording
        self.player.stop()
        
        # Quit application
        QApplication.quit()
    
    def show(self):
        """Show the tray icon."""
        self.tray_icon.show()
    