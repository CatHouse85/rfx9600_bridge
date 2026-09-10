"""
RFX9600 bridge : recoit un nom de commande via MQTT, retrouve le payload IR
correspondant dans le CSV partage (/share, commun a tous les sites, filtre
localement selon la 'location' de cette instance), construit la trame UDP,
l'envoie UNE SEULE FOIS (pas de retry - certains equipements utilisent un
code "toggle" : renvoyer la commande la ferait basculer a nouveau), puis
attend une reponse portant le meme packet_id pour confirmer la reception.
"""

import csv
import json
import os
import socket
import struct
import threading
import time

from mqtt_bridge import MqttBridge

OPTIONS_PATH = "/data/options.json"

# Structure de trame (28 octets d'en-tete fixe) :
# Header(1) + PacketId(2) + Unknown(9) + Type(2) + Length(2)
# + Port(1) + Unknown(5) + Timeout(2) + Unknown(4) = 28 octets
HEADER_FORMAT = ">BH9xHHB5xH4x"
FRAME_TYPE_IR = 0x4000

# Un fichier codes.csv unique, partage par tous les sites (colonne "site").
# Chaque instance ne charge que les lignes qui la concernent :
#   - "all"                 -> valable partout
#   - la valeur de sa propre "location"
#   - les sous-zones de sa location (ex. Paris voit aussi paris_s / paris_c)
SITE_GROUPS = {
    "la_chaume": {"all", "la_chaume"},
    "paris": {"all", "paris", "paris_s", "paris_c"},
}


def load_options():
    with open(OPTIONS_PATH) as f:
        return json.load(f)


def load_mqtt_env():
    """Recupere les identifiants MQTT injectes automatiquement par Supervisor
    grace a 'services: [\"mqtt:want\"]' dans config.json."""
    env = {
        "host": os.getenv("MQTT_HOST", "core-mosquitto"),
        "port": int(os.getenv("MQTT_PORT", "1883")),
        "username": os.getenv("MQTT_USERNAME", ""),
        "password": os.getenv("MQTT_PASSWORD", ""),
    }
    has_creds = "oui" if env["username"] else "NON"
    print(f"MQTT env recu de Supervisor : host={env['host']} port={env['port']} identifiants presents={has_creds}")
    return env


def load_codes(path, location):
    """Relit le CSV a chaque commande : les modifications faites a chaud
    dans /share (via Samba / File editor) sont donc prises en compte
    immediatement, sans redemarrer l'add-on. Ne garde que les lignes
    pertinentes pour cette 'location'."""
    allowed_sites = SITE_GROUPS[location]
    codes = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["site"] not in allowed_sites:
                continue
            codes[row["command_name"]] = {
                "port": int(row["port"]),
                "payload": bytes.fromhex(row["payload_hex"]),
            }
    return codes


def build_ir_frame(packet_id, port, payload, timeout_ms=1500):
    header = struct.pack(HEADER_FORMAT, 0x00, packet_id, FRAME_TYPE_IR, len(payload), port, timeout_ms)
    return header + payload


def get_packet_id(frame):
    # Le packet_id est toujours aux octets 1-2, quel que soit le type de trame
    return struct.unpack_from(">H", frame, 1)[0]


class PacketIdCounter:
    """Compteur 16 bits avec rollover, comme decrit dans la doc du protocole."""

    def __init__(self):
        self._id = 0
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            self._id = (self._id + 1) % 0x10000
            return self._id


class Rfx9600Bridge:
    def __init__(self, options, mqtt_env):
        self.device_ip = options["device_ip"]
        self.udp_port = options["udp_port"]
        self.location = options.get("location")
        if self.location not in ("la_chaume", "paris"):
            raise ValueError(
                f"Option 'location' manquante ou invalide ({self.location!r}). "
                "Va dans Configuration de l'add-on, choisis 'la_chaume' ou 'paris', puis Enregistrer."
            )
        self.response_timeout = float(options.get("response_timeout", 2.0))
        self.codes_file = options.get("codes_file", "/share/rfx9600/codes.csv")
        self.packet_ids = PacketIdCounter()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", self.udp_port))

        topic_base = f"rfx9600/{self.location}"
        self.mqtt = MqttBridge(
            host=mqtt_env["host"],
            port=mqtt_env["port"],
            username=mqtt_env["username"],
            password=mqtt_env["password"],
            topic_base=topic_base,
            on_command=self.handle_command,
        )

    def handle_command(self, command_name):
        codes = load_codes(self.codes_file, self.location)
        code = codes.get(command_name)
        if code is None:
            print(f"Commande inconnue (ou hors zone '{self.location}') : {command_name}")
            self.mqtt.publish_status(command_name, "unknown_command")
            return

        packet_id = self.packet_ids.next()
        frame = build_ir_frame(packet_id, code["port"], code["payload"])

        # Envoi unique, volontairement sans retry (voir docstring en tete de fichier)
        self.sock.sendto(frame, (self.device_ip, self.udp_port))
        print(f"Envoye {command_name} (packet_id={packet_id}) vers {self.device_ip}:{self.udp_port}")

        if self._wait_for_ack(packet_id):
            self.mqtt.publish_status(command_name, "ok")
        else:
            self.mqtt.publish_status(command_name, "timeout")

    def _wait_for_ack(self, packet_id):
        deadline = time.time() + self.response_timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            self.sock.settimeout(remaining)
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                return False
            if len(data) >= 3 and get_packet_id(data) == packet_id:
                print(f"Ack recu pour packet_id={packet_id} depuis {addr}")
                return True
            # trame recue mais avec un autre packet_id : on ignore et on continue d'attendre

    def run(self):
        self.mqtt.connect()
        print(f"RFX9600 bridge demarre (location={self.location}), en attente de commandes MQTT...")
        # Le vrai travail se fait dans handle_command(), declenche par les
        # messages MQTT recus sur un thread separe (paho loop_start()).
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    opts = load_options()
    mqtt_env = load_mqtt_env()
    bridge = Rfx9600Bridge(opts, mqtt_env)
    bridge.run()
