"""
RFX9600 bridge : recoit un nom de commande via MQTT, retrouve le payload IR
correspondant dans le CSV (/share, modifiable a chaud), construit la trame
UDP, l'envoie UNE SEULE FOIS (pas de retry - certains equipements utilisent
un code "toggle" : renvoyer la commande la ferait basculer a nouveau), puis
attend une reponse portant le meme packet_id pour confirmer la reception.
"""

import csv
import json
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


def load_options():
    with open(OPTIONS_PATH) as f:
        return json.load(f)


def load_codes(path):
    """Relit le CSV a chaque commande : les modifications faites a chaud
    dans /share (via Samba / File editor) sont donc prises en compte
    immediatement, sans redemarrer l'add-on."""
    codes = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
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
    def __init__(self, options):
        self.device_ip = options["device_ip"]
        self.udp_port = options["udp_port"]
        self.response_timeout = float(options.get("response_timeout", 2.0))
        self.codes_file = options.get("codes_file", "/share/rfx9600/codes.csv")
        self.packet_ids = PacketIdCounter()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", self.udp_port))

        self.mqtt = MqttBridge(
            host=options["mqtt_host"],
            port=options["mqtt_port"],
            username=options.get("mqtt_username", ""),
            password=options.get("mqtt_password", ""),
            topic_base=options.get("mqtt_topic_base", "rfx9600"),
            on_command=self.handle_command,
        )

    def handle_command(self, command_name):
        codes = load_codes(self.codes_file)
        code = codes.get(command_name)
        if code is None:
            print(f"Commande inconnue : {command_name}")
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
        self.sock.settimeout(self.response_timeout)
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
        print("RFX9600 bridge demarre, en attente de commandes MQTT...")
        # Le vrai travail se fait dans handle_command(), declenche par les
        # messages MQTT recus sur un thread separe (paho loop_start()).
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    opts = load_options()
    bridge = Rfx9600Bridge(opts)
    bridge.run()
