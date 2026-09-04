#!/bin/sh

echo "RUN.SH: start"

ls -l /

echo "RUN.SH: listing /app"
ls -l /app || echo "RUN.SH: /app not found"

echo "RUN.SH: trying python"
python /app/rfx9600_listener.py || echo "RUN.SH: python failed"

echo "RUN.SH: end"
