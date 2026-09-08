# RFX9600 UDP → MQTT Bridge (App HAOS 2026)

Cette app écoute les trames UDP envoyées par le RFX9600 (port 4998)
et les publie sur MQTT pour Home Assistant.

- Slug : `rfx9600_bridge`
- UDP : port configurable (par défaut 4998)
- MQTT : hôte, port, user/pass, topic base configurables

## Installation

1. Créer un dépôt GitHub avec cette structure.
2. Dans Home Assistant : Paramètres → Applications → Dépôts → Ajouter l’URL du dépôt.
3. Installer l’app `RFX9600 UDP → MQTT Bridge`.
4. Configurer MQTT et le port UDP dans l’UI.
5. Vérifier les trames sur le topic `rfx9600/raw` (via MQTT Explorer ou HA).

## Prochaines étapes

- Extraire `packet_id` des trames.
- Publier des topics dédiés (`rfx9600/packet_id`, etc.).
- Intégrer dans les scénarios AV multi-sites.
