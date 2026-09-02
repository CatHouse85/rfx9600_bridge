import socket
import os
from mqtt_bridge import publish_frame

UDP_PORT = int(os.getenv("UDP_PORT", "4998"))

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", UDP_PORT))

print(f"Listening on UDP port {UDP_PORT}...")

while True:
    data, addr = sock.recvfrom(2048)
    print(f"From {addr}: {data.hex()}")
    publish_frame(data)
