# RFX9600 UDP → MQTT Bridge

Add-on Home Assistant OS qui pilote un boîtier RFX9600 (passerelle IR/Relais/PowerSense
Philips Pronto) via UDP, déclenché par des commandes MQTT. Développé dans le cadre du
projet de migration Philips Pronto → Home Assistant sur les sites **La Chaume** et
**Paris** (salon / cuisine).

## Architecture

Chaque site physique possédant son propre RFX9600 exécute **sa propre instance** de cet
add-on, sur son propre NUC HAOS :

| Site       | NUC   | RFX9600 (IP:port)      | `location` |
|------------|-------|-------------------------|------------|
| La Chaume  | NUC 1 | `11.85.85.101:65442`    | `la_chaume`|
| Paris (S+C)| NUC 2 | à renseigner             | `paris`    |

Aucune dépendance réseau entre sites au moment de l'exécution (conforme à l'exigence
du cahier des charges : fonctionnement 100% local). Le seul élément partagé entre les
deux instances est le fichier `codes.csv`, qui est un **fichier unique** contenant les
commandes des deux sites, copié localement dans le `/share` de chaque NUC — chaque
instance ne charge que les lignes qui la concernent (voir *Format de `codes.csv`*).

## Structure du dépôt

```
.
├── .github/workflows/build.yml   # build + push de l'image Docker sur GHCR
├── rfx9600_bridge/                # l'add-on lui-même
│   ├── config.json
│   ├── Dockerfile
│   ├── mqtt_bridge.py
│   ├── rfx9600_listener.py
│   └── run.sh
├── tools/
│   ├── pronto_hex_to_payload.py   # conversion Pronto HEX (RC5/RC6) → payload ECF
│   └── batch_convert_codes.py     # conversion par lots → lignes codes.csv
├── codes_template.csv             # modèle/exemple de codes.csv
└── repository.json                # métadonnées du dépôt d'add-ons HA
```

## Installation

1. Ajouter ce dépôt dans **Paramètres → Add-ons → Boutique des add-ons → ⋮ → Dépôts**.
2. Installer l'add-on **RFX9600 UDP → MQTT Bridge**.
3. Dans **Configuration**, renseigner :
   - `device_ip` / `udp_port` : adresse du RFX9600 de ce site.
   - `location` : `la_chaume` ou `paris`.
   - `mqtt_username` / `mqtt_password` : identifiants créés côté Mosquitto (voir
     *Configuration MQTT* ci-dessous).
4. Copier `codes_template.csv` (ou le `codes.csv` à jour du projet) vers
   `/share/rfx9600/codes.csv` sur ce NUC.
5. Démarrer l'add-on.

## Configuration MQTT

L'injection automatique d'identifiants via `services: ["mqtt:want"]` ne fonctionne pas
de façon fiable sur cette installation (cause non confirmée : add-on Mosquitto utilisé,
ou restriction temporaire des comptes non-admin côté HA). À la place, des identifiants
sont créés **directement dans l'add-on Mosquitto** (fonctionnalité native `logins`,
indépendante des comptes Personnes/Utilisateurs HA) :

```yaml
logins:
  - username: rfx9600_bridge
    password: <mot de passe choisi>
```

Ces mêmes identifiants sont ensuite renseignés dans la Configuration de l'add-on
(`mqtt_username` / `mqtt_password`).

## Topics MQTT

Pour une instance de `location` donnée (`la_chaume` ou `paris`) :

- **Commande** (à publier) : `rfx9600/<location>/command`, payload = `command_name`
  (doit exister dans `codes.csv` pour cette localisation).
- **Statut** (publié par l'add-on) : `rfx9600/<location>/status`, payload =
  `command_name:résultat` où résultat est `ok`, `timeout`, `unknown_command`, ou `error:<détail>`.

## Format de `codes.csv`

```
command_name,site,port,payload_hex,holdable
```

| Colonne       | Description |
|---------------|-------------|
| `command_name`| Identifiant unique **au sein des lignes visibles par une instance** (`site == all` ou `site` correspondant à sa `location`) — deux sites différents peuvent réutiliser le même nom. Descriptif par convention (`tv_lg_power_on`), pas de colonnes `device`/`function` séparées. |
| `site`        | `all` (partout), `la_chaume`, `paris` (les deux pièces), `paris_s`, ou `paris_c`. |
| `port`        | Sortie IR du RFX9600 (0-3, zéro-indexé — IR1=0 … IR4=3). |
| `payload_hex` | Trame ECF complète en hexadécimal (voir *Obtenir les payloads IR*). |
| `holdable`    | `oui`/`non`. Indique si cette commande est destinée à être répétée par une automatisation HA tant qu'un bouton est maintenu (ex. `volume_up`), ou envoyée en une seule fois (ex. `power_on`). N'affecte pas le comportement du script — c'est une métadonnée pour la conception des automatisations. |

`timeout_ms` n'est plus une colonne : la valeur est toujours `0` (envoi unique), fixée dans le code — c'est le comportement observé sur les vraies trames émises par la télécommande Pronto pour un appui simple.

**Lignes de commentaire** : toute ligne commençant par `#` (espaces de début ignorés) est ignorée au chargement — c'est l'endroit pour tes notes, un historique de modification, ou toute annotation libre, n'importe où dans le fichier.

Une seule ligne active par commande.

## Obtenir les payloads IR (`payload_hex`)

Méthode retenue : préparer une télécommande Pronto avec toutes les commandes nécessaires (par site), puis capturer directement les trames via Wireshark en les actionnant. Le payload capturé (préfixe `eecf` ou `ffff`, les deux fonctionnent à l'identique) se colle tel quel dans `payload_hex`, sans transformation.

Un outil de conversion Pronto HEX → ECF existe aussi (`tools/pronto_hex_to_payload.py`, `tools/batch_convert_codes.py`) pour les cas où seul un code Pronto HEX brut (RC5/RC6, format `0000 ...`) est disponible sans possibilité de capture — mais la capture directe reste la méthode privilégiée : plus fiable, elle évite toute dépendance à la justesse de l'algorithme de conversion.

## Protocole RFX9600 — notes de référence

- Format de trame, structure ECF, et comportement du protocole documentés à partir
  d'un travail de reverse engineering tiers (dépôt
  [petergeraghty/pronto-lib](https://github.com/petergeraghty/pronto-lib)) et de
  captures Wireshark propres au projet.
- Pas de retry automatique sur l'envoi : certains équipements utilisent un code IR
  "toggle" (un seul code fait basculer l'état) — renvoyer la commande la ferait
  basculer une seconde fois. Une commande non confirmée (timeout) n'est donc jamais
  réémise automatiquement par le script.
- `timeout_ms = 0` correspond à un envoi unique (comportement observé pour un appui
  court sur la télécommande réelle) ; une valeur non nulle fait répéter l'émission IR
  pendant cette durée. La télécommande réelle prolonge un appui maintenu via des
  messages périodiques (~1/s) plutôt qu'un timeout infini — c'est ce comportement
  qu'on reproduit côté Home Assistant pour les commandes `holdable`.
