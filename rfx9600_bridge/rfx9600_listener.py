import socket
import os
from mqtt_bridge import publish_frame

UDP_PORT = int(os.getenv("UDP_PORT", "4998"))

print("DEBUG: Python démarre correctement…")
print(f"DEBUG: lancement du listener sur UDP {UDP_PORT}")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", UDP_PORT))

print(f"Listening on UDP port {UDP_PORT}...")

while True:
    try:
        data, addr = sock.recvfrom(2048)
        print(f"From {addr}: {data.hex()}")
        publish_frame(data)
    except Exception as e:
        print(f"Listener ERROR → {e}")
