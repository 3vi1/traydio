#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Settings module for traydio.

This module contains the settings dialog and related functionality
for configuring stations, recording options, and other settings.
"""

import os
import copy
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QComboBox, QDialogButtonBox, QGroupBox,
    QFormLayout, QLineEdit, QTextEdit, QMessageBox, QTabWidget, QWidget
)
from PyQt6.QtGui import QIcon, QIntValidator


class SettingsDialog(QDialog):
    """
    Dialog for configuring application settings.
    """
    # Emitted when the user clicks Apply; carries the full updated config
    settings_applied = pyqtSignal(dict)
    
    def __init__(self, config, parent=None):
        """
        Initialize settings dialog.
        
        Args:
            config: Dictionary with current configuration
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Store a copy of the config
        self.config = copy.deepcopy(config)
        
        # Setup UI
        self.setWindowTitle("traydio Settings")
        self.setWindowIcon(QIcon.fromTheme("audio-radio"))
        self.resize(650, 500)
        
        # Create main layout
        self.main_layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # Create tabs
        self.create_stations_tab()
        self.create_recording_tab()
        self.create_buffers_tab()
        self.create_icons_tab()
        
        # Add tabs to tab widget
        self.tab_widget.addTab(self.stations_tab, "Stations")
        self.tab_widget.addTab(self.recording_tab, "Recording")
        self.tab_widget.addTab(self.buffers_tab, "Buffers")
        self.tab_widget.addTab(self.icons_tab, "Icons")

        # Create button box with Apply support
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        # Apply button handling
        self.apply_button = self.button_box.button(QDialogButtonBox.StandardButton.Apply)
        if self.apply_button is not None:
            self.apply_button.setEnabled(False)
            self.apply_button.clicked.connect(self._on_apply_clicked)

        # Add widgets to main layout
        self.main_layout.addWidget(self.tab_widget)
        self.main_layout.addWidget(self.button_box)

        # Baseline for dirty tracking (what's currently applied)
        self._last_applied_config = copy.deepcopy(self.config)
        self._dirty = False
        self._setup_dirty_tracking()
    def create_icons_tab(self):
        """Create and set up the tray icons tab."""
        self.icons_tab = QWidget()
        main_layout = QVBoxLayout(self.icons_tab)
        
        icon_group = QGroupBox("Tray Icons")
        layout = QFormLayout(icon_group)

        # Only two states are used by the app: playing and stopped (paused/stopped share the same state)
        self.icon_states = ["playing", "stopped"]
        self.icon_edits = {}
        self.icon_buttons = {}

        for state in self.icon_states:
            hbox = QHBoxLayout()
            edit = QLineEdit()
            edit.setText(self.config.get(f'tray_icon_{state}', ""))
            button = QPushButton("Browse...")
            button.clicked.connect(lambda _, s=state: self._browse_icon_file(s))
            hbox.addWidget(edit)
            hbox.addWidget(button)
            self.icon_edits[state] = edit
            self.icon_buttons[state] = button

            # Use a friendlier label for the stopped state
            if state == "stopped":
                label_text = "Paused/Stopped Icon (.png):"
            else:
                label_text = "Playing Icon (.png):"

            layout.addRow(label_text, hbox)

        self.reset_icons_button = QPushButton("Reset to Default")
        self.reset_icons_button.clicked.connect(self._reset_icons)
        layout.addRow(self.reset_icons_button)
        
        main_layout.addWidget(icon_group)
        main_layout.addStretch()

    def _browse_icon_file(self, state):
        """Open file dialog to select a .png icon for a given state."""
        # Friendlier title for the stopped state
        title = "Select Paused/Stopped Icon" if state == "stopped" else "Select Playing Icon"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            os.path.expanduser('~'),
            "PNG Files (*.png)"
        )
        if file_path:
            self.icon_edits[state].setText(file_path)

    def _reset_icons(self):
        """Reset all tray icons to default (empty)."""
        for state in self.icon_states:
            self.icon_edits[state].setText("")
        QMessageBox.information(self, "Tray Icons Reset", "Tray icons have been reset to default.")
        self._on_form_changed()
    
    def create_stations_tab(self):
        """Create and set up the stations tab."""
        self.stations_tab = QWidget()
        layout = QVBoxLayout(self.stations_tab)
        
        # Add a label
        label = QLabel("Manage your radio stations:")
        layout.addWidget(label)
        
        # Station list
        self.station_list = QListWidget()
        self.station_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        
        # Populate station list
        self._populate_station_list()
        
        # Buttons for managing stations
        buttons_layout = QHBoxLayout()
        
        self.add_button = QPushButton("Add Station")
        self.edit_button = QPushButton("Edit Station")
        self.remove_button = QPushButton("Remove Station")
        
        self.add_button.clicked.connect(self._add_station)
        self.edit_button.clicked.connect(self._edit_station)
        self.remove_button.clicked.connect(self._remove_station)
        
        buttons_layout.addWidget(self.add_button)
        buttons_layout.addWidget(self.edit_button)
        buttons_layout.addWidget(self.remove_button)
        
        # Add widgets to layout
        layout.addWidget(self.station_list)
        layout.addLayout(buttons_layout)
        layout.addStretch()
    
    def create_recording_tab(self):
        """Create and set up the recording options tab."""
        self.recording_tab = QWidget()
        main_layout = QVBoxLayout(self.recording_tab)
        
        recording_group = QGroupBox("Recording Options")
        layout = QFormLayout(recording_group)
        
        # Recording directory
        self.recording_dir_layout = QHBoxLayout()
        self.recording_dir_edit = QLineEdit()
        self.recording_dir_edit.setText(self.config.get('recording_dir', os.path.expanduser('~/Music')))
        self.recording_dir_button = QPushButton("Browse...")
        self.recording_dir_button.clicked.connect(self._browse_recording_dir)
        
        self.recording_dir_layout.addWidget(self.recording_dir_edit)
        self.recording_dir_layout.addWidget(self.recording_dir_button)
        
        # Recording format
        self.recording_format_combo = QComboBox()
        self.recording_format_combo.addItems(["mp3", "ogg", "flac", "wav"])
        
        # Set current format from config
        current_format = self.config.get('recording_format', 'mp3')
        index = self.recording_format_combo.findText(current_format)
        if index >= 0:
            self.recording_format_combo.setCurrentIndex(index)
        
        # Recording cache limit (MB)
        self.record_cache_limit_edit = QLineEdit(str(self.config.get('record_cache_limit_mb', 100)))
        self.record_cache_limit_edit.setValidator(QIntValidator(1, 100000, self))

        # Notification timeouts
        self.notify_info_timeout_edit = QLineEdit(str(self.config.get('notify_info_timeout_ms', 5000)))
        self.notify_info_timeout_edit.setValidator(QIntValidator(1000, 60000, self))
        self.notify_warning_timeout_edit = QLineEdit(str(self.config.get('notify_warning_timeout_ms', 8000)))
        self.notify_warning_timeout_edit.setValidator(QIntValidator(1000, 60000, self))

        # Add widgets to layout
        layout.addRow("Recording Directory:", self.recording_dir_layout)
        layout.addRow("Recording Format:", self.recording_format_combo)
        layout.addRow("Recording Cache Limit (MB):", self.record_cache_limit_edit)
        layout.addRow("Part Saved Notification (ms):", self.notify_info_timeout_edit)
        layout.addRow("Warning Notification (ms):", self.notify_warning_timeout_edit)
        
        main_layout.addWidget(recording_group)
        main_layout.addStretch()
    
    def create_buffers_tab(self):
        """Create and set up the buffer settings tab."""
        self.buffers_tab = QWidget()
        main_layout = QVBoxLayout(self.buffers_tab)
        layout = QVBoxLayout()
        
        # Get default buffer settings from config
        buffer_settings = self.config.get('buffer_settings', {})
        
        # Playback buffer settings
        self.playback_buffers_edit = QLineEdit(str(buffer_settings.get('playback_buffers', 200)))
        self.playback_bytes_edit = QLineEdit(str(buffer_settings.get('playback_bytes', 2048)))
        self.playback_time_edit = QLineEdit(str(buffer_settings.get('playback_time', 3)))
        
        # Recording buffer settings
        self.recording_buffers_edit = QLineEdit(str(buffer_settings.get('recording_buffers', 500)))
        self.recording_bytes_edit = QLineEdit(str(buffer_settings.get('recording_bytes', 5120)))
        self.recording_time_edit = QLineEdit(str(buffer_settings.get('recording_time', 5)))
        
        # Only allow integer inputs
        for edit in [self.playback_buffers_edit, self.playback_bytes_edit, self.playback_time_edit,
                    self.recording_buffers_edit, self.recording_bytes_edit, self.recording_time_edit]:
            edit.setValidator(QIntValidator(1, 100000, self))
        
        # Add playback settings
        playback_group = QGroupBox("Playback Buffer")
        playback_layout = QFormLayout(playback_group)
        playback_layout.addRow("Max Buffers:", self.playback_buffers_edit)
        playback_layout.addRow("Max Size (KB):", self.playback_bytes_edit)
        playback_layout.addRow("Max Time (seconds):", self.playback_time_edit)
        
        # Add recording settings
        recording_group = QGroupBox("Recording Buffer")
        recording_layout = QFormLayout(recording_group)
        recording_layout.addRow("Max Buffers:", self.recording_buffers_edit)
        recording_layout.addRow("Max Size (KB):", self.recording_bytes_edit)
        recording_layout.addRow("Max Time (seconds):", self.recording_time_edit)
        
        # Add widgets to layout
        layout.addWidget(playback_group)
        layout.addWidget(recording_group)
        
        main_layout.addLayout(layout)
        main_layout.addStretch()
    
    def _populate_station_list(self):
        """Populate the station list from config."""
        self.station_list.clear()
        
        for station in self.config.get('stations', []):
            item = QListWidgetItem(station['name'])
            item.setData(Qt.ItemDataRole.UserRole, station)
            self.station_list.addItem(item)
    
    def _add_station(self):
        """Add a new station."""
        dialog = StationDialog(self)
        if dialog.exec():
            station_data = dialog.get_station_data()
            
            # Add to config and list
            if 'stations' not in self.config:
                self.config['stations'] = []
            
            self.config['stations'].append(station_data)
            
            # Add to list widget
            item = QListWidgetItem(station_data['name'])
            item.setData(Qt.ItemDataRole.UserRole, station_data)
            self.station_list.addItem(item)
            self._on_form_changed()
    
    def _edit_station(self):
        """Edit the selected station."""
        current_item = self.station_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a station to edit.")
            return
        
        # Get the station data
        station_data = current_item.data(Qt.ItemDataRole.UserRole)
        
        # Open dialog with current data
        dialog = StationDialog(self, station_data)
        if dialog.exec():
            updated_data = dialog.get_station_data()
            
            # Update config
            for i, station in enumerate(self.config['stations']):
                if station['name'] == station_data['name']:
                    self.config['stations'][i] = updated_data
                    break
            
            # Update list item
            current_item.setText(updated_data['name'])
            current_item.setData(Qt.ItemDataRole.UserRole, updated_data)
            self._on_form_changed()
    
    def _remove_station(self):
        """Remove the selected station."""
        current_item = self.station_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a station to remove.")
            return
        
        # Get the station data
        station_data = current_item.data(Qt.ItemDataRole.UserRole)
        
        # Confirm removal
        result = QMessageBox.question(
            self, 
            "Confirm Removal",
            f"Are you sure you want to remove the station '{station_data['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if result == QMessageBox.StandardButton.Yes:
            # Remove from config
            self.config['stations'] = [
                s for s in self.config['stations'] 
                if s['name'] != station_data['name']
            ]
            
            # Remove from list
            row = self.station_list.row(current_item)
            self.station_list.takeItem(row)
            self._on_form_changed()
    
    def _browse_recording_dir(self):
        """Open file dialog to select recording directory."""
        current_dir = self.recording_dir_edit.text() or os.path.expanduser('~')
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Recording Directory",
            current_dir
        )
        
        if directory:
            self.recording_dir_edit.setText(directory)
    
    def _collect_config_from_ui(self):
        """
        Build a configuration snapshot from the current UI values without mutating state.
        
        Returns:
            Dictionary with updated configuration
        """
        # Start with a deep copy of the current in-dialog config as base
        cfg = copy.deepcopy(self.config)

        # Update configuration from UI
        
        # Update stations from list order
        stations = []
        for i in range(self.station_list.count()):
            item = self.station_list.item(i)
            station_data = item.data(Qt.ItemDataRole.UserRole)
            stations.append(station_data)
        cfg['stations'] = stations
        
        # Update recording settings
        cfg['recording_dir'] = self.recording_dir_edit.text()
        cfg['recording_format'] = self.recording_format_combo.currentText()
        # Cache limit and notifications
        try:
            cfg['record_cache_limit_mb'] = int(self.record_cache_limit_edit.text())
        except ValueError:
            cfg['record_cache_limit_mb'] = 100
        try:
            cfg['notify_info_timeout_ms'] = int(self.notify_info_timeout_edit.text())
        except ValueError:
            cfg['notify_info_timeout_ms'] = 5000
        try:
            cfg['notify_warning_timeout_ms'] = int(self.notify_warning_timeout_edit.text())
        except ValueError:
            cfg['notify_warning_timeout_ms'] = 8000
        
        # Update buffer settings
        if 'buffer_settings' not in cfg:
            cfg['buffer_settings'] = {}
            
        # Validate and convert buffer settings inputs to integers
        try:
            cfg['buffer_settings']['playback_buffers'] = int(self.playback_buffers_edit.text())
            cfg['buffer_settings']['playback_bytes'] = int(self.playback_bytes_edit.text())
            cfg['buffer_settings']['playback_time'] = int(self.playback_time_edit.text())
            cfg['buffer_settings']['recording_buffers'] = int(self.recording_buffers_edit.text())
            cfg['buffer_settings']['recording_bytes'] = int(self.recording_bytes_edit.text())
            cfg['buffer_settings']['recording_time'] = int(self.recording_time_edit.text())
        except ValueError:
            # If any conversion fails, use default values
            cfg['buffer_settings'] = {
                'playback_buffers': 200,
                'playback_bytes': 2048,
                'playback_time': 3,
                'recording_buffers': 500,
                'recording_bytes': 5120,
                'recording_time': 5
            }

        # Update tray icon paths: only playing and stopped (paused/stopped)
        for state in ["playing", "stopped"]:
            cfg[f'tray_icon_{state}'] = self.icon_edits[state].text().strip()

        # Clean legacy paused key if present
        if "tray_icon_paused" in cfg:
            cfg.pop("tray_icon_paused", None)

        return cfg

    def get_config(self):
        """
        Get the updated configuration and update in-dialog state.
        """
        cfg = self._collect_config_from_ui()
        self.config = copy.deepcopy(cfg)
        return cfg

    def _on_apply_clicked(self):
        """Emit the current configuration and reset dirty baseline."""
        cfg = self._collect_config_from_ui()
        # Emit to the app; dialog stays open
        self.settings_applied.emit(copy.deepcopy(cfg))
        # Reset baseline and disable Apply
        self._last_applied_config = copy.deepcopy(cfg)
        self._dirty = False
        if self.apply_button is not None:
            self.apply_button.setEnabled(False)

    def _on_form_changed(self, *args, **kwargs):
        """Recompute dirty state by comparing UI snapshot to last applied config."""
        try:
            current = self._collect_config_from_ui()
            self._dirty = current != self._last_applied_config
        except Exception:
            # On any error, err on the side of enabling Apply
            self._dirty = True
        if self.apply_button is not None:
            self.apply_button.setEnabled(self._dirty)

    def _setup_dirty_tracking(self):
        """Connect change signals to maintain Apply button enabled state."""
        # Recording group fields
        self.recording_dir_edit.textChanged.connect(self._on_form_changed)
        self.recording_format_combo.currentIndexChanged.connect(self._on_form_changed)
        self.record_cache_limit_edit.textChanged.connect(self._on_form_changed)
        self.notify_info_timeout_edit.textChanged.connect(self._on_form_changed)
        self.notify_warning_timeout_edit.textChanged.connect(self._on_form_changed)

        # Buffer settings fields
        for edit in [
            self.playback_buffers_edit,
            self.playback_bytes_edit,
            self.playback_time_edit,
            self.recording_buffers_edit,
            self.recording_bytes_edit,
            self.recording_time_edit,
        ]:
            edit.textChanged.connect(self._on_form_changed)

        # Tray icon fields
        for edit in self.icon_edits.values():
            edit.textChanged.connect(self._on_form_changed)

        # Stations: mark dirty on add/edit/remove and on reorder
        if self.station_list.model() is not None:
            try:
                self.station_list.model().rowsMoved.connect(self._on_form_changed)
            except Exception:
                pass
        
        return self.config


class StationDialog(QDialog):
    """
    Dialog for adding or editing a radio station.
    """
    
    def __init__(self, parent=None, station_data=None):
        """
        Initialize station dialog.
        
        Args:
            parent: Parent widget
            station_data: Optional data for an existing station
        """
        super().__init__(parent)
        
        self.setWindowTitle("Station Configuration")
        self.resize(400, 300)
        
        # Create layouts
        self.main_layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()
        
        # Create widgets
        self.name_edit = QLineEdit()
        self.urls_edit = QTextEdit()
        self.urls_edit.setPlaceholderText("Enter one URL per line")
        
        # Add widgets to form layout
        self.form_layout.addRow("Station Name:", self.name_edit)
        self.form_layout.addRow("Stream URLs:", self.urls_edit)
        
        # Create button box
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        # Add layouts to main layout
        self.main_layout.addLayout(self.form_layout)
        self.main_layout.addWidget(self.button_box)
        
        # Populate with existing data if provided
        if station_data:
            self.name_edit.setText(station_data['name'])
            self.urls_edit.setText('\n'.join(station_data['urls']))
    
    def accept(self):
        """Validate input before accepting the dialog."""
        name = self.name_edit.text().strip()
        urls_text = self.urls_edit.toPlainText().strip()
        
        if not name:
            QMessageBox.warning(self, "Missing Information", "Please enter a station name.")
            return
        
        if not urls_text:
            QMessageBox.warning(self, "Missing Information", "Please enter at least one stream URL.")
            return
        
        # Split URLs by line and filter out empty ones
        urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        
        if not urls:
            QMessageBox.warning(self, "Invalid URLs", "Please enter valid stream URLs.")
            return
        
        # Check if URLs are valid (basic check)
        for url in urls:
            if not (url.startswith('http://') or url.startswith('https://') or 
                    url.startswith('rtsp://') or url.startswith('mms://') or
                    url.startswith('rtmp://')):
                QMessageBox.warning(
                    self, 
                    "Invalid URL", 
                    f"URL '{url}' is not valid. URLs should start with http://, https://, rtsp://, etc."
                )
                return
        
        super().accept()
    
    def get_station_data(self):
        """
        Get the station data from the dialog.
        
        Returns:
            Dictionary with station data
        """
        name = self.name_edit.text().strip()
        urls_text = self.urls_edit.toPlainText().strip()
        urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        
        return {
            'name': name,
            'urls': urls,
            'current_url_index': 0
        }
