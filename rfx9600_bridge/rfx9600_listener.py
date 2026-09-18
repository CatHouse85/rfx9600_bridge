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
from log_utils import log

OPTIONS_PATH = "/data/options.json"

# Structure de trame (28 octets d'en-tete fixe) :
# Header(1) + PacketId(2) + Unknown(9) + Type(2) + Length(2)
# + Port(1) + Unknown(5) + Timeout(2) + Unknown(4) = 28 octets
HEADER_FORMAT = ">BH9xHHB5xH4x"
FRAME_TYPE_IR = 0x4000
FRAME_TYPE_RELAY = 0x6300
RELAY_LENGTH = 0x0006
# 10 derniers octets, constants sur les 8 captures de reference (4 relais x on/off)
RELAY_TAIL = bytes.fromhex("000020000008000000c3")

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


def load_mqtt_env(options):
    """Priorite aux identifiants injectes par Supervisor (services: mqtt:want).
    S'ils sont absents (NON confirme par le diagnostic), on retombe sur les
    identifiants manuels definis dans les options de l'add-on (compte
    'logins' cree directement dans Mosquitto)."""
    env = {
        "host": os.getenv("MQTT_HOST") or "core-mosquitto",
        "port": int(os.getenv("MQTT_PORT") or 1883),
        "username": os.getenv("MQTT_USERNAME") or options.get("mqtt_username", ""),
        "password": os.getenv("MQTT_PASSWORD") or options.get("mqtt_password", ""),
    }
    source = "Supervisor (auto)" if os.getenv("MQTT_USERNAME") else "options manuelles"
    has_creds = "oui" if env["username"] else "NON"
    log(f"MQTT identifiants : source={source} host={env['host']} port={env['port']} presents={has_creds}")
    return env


def load_codes(path, location):
    """Relit le CSV a chaque commande : les modifications faites a chaud
    dans /share (via Samba / File editor) sont donc prises en compte
    immediatement, sans redemarrer l'add-on. Ne garde que les lignes
    pertinentes pour cette 'location'. Les lignes commencant par # (une fois
    les espaces de debut retires) sont ignorees : c'est l'endroit pour mettre
    des notes, un historique de version, ou toute annotation libre.

    Colonnes PowerSense (optionnelles) :
      - sense_port : VIDE = pas de condition (envoi IR classique). 0-3 = port
        Sense1-4 du RFX9600, 0-indexe - meme convention que les ports IR et
        relais (pas de conversion d'index necessaire).
      - sense_logic : "and" = on emet si le port Sense est ON, "nand" = on
        emet si le port Sense est OFF. Ignore si sense_port est vide.

    Commandes relais : une ligne relais se reconnait a son 'payload_hex' vide.
    'port' est alors le numero de relais (0-indexe, comme les IR : relais1=0
    ... relais4=3), et l'etat ON/OFF est donne par le suffixe du
    command_name (doit finir par '_on' ou '_off'), ex. 'relay_1_on'. Chaque
    etat est une ligne CSV distincte, comme pour les commandes IR discretes
    (onkyo_power_on / onkyo_power_off)."""
    allowed_sites = SITE_GROUPS[location]
    codes = {}
    with open(path, newline="") as f:
        lines = (line for line in f if not line.lstrip().startswith("#"))
        reader = csv.DictReader(lines)
        for row in reader:
            command_name = row.get("command_name")
            if not command_name:
                continue
            if row["site"] not in allowed_sites:
                continue

            sense_port_str = (row.get("sense_port") or "").strip()
            sense_logic = (row.get("sense_logic") or "").strip().lower()
            payload_hex = (row.get("payload_hex") or "").strip()

            entry = {
                "port": int(row["port"]),
                "holdable": (row.get("holdable") or "").strip().lower() in ("oui", "yes", "true", "1"),
                # sense_port : vide = pas de PowerSense, sinon 0-indexe (Sense1=0 ... Sense4=3)
                "sense_port": int(sense_port_str) if sense_port_str else 0,
                "sense_active": sense_port_str != "",
                # nand -> on verifie "Sense = OFF" (check_off=True), and -> "Sense = ON"
                "check_off": (sense_logic == "nand"),
            }

            if payload_hex:
                entry["kind"] = "ir"
                entry["payload"] = bytes.fromhex(payload_hex)
            else:
                if command_name.endswith("_on"):
                    relay_state_on = True
                elif command_name.endswith("_off"):
                    relay_state_on = False
                else:
                    log(
                        f"Ligne relais ignoree (command_name doit finir par "
                        f"'_on' ou '_off') : {command_name}"
                    )
                    continue
                entry["kind"] = "relay"
                entry["relay_state_on"] = relay_state_on

            codes[command_name] = entry
    return codes


def build_ir_frame(packet_id, port, payload, timeout_ms=0):
    # Le champ "Length" de l'en-tete RFX vaut le NumberOfBytes declare a
    # l'INTERIEUR du payload (octets 2-3, juste apres le Type eecf/ffff)
    # + 16 - confirme par comparaison controlee de trames. On lit ce champ
    # directement plutot que de le deduire de la taille totale du payload,
    # car pour un payload "eecf" (base Philips), NumberOfBytes exclut les
    # 8 octets de son propre en-tete - contrairement a nos payloads "ffff"
    # generes nous-memes, ou les deux coincident.
    declared_numbytes = struct.unpack(">H", payload[2:4])[0]
    length_field = declared_numbytes + 16
    header = struct.pack(HEADER_FORMAT, 0x00, packet_id, FRAME_TYPE_IR, length_field, port, timeout_ms)
    return header + payload


def build_powersense_frame(packet_id, ir_port, sense_port, check_off, payload):
    """Construit une trame IR conditionnee par un port PowerSense du RFX9600.
    Structure reverse-engineered a partir de captures Wireshark reelles et
    validee octet pour octet (reconstruction identique aux deux captures de
    reference, check OFF et check ON, sur orangebox_power_toggle IR4/Sense1).

    - packet_id : identifiant de trame (16 bits)
    - ir_port   : port IR du RFX9600 a utiliser si la condition est remplie (0-3)
    - sense_port: port PowerSense a tester (0-3)
    - check_off : True pour verifier "port Sense = OFF", False pour "= ON"
    - payload   : payload IR (eecf/ffff) a emettre si la condition est vraie

    Le RFX9600 decide localement : si la condition est vraie, il emet le
    payload IR ; sinon, silence total (pas de trame de retour).
    Le delai configurable cote Pronto ("Wait for") n'est PAS transmis dans
    la trame - c'est un comportement local a la telecommande.
    """
    declared_numbytes = struct.unpack(">H", payload[2:4])[0]
    embedded_ir_header = (
        struct.pack(">H", 0x4000) +           # Type (bloc IR classique reutilise)
        struct.pack(">H", declared_numbytes + 16) +  # Length (meme formule que build_ir_frame)
        bytes([ir_port]) +                    # Port IR
        bytes(5) +                            # Unknown
        struct.pack(">H", 0) +                # Timeout
        bytes(4)                              # Unknown
    )

    body = struct.pack(">H", 0x0108) + struct.pack(">H", 0x0000)
    if check_off:
        # Bloc supplementaire de 4 octets, present uniquement en mode "check OFF"
        body += struct.pack(">H", 0x1300) + struct.pack(">H", 0x000c)
    body += struct.pack(">H", 0x6000) + struct.pack(">H", 0x0005)
    body += struct.pack(">H", sense_port) + struct.pack(">H", 0x0000)
    body += embedded_ir_header
    body += payload

    total_len = 12 + 2 + 2 + len(body)  # prefixe(12) + Type(2) + Length(2) + reste
    length_field = total_len - 20

    prefix = bytes([0x00]) + struct.pack(">H", packet_id) + bytes(9)
    return prefix + struct.pack(">H", 0x2100) + struct.pack(">H", length_field) + body


def build_relay_frame(packet_id, relay_port, state_on):
    """Construit une trame de commande relais (Type 0x6300, sans payload).
    Structure reverse-engineered et validee octet pour octet contre 8
    captures Wireshark reelles (4 relais x ON/OFF).

    - packet_id  : identifiant de trame (16 bits)
    - relay_port : numero de relais du RFX9600, 0-indexe (relais1=0 ... relais4=3)
    - state_on   : True = ON, False = OFF
    """
    prefix = bytes([0x00]) + struct.pack(">H", packet_id) + bytes(9)
    type_length = struct.pack(">H", FRAME_TYPE_RELAY) + struct.pack(">H", RELAY_LENGTH)
    port_state = bytes([relay_port]) + bytes([0x01 if state_on else 0x00])
    return prefix + type_length + port_state + RELAY_TAIL


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
            log(f"Commande inconnue (ou hors zone '{self.location}') : {command_name}")
            self.mqtt.publish_status(command_name, "unknown_command")
            return

        packet_id = self.packet_ids.next()

        if code["kind"] == "relay":
            frame = build_relay_frame(packet_id, code["port"], code["relay_state_on"])
        elif code["sense_active"]:
            frame = build_powersense_frame(
                packet_id,
                ir_port=code["port"],
                sense_port=code["sense_port"],
                check_off=code["check_off"],
                payload=code["payload"],
            )
        else:
            frame = build_ir_frame(packet_id, code["port"], code["payload"])

        # Envoi unique, volontairement sans retry (voir docstring en tete de fichier)
        self.sock.sendto(frame, (self.device_ip, self.udp_port))
        log(f"Envoye {command_name} (packet_id={packet_id}) vers {self.device_ip}:{self.udp_port}")

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
                log(f"Ack recu pour packet_id={packet_id} depuis {addr}")
                return True
            # trame recue mais avec un autre packet_id : on ignore et on continue d'attendre

    def run(self):
        self.mqtt.connect()
        log(f"RFX9600 bridge demarre (location={self.location}), en attente de commandes MQTT...")
        # Le vrai travail se fait dans handle_command(), declenche par les
        # messages MQTT recus sur un thread separe (paho loop_start()).
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    opts = load_options()
    mqtt_env = load_mqtt_env(opts)
    bridge = Rfx9600Bridge(opts, mqtt_env)
    bridge.run()
