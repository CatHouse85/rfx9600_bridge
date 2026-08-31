import socket
import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_BASE = "rfx9600/la_chaume"

UDP_PORT = 65442

client = mqtt.Client()
client.connect(MQTT_HOST, MQTT_PORT, 60)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", UDP_PORT))

print(f"RFX9600 MQTT Bridge started, listening on UDP {UDP_PORT}")

while True:
    try:
        data, addr = sock.recvfrom(1024)
        trois_octets = data[:3].hex()
        client.publish(f"{MQTT_TOPIC_BASE}/ack", trois_octets)
        print(f"Trame reçue de {addr} : {trois_octets}")
    except Exception as e:
        client.publish(f"{MQTT_TOPIC_BASE}/error", str(e))
        print(f"Erreur: {e}")