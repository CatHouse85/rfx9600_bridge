#!/bin/sh
set -e

echo "Starting RFX9600 UDP → MQTT bridge..."

ls -l /app

echo "Launching Python..."
python /app/rfx9600_listener.py

echo "Python finished."
