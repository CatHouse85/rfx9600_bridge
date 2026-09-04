import paho.mqtt.client as mqtt

MQTT_HOST = "core-mosquitto"
MQTT_PORT = 1883
MQTT_TOPIC_BASE = "rfx9600/la_chaume"

client = mqtt.Client()
client.connect(MQTT_HOST, MQTT_PORT, 60)

def publish_frame(data: bytes):
    try:
        trois_octets = data[:3].hex()
        topic = f"{MQTT_TOPIC_BASE}/ack"
        client.publish(topic, trois_octets)
        print(f"MQTT → {topic}: {trois_octets}")
    except Exception as e:
        err_topic = f"{MQTT_TOPIC_BASE}/error"
        client.publish(err_topic, str(e))
        print(f"MQTT ERROR → {e}")
