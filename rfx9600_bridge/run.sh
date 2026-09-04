#!/bin/sh
set -e

echo "Starting RFX9600 UDP → MQTT bridge..."

# On pourrait plus tard lire un fichier de config, mais pour l’instant
# les options seront passées via variables d’environnement par HA.

python3 /app/rfx9600_listener.py
