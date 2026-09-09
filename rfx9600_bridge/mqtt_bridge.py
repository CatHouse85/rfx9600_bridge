"""
Pont MQTT : s'abonne a un topic pour recevoir les noms de commandes IR
a envoyer, et publie le resultat de chaque envoi (ok / timeout / erreur).

Important : la connexion MQTT ne se fait JAMAIS au niveau du module (pas de
code "a plat" hors fonction). Si elle etait executee au moment de l'import,
une indisponibilite temporaire du broker au demarrage de Home Assistant
ferait planter tout le programme avant meme d'afficher un message de debug.
"""

import time
import paho.mqtt.client as mqtt


class MqttBridge:
    def __init__(self, host, port, username, password, topic_base, on_command):
        self.topic_base = topic_base
        self._host = host
        self._port = port

        self.client = mqtt.Client()
        if username:
            self.client.username_pw_set(username, password)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect   # ← ajout
        self.client.on_message = self._on_message
        self._on_command = on_command

    def connect(self, retries=10, delay=3):
        """Se connecte au broker, avec plusieurs tentatives.
        Le broker MQTT (add-on Mosquitto) peut mettre quelques secondes
        a etre pret au demarrage de Home Assistant."""
        for attempt in range(1, retries + 1):
            try:
                self.client.connect(self._host, self._port, keepalive=60)
                self.client.loop_start()
                print(f"MQTT connecte a {self._host}:{self._port}")
                return
            except Exception as e:
                print(f"MQTT connexion echouee ({attempt}/{retries}) : {e}")
                time.sleep(delay)
        raise RuntimeError("Impossible de se connecter au broker MQTT apres plusieurs tentatives")

    def _on_connect(self, client, userdata, flags, rc):
       if rc != 0:
        print(f"MQTT échec de connexion, code retour = {rc}")
        return     
       topic = f"{self.topic_base}/command"
       client.subscribe(topic)
       print(f"MQTT abonne a {topic}")

    def _on_disconnect(self, client, userdata, rc):        # ← nouvelle méthode
        print(f"MQTT déconnecté, code retour = {rc}")

    def _on_message(self, client, userdata, msg):
        command_name = msg.payload.decode(errors="ignore").strip()
        if not command_name:
            return
        print(f"MQTT commande recue : {command_name}")
        try:
            self._on_command(command_name)
        except Exception as e:
            print(f"Erreur lors du traitement de la commande '{command_name}' : {e}")
            self.publish_status(command_name, "error", str(e))

    def publish_status(self, command_name, status, extra=""):
        topic = f"{self.topic_base}/status"
        payload = f"{command_name}:{status}"
        if extra:
            payload += f":{extra}"
        self.client.publish(topic, payload)
        print(f"MQTT -> {topic}: {payload}")
