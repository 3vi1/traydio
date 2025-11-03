#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration module for traydio.

This module handles configuration file management, provides default settings,
and ensures the configuration directory exists.
"""

import os
import json
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Configuration constants
CONFIG_DIR = os.path.expanduser("~/.config/traydio")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Default configuration
DEFAULT_CONFIG = {
    "stations": [
        {
            "current_url_index": 0,
            "name": "Slay Radio",
            "urls": [
                "http://relay1.slayradio.com:8000",
                "http://relay2.slayradio.com:8000",
                "http://relay3.slayradio.com:8000"
            ]
        },
        {
            "current_url_index": 0,
            "name": "Space Station",
            "urls": [
                "https://ice1.somafm.com/spacestation-128-aac",
                "https://ice2.somafm.com/spacestation-128-aac"
            ]
        },
        {
            "current_url_index": 0,
            "name": "Lush",
            "urls": [
                "https://ice1.somafm.com/lush-128-aac",
                "https://ice2.somafm.com/lush-128-aac"
            ]
        },
        {
            "current_url_index": 0,
            "name": "Secret Agent",
            "urls": [
                "https://ice1.somafm.com/secretagent-128-aac",
                "https://ice2.somafm.com/secretagent-128-aac"
            ]
        }
    ],
    "volume": 0.8,
    "recording_dir": os.path.expanduser("~/Music"),
    "recording_format": "mp3",
    "last_station": "",
    "playing_on_startup": False,
    "buffer_settings": {
        "playback_buffers": 200,
        "playback_bytes": 2048,  # KB (2MB)
        "playback_time": 3,      # seconds
        "recording_buffers": 500,
        "recording_bytes": 5120,  # KB (5MB)
        "recording_time": 5       # seconds
    },
    # Recording RAM cache limit (in MB) for appsink-based recording
    "record_cache_limit_mb": 100,
    # Notification timeouts (ms)
    "notify_info_timeout_ms": 5000,
    "notify_warning_timeout_ms": 8000,
    # Tray icon paths (empty means use default)
    "tray_icon_playing": "",
    "tray_icon_stopped": ""
}

# Note: Custom tray icon paths are now used directly as provided by the user.
# No copy/remove helpers are needed; if a selected icon is moved or deleted,
# the app will fall back to the theme icon at runtime.


def ensure_config():
    """
    Ensure the configuration directory and file exist.
    Creates them with default values if they don't.
    """
    # Create config directory with user-only permissions
    try:
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create configuration directory: {e}")
        return False

    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError as e:
        logger.warning(f"Unable to enforce permissions on config directory: {e}")
    
    # Create default config file if it doesn't exist
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            os.chmod(CONFIG_FILE, 0o600)
            logger.info(f"Created default configuration file: {CONFIG_FILE}")
        except OSError as e:
            logger.error(f"Failed to create configuration file: {e}")
            return False
    
    return True
