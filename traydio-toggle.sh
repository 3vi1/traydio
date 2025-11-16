#!/bin/bash
qdbus6 org.traydio.App /org/traydio/App org.traydio.App.TogglePlayback

# If your distro uses qdbus instead of qdbus6:
#   qdbus org.traydio.App /org/traydio/App org.traydio.App.TogglePlayback
# Or with gdbus:
#   gdbus call --session --dest org.traydio.App --object-path /org/traydio/App --method org.traydio.App.TogglePlayback
