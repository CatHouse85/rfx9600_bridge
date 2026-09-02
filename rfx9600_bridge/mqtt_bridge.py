import os
import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USERNAME", "")
MQTT_PASS = os.getenv("MQTT_PASSWORD", "")
MQTT_BASE = os.getenv("MQTT_TOPIC_BASE", "rfx9600")

client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)

client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()

def publish_frame(data: bytes):
    hex_payload = data.hex()
    topic = f"{MQTT_BASE}/raw"
    client.publish(topic, hex_payload, qos=0, retain=False)
