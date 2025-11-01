#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audio playback module for traydio.

This module contains the StreamPlayer class that handles audio streaming,
metadata extraction, and recording functionality using GStreamer.
"""

import os
import logging
import datetime
import threading
from io import BytesIO

import gi

# Import PyQt6
from PyQt6.QtCore import pyqtSignal, QObject

# Import GStreamer
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

# Initialize GStreamer
Gst.init(None)

# Set up logging
logger = logging.getLogger(__name__)


class StreamPlayer:
    """
    Audio streaming and recording handler using GStreamer.
    """
    
    class Signals(QObject):
        metadata_changed = pyqtSignal(dict)
        stream_error = pyqtSignal(str, str, str)  # error_type, error_msg, station_name
        part_flushed = pyqtSignal(str, dict)  # filepath, tags used
        cache_limit_warning = pyqtSignal(str)  # human message
    
    def __init__(self, config=None):
        """
        Initialize the stream player.
        
        Args:
            config: Optional application configuration dictionary
        """
        self.signals = self.Signals()
        self.metadata_changed = self.signals.metadata_changed
        self.stream_error = self.signals.stream_error
        
        # Store configuration
        self.config = config or {}
        
        # Current stream info
        self.current_station = {}
        self.current_metadata = {}
        self.previous_metadata = {}
        self.same_metadata_as_previous = False
        
        # Recording-related variables
        self.is_recording = False
        self.record_pipeline = None  # unused with appsink path, kept for compatibility
        self.recording_filename = None  # last written file path
        self.recording_dir = None
        self.recording_format = None
        self.tee = None
        self.record_bin = None
        self.tee_recording_pad = None

        # Appsink RAM cache for encoded data
        self._appsink = None
        self._encoded_chunks = []  # list[bytes]
        self._encoded_size = 0
        self._encoded_lock = threading.Lock()
        self._record_part_index = 1  # resets to 1 each recording session, continuous across tracks
        self._record_cache_limit_bytes = 100 * 1024 * 1024  # default; overridden by config
        self._wav_autostop_threshold_bytes = int(self._record_cache_limit_bytes * 0.95)
        
        # Create the playback pipeline
        self._setup_playback_pipeline()
    
    def _setup_playback_pipeline(self):
        """Set up the GStreamer playback pipeline."""
        # Create pipeline for playback
        self.pipeline = Gst.Pipeline.new("player")
        
        # Create elements
        self.source = Gst.ElementFactory.make("uridecodebin", "source")
        self.convert = Gst.ElementFactory.make("audioconvert", "convert")
        self.resample = Gst.ElementFactory.make("audioresample", "resample")
        
        # Create a tee element to allow for recording branch
        self.tee = Gst.ElementFactory.make("tee", "tee")
        
        # Create a queue for the playback branch
        self.play_queue = Gst.ElementFactory.make("queue", "play_queue")
        
        # Configure playback queue buffer size from settings
        buffer_settings = self.config.get('buffer_settings', {})
        # Get playback buffer settings with defaults if not specified
        pb_buffers = buffer_settings.get('playback_buffers', 200)
        pb_bytes = buffer_settings.get('playback_bytes', 2048) * 1024  # Convert KB to bytes
        pb_time = buffer_settings.get('playback_time', 3) * Gst.SECOND
        
        # Apply buffer settings
        self.play_queue.set_property("max-size-buffers", pb_buffers)
        self.play_queue.set_property("max-size-bytes", pb_bytes)
        self.play_queue.set_property("max-size-time", pb_time)
        
        # Place volume control after the tee in the playback branch only
        self.volume = Gst.ElementFactory.make("volume", "volume")
        
        self.sink = Gst.ElementFactory.make("autoaudiosink", "sink")
        
        # Check if all elements were created successfully
        if (not self.pipeline or not self.source or not self.convert or
                not self.resample or not self.tee or not self.play_queue or
                not self.volume or not self.sink):
            logger.error("Failed to create GStreamer elements")
            return
        
        # Add elements to pipeline
        self.pipeline.add(self.source)
        self.pipeline.add(self.convert)
        self.pipeline.add(self.resample)
        self.pipeline.add(self.tee)
        self.pipeline.add(self.play_queue)
        self.pipeline.add(self.volume)
        self.pipeline.add(self.sink)
        
        # Link elements that can be linked statically
        self.convert.link(self.resample)
        self.resample.link(self.tee)
        
        # Link tee to playback branch with volume control
        self.tee.link(self.play_queue)
        self.play_queue.link(self.volume)
        self.volume.link(self.sink)
        
        # Connect pad-added signal for dynamic linking
        self.source.connect("pad-added", self._on_pad_added)
        
        # Connect callbacks for bus messages
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        
        # Set initial volume
        self.volume.set_property("volume", 1.0)
    
    def _on_pad_added(self, element, pad):
        """
        Callback function for pad-added signal.
        Links dynamic source pad to the next element when it becomes available.
        """
        sink_pad = self.convert.get_static_pad("sink")
        
        # Check if pad is already linked
        if sink_pad.is_linked():
            return
        
        # Check if pad is audio
        pad_caps = pad.get_current_caps()
        if not pad_caps:
            return
        
        pad_struct = pad_caps.get_structure(0)
        if not pad_struct:
            return
        
        if pad_struct.get_name().startswith("audio/"):
            # Link the pads
            if pad.link(sink_pad) != Gst.PadLinkReturn.OK:
                logger.error("Failed to link pads")
    
    def _on_bus_message(self, bus, message):
        """
        Handle GStreamer bus messages.
        """
        message_type = message.type
        
        if message_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"GStreamer error: {err}, {debug}")
            
            # Emit signal with error info
            error_type = "stream_error"
            error_msg = str(err)
            station_name = self.current_station.get('name', '')
            self.stream_error.emit(error_type, error_msg, station_name)
        
        elif message_type == Gst.MessageType.EOS:
            logger.info("End of stream")
            # For internet radio, this shouldn't happen under normal conditions
            # Emit signal to try next URL
            self.stream_error.emit(
                "eos",
                "End of stream",
                self.current_station.get('name', '')
            )
        
        elif message_type == Gst.MessageType.TAG:
            # Extract metadata from tags
            tag_list = message.parse_tag()
            metadata = {}
            
            # Get title
            success, title = tag_list.get_string("title")
            if success and title:
                metadata['title'] = title
            
            # Get artist
            success, artist = tag_list.get_string("artist")
            if success and artist:
                metadata['artist'] = artist
            
            # Get album
            success, album = tag_list.get_string("album")
            if success and album:
                metadata['album'] = album
            
            # Get genre
            success, genre = tag_list.get_string("genre")
            if success and genre:
                metadata['genre'] = genre
            
            # Get image/artwork
            success, sample = tag_list.get_sample("image")
            if success and sample:
                # TODO: Handle image data
                metadata['has_image'] = True
            
            # Only emit signal if metadata has changed or contains new information
            if metadata and metadata != self.current_metadata:
                # Check if just the same data repeated
                same_data = True
                for key, value in metadata.items():
                    if key not in self.current_metadata or self.current_metadata[key] != value:
                        same_data = False
                        break
                
                if not same_data:
                    self.previous_metadata = self.current_metadata.copy()
                    self.current_metadata = metadata
                    self.same_metadata_as_previous = (
                        'title' in self.previous_metadata and 
                        'title' in self.current_metadata and
                        self.previous_metadata['title'] == self.current_metadata['title']
                    )
                    
                    # Emit signal with new metadata
                    self.metadata_changed.emit(metadata)
                    
                    # If recording, check if we need to start a new recording file
                    if self.is_recording and not self.same_metadata_as_previous and 'title' in metadata:
                        self._rotate_recording_file()
        
        elif message_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old_state, new_state, pending_state = message.parse_state_changed()
                logger.debug(f"Pipeline state changed from {old_state} to {new_state}, pending: {pending_state}")
    
    def play_station(self, station_data):
        """
        Play a radio station.
        
        Args:
            station_data: Dictionary with station information
        """
        # Stop any current playback
        self.pipeline.set_state(Gst.State.NULL)
        
        # Clear current metadata
        self.current_metadata = {}
        self.previous_metadata = {}
        self.same_metadata_as_previous = False
        
        # Store current station info
        self.current_station = station_data
        
        # Get the URL to play
        current_index = station_data.get('current_url_index', 0)
        if current_index >= len(station_data['urls']):
            current_index = 0
            station_data['current_url_index'] = 0
        
        url = station_data['urls'][current_index]
        logger.info(f"Playing URL: {url}")
        
        # Set the URI and start playing
        self.source.set_property("uri", url)
        self.pipeline.set_state(Gst.State.PLAYING)
        
        # If recording was active, restart it
        if self.is_recording:
            self.stop_recording()
            self.start_recording(self.recording_dir, self.recording_format)
    
    def stop(self):
        """Stop playback."""
        # Stop recording if active
        if self.is_recording:
            self.stop_recording()
        
        # Stop the pipeline
        self.pipeline.set_state(Gst.State.NULL)
        
        # Clear current metadata
        self.current_metadata = {}
        self.previous_metadata = {}
    
    def set_volume(self, volume):
        """
        Set playback volume.
        
        Args:
            volume: Float value from 0.0 to 1.0
        """
        self.volume.set_property("volume", volume)
    
    def update_buffer_settings(self, buffer_settings):
        """
        Update buffer size settings dynamically.
        
        Args:
            buffer_settings: Dictionary with buffer settings
        """
        # Update config
        if 'buffer_settings' not in self.config:
            self.config['buffer_settings'] = {}
        self.config['buffer_settings'] = buffer_settings
        
        # Update playback buffer settings
        if self.play_queue:
            # Get playback buffer settings with defaults if not specified
            pb_buffers = buffer_settings.get('playback_buffers', 200)
            pb_bytes = buffer_settings.get('playback_bytes', 2048) * 1024  # Convert KB to bytes
            pb_time = buffer_settings.get('playback_time', 3) * Gst.SECOND
            
            # Apply to playback queue
            self.play_queue.set_property("max-size-buffers", pb_buffers)
            self.play_queue.set_property("max-size-bytes", pb_bytes)
            self.play_queue.set_property("max-size-time", pb_time)
            
            logger.info(f"Updated playback buffer settings: buffers={pb_buffers}, bytes={pb_bytes}, time={pb_time/Gst.SECOND}s")
        
        # Note: Recording buffer settings will be applied the next time recording starts
        logger.info("Buffer settings updated")
    
    def start_recording(self, recording_dir, format_name="mp3"):
        """
        Start recording the current stream.
        
        Args:
            recording_dir: Directory to save recordings
            format_name: Format to use for recording (mp3, ogg, etc.)
        """
        if self.is_recording:
            self.stop_recording(auto_rotation=False)
        
        # Store recording settings
        self.recording_dir = recording_dir
        self.recording_format = format_name
        
        # Set recording flag
        self.is_recording = True
        # Reset RAM cache and part numbering
        with self._encoded_lock:
            self._encoded_chunks = []
            self._encoded_size = 0
        self._record_part_index = 1

        # Read cache limit from config
        cache_mb = None
        try:
            cache_mb = int(self.config.get('record_cache_limit_mb', 100))
        except Exception:
            cache_mb = 100
        self._record_cache_limit_bytes = max(1, cache_mb) * 1024 * 1024
        self._wav_autostop_threshold_bytes = int(self._record_cache_limit_bytes * 95 / 100)
        
        # Create recording pipeline that taps into the main pipeline
        self._setup_recording_pipeline()
    
    def stop_recording(self, auto_rotation=False):
        """
        Stop recording.
        
        Args:
            auto_rotation: Whether this is an automatic rotation due to track change (True)
                           or a manual stop by the user (False)
        """
        if not self.is_recording:
            return
        
        # Set flag
        self.is_recording = False
        
        # Flush remaining buffer to a final file
        try:
            if self._encoded_size > 0:
                # For manual stop, we keep " - partial" suffix by renaming after write
                path = self._flush_current_part(track_metadata=self.current_metadata, is_final_stop=True)
                if path and (not auto_rotation):
                    base, ext = os.path.splitext(path)
                    if not base.endswith("- partial"):
                        new_path = f"{base} - partial{ext}"
                        try:
                            os.replace(path, new_path)
                            self.recording_filename = new_path
                        except Exception as e:
                            logger.error(f"Error renaming partial recording: {e}")
                else:
                    # update last written filename
                    self.recording_filename = path
        except Exception as e:
            logger.error(f"Error flushing recording buffer on stop: {e}")
        
        # Stop recording pipeline (appsink branch)
        if self.record_bin and self.tee_recording_pad:
            # First set bin state to NULL
            self.record_bin.set_state(Gst.State.NULL)
            
            # Unlink the bin from the tee
            bin_sink_pad = self.record_bin.get_static_pad("sink")
            if bin_sink_pad:
                self.tee_recording_pad.unlink(bin_sink_pad)
            
            # Release the tee src pad
            self.tee.release_request_pad(self.tee_recording_pad)
            self.tee_recording_pad = None
            
            # Remove the bin from the pipeline
            self.pipeline.remove(self.record_bin)
            self.record_bin = None
        
        # Clear RAM cache
        with self._encoded_lock:
            self._encoded_chunks = []
            self._encoded_size = 0
        self.recording_filename = None
    
    def _setup_recording_pipeline(self):
        """Set up GStreamer pipeline for recording using appsink (RAM cache)."""
        # Check if tee element exists
        if not self.tee:
            logger.error("Cannot set up recording - tee element is not available")
            return False
            
        # Create a bin for recording elements
        self.record_bin = Gst.Bin.new("record_bin")
        
        # Create elements
        queue = Gst.ElementFactory.make("queue", "record_queue")
        
        # Configure recording queue buffer size from settings
        buffer_settings = self.config.get('buffer_settings', {})
        # Get recording buffer settings with defaults if not specified
        rec_buffers = buffer_settings.get('recording_buffers', 500)
        rec_bytes = buffer_settings.get('recording_bytes', 5120) * 1024  # Convert KB to bytes
        rec_time = buffer_settings.get('recording_time', 5) * Gst.SECOND
        
        # Apply buffer settings
        queue.set_property("max-size-buffers", rec_buffers)
        queue.set_property("max-size-bytes", rec_bytes)
        queue.set_property("max-size-time", rec_time)
        
        convert = Gst.ElementFactory.make("audioconvert", "record_convert")
        
        # Create encoder and muxer based on format
        if self.recording_format.lower() == "mp3":
            encoder = Gst.ElementFactory.make("lamemp3enc", "mp3_encoder")
            muxer = Gst.ElementFactory.make("id3v2mux", "id3_muxer")
            file_extension = ".mp3"
        elif self.recording_format.lower() == "ogg":
            encoder = Gst.ElementFactory.make("vorbisenc", "vorbis_encoder")
            muxer = Gst.ElementFactory.make("oggmux", "ogg_muxer")
            file_extension = ".ogg"
        elif self.recording_format.lower() == "flac":
            encoder = Gst.ElementFactory.make("flacenc", "flac_encoder")
            muxer = None  # FLAC doesn't need a muxer
            file_extension = ".flac"
        else:
            # Default to WAV
            encoder = Gst.ElementFactory.make("wavenc", "wav_encoder")
            muxer = None
            file_extension = ".wav"
        # Create appsink to capture encoded/muxed bytes
        appsink = Gst.ElementFactory.make("appsink", "record_appsink")
        if appsink:
            appsink.set_property("emit-signals", True)
            appsink.set_property("sync", False)
            # Don't drop: we want full data; leave default max-buffers
        
        # Check if all elements were created
        if (not queue or not convert or not encoder or not appsink):
            logger.error("Failed to create recording elements")
            self.is_recording = False
            return False
        
        # Remember appsink
        self._appsink = appsink
        
        # Add elements to the bin
        self.record_bin.add(queue)
        self.record_bin.add(convert)
        self.record_bin.add(encoder)
        if muxer:
            self.record_bin.add(muxer)
        self.record_bin.add(appsink)
        
        # Link elements
        queue.link(convert)
        convert.link(encoder)
        
        if muxer:
            encoder.link(muxer)
            muxer.link(appsink)
        else:
            encoder.link(appsink)
        
        # Add ghost pad to the bin
        sink_pad = queue.get_static_pad("sink")
        ghost_pad = Gst.GhostPad.new("sink", sink_pad)
        self.record_bin.add_pad(ghost_pad)
        
        # Add the bin to the pipeline and link to tee
        current_state = self.pipeline.get_state(0)[1]
        if self.pipeline.set_state(Gst.State.PAUSED) == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to pause pipeline for recording setup")
            self.is_recording = False
            return False
            
        # Add the record bin to the pipeline
        try:
            self.pipeline.add(self.record_bin)
            
            # Get a source pad from the tee element
            tee_src_pad = self.tee.get_request_pad("src_%u")
            bin_sink_pad = self.record_bin.get_static_pad("sink")
            
            # Link the tee to the recording bin
            if tee_src_pad.link(bin_sink_pad) != Gst.PadLinkReturn.OK:
                logger.error("Failed to link tee to recording bin")
                self.is_recording = False
                self.pipeline.set_state(current_state)
                return False
            
            # Store the tee src pad so we can release it when stopping recording
            self.tee_recording_pad = tee_src_pad
            
            # Connect appsink callback after linking
            try:
                self._appsink.connect("new-sample", self._on_new_sample)
            except Exception as e:
                logger.error(f"Failed to connect appsink callback: {e}")
                self.is_recording = False
                # detach bin
                self.tee.release_request_pad(self.tee_recording_pad)
                self.pipeline.remove(self.record_bin)
                self.record_bin = None
                self.pipeline.set_state(current_state)
                return False

            # Resume playback to previous state
            self.pipeline.set_state(current_state)
            
            logger.info("Started recording (RAM-cached mode)")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up recording pipeline: {e}")
            self.is_recording = False
            self.pipeline.set_state(current_state)
            return False
    
    def _create_recording_filename(self, extension=None, part_index: int | None = None, use_metadata: dict | None = None):
        """
        Create a filename for the recording based on metadata.
        
        Args:
            extension: File extension to use (default: based on format)
            part_index: Optional part index to include as -N before extension
            use_metadata: Optional metadata dict to build base name (defaults to current)
        """
        if not extension:
            # Determine extension from format
            if self.recording_format.lower() == "mp3":
                extension = ".mp3"
            elif self.recording_format.lower() == "ogg":
                extension = ".ogg"
            elif self.recording_format.lower() == "flac":
                extension = ".flac"
            else:
                extension = ".wav"
        
        md = use_metadata if use_metadata is not None else self.current_metadata
        # Create base filename from metadata or station name
        if 'title' in md:
            if 'artist' in md:
                base_name = f"{md['artist']} - {md['title']}"
            else:
                base_name = md['title']
        else:
            # If no title, use station name and timestamp
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            base_name = f"{self.current_station.get('name', 'Unknown')} - {timestamp}"
        
        # Sanitize filename (remove invalid characters)
        base_name = self._sanitize_filename(base_name)
        
        # Insert part suffix if provided
        name_with_part = f"{base_name}{f' - {part_index}' if part_index is not None else ''}"

        # Construct candidate
        filename = os.path.join(self.recording_dir, f"{name_with_part}{extension}")
        
        # If exists, add timestamp suffix _YYMMDDHHMMSS before extension
        if os.path.exists(filename):
            ts = datetime.datetime.now().strftime("_%y%m%d%H%M%S")
            filename = os.path.join(self.recording_dir, f"{name_with_part}{ts}{extension}")
        
        self.recording_filename = filename
        return filename
    
    def _rotate_recording_file(self):
        """
        On metadata change, flush current RAM cache to disk as a complete track
        and reset the cache for the next track (do not stop the pipeline).
        """
        if not self.is_recording:
            return
        try:
            if self._encoded_size > 0:
                # Use previous metadata for the track that just ended if available
                md = self.previous_metadata if self.previous_metadata else self.current_metadata
                self._flush_current_part(track_metadata=md, is_rotation=True)
            # Reset RAM cache for next track
            with self._encoded_lock:
                self._encoded_chunks = []
                self._encoded_size = 0
        except Exception as e:
            logger.error(f"Error rotating recording file: {e}")
    
    @staticmethod
    def _sanitize_filename(filename):
        """
        Sanitize filename by removing invalid characters.
        
        Args:
            filename: Input filename to sanitize
            
        Returns:
            Sanitized filename
        """
        # Replace invalid characters with underscores
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Limit length to avoid path length issues
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename

    # -------------------- Appsink and caching logic --------------------
    def _on_new_sample(self, appsink):
        """Appsink callback: append encoded bytes to RAM cache and enforce limits."""
        sample = appsink.emit('pull-sample')
        if not sample:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        # Map buffer to bytes
        success, mapinfo = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.OK
        try:
            data = bytes(mapinfo.data)
        finally:
            buf.unmap(mapinfo)
        # Append to chunk list
        with self._encoded_lock:
            self._encoded_chunks.append(data)
            self._encoded_size += len(data)
            cur_size = self._encoded_size

        # Enforce limits
        fmt = (self.recording_format or '').lower()
        if fmt == 'wav':
            if cur_size >= self._wav_autostop_threshold_bytes:
                # Warn and auto-stop (no mid-track parts), discard cache via main loop
                msg = (
                    f"WAV recording cache reached {cur_size//(1024*1024)}MB (>=95% of limit); "
                    f"auto-stopping to avoid invalid partial files."
                )
                def _do_stop():
                    try:
                        self.signals.cache_limit_warning.emit(msg)
                    except Exception:
                        pass
                    with self._encoded_lock:
                        self._encoded_chunks = []
                        self._encoded_size = 0
                    self.stop_recording(auto_rotation=False)
                    return False  # one-shot
                try:
                    GObject.idle_add(_do_stop)
                except Exception:
                    _do_stop()
        else:
            if cur_size >= self._record_cache_limit_bytes:
                # Flush part and continue
                try:
                    md = self.current_metadata.copy() if self.current_metadata else {}
                    self._flush_current_part(track_metadata=md, is_part=True)
                    # Reset cache after flush
                    with self._encoded_lock:
                        self._encoded_chunks = []
                        self._encoded_size = 0
                    self._record_part_index += 1
                except Exception as e:
                    logger.error(f"Error flushing part on size cap: {e}")
        return Gst.FlowReturn.OK

    def _flush_current_part(self, track_metadata: dict, is_part: bool = False, is_rotation: bool = False, is_final_stop: bool = False) -> str | None:
        """Write the RAM cache to a file with correct naming and minimal tagging.

        Returns the final file path, or None if nothing was written.
        """
        # Snapshot chunks safely
        with self._encoded_lock:
            if self._encoded_size == 0:
                return None
            chunks = self._encoded_chunks.copy()
            total_size = self._encoded_size
        fmt = (self.recording_format or '').lower()

        # Determine part index to use
        part_idx = self._record_part_index if is_part else None

        # Build target filename (collision-safe)
        final_path = self._create_recording_filename(extension=None, part_index=part_idx, use_metadata=track_metadata)

        # Ensure parent dir exists
        os.makedirs(self.recording_dir or os.path.expanduser('~/Music'), exist_ok=True)

        # Create temp path in same dir
        base_dir = os.path.dirname(final_path)
        tmp_name = f".~traydio-{datetime.datetime.now().strftime('%y%m%d%H%M%S')}-{os.getpid()}.tmp"
        temp_path = os.path.join(base_dir, tmp_name)

        try:
            # Compose bytes, with MP3 ID3v2.3 header if needed for parts
            out_bytes: bytes
            if fmt == 'mp3' and is_part:
                try:
                    out_bytes = self._build_id3v23_header(track_metadata) + b''.join(chunks)
                except Exception as e:
                    logger.warning(f"Failed to build ID3v2.3 tag for part, writing raw audio: {e}")
                    out_bytes = b''.join(chunks)
            else:
                out_bytes = b''.join(chunks)

            with open(temp_path, 'wb') as f:
                f.write(out_bytes)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    pass

            # Atomic replace to final
            os.replace(temp_path, final_path)
            self.recording_filename = final_path

            # Emit part flushed notification
            try:
                self.signals.part_flushed.emit(final_path, track_metadata or {})
            except Exception:
                pass

            logger.info(f"Saved recording: {final_path} ({total_size} bytes)")
            return final_path
        finally:
            # Cleanup temp if exists
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    def _build_id3v23_header(self, md: dict) -> bytes:
        """Build a minimal ID3v2.3 header with TIT2/TPE1/date using mutagen.

        Returns the raw ID3 tag bytes.
        """
        try:
            from mutagen.id3 import ID3, TIT2, TPE1, TYER, TDAT, TIME
        except Exception:
            # Fallback: no tag
            return b''

        id3 = ID3()
        title = md.get('title')
        artist = md.get('artist')
        now = datetime.datetime.now()
        if title:
            id3.add(TIT2(encoding=3, text=title))  # UTF-8 not strictly in v2.3; mutagen handles encoding flags
        if artist:
            id3.add(TPE1(encoding=3, text=artist))
        # Date fields for v2.3 (year, day+month, time)
        id3.add(TYER(encoding=3, text=str(now.year)))
        id3.add(TDAT(encoding=3, text=now.strftime('%d%m')))
        id3.add(TIME(encoding=3, text=now.strftime('%H%M')))
        # Save to bytes
        bio = BytesIO()
        id3.save(bio, v2_version=3)
        return bio.getvalue()
