"""Petit utilitaire pour horodater chaque ligne du journal de l'add-on.

Sans ca, le journal affiche du texte brut sans date/heure - impossible de
distinguer une session d'une autre une fois l'add-on redemarre plusieurs
fois (le seul moyen de "vider" le journal). Chaque appel a log() prefixe
le message avec la date et l'heure exactes.
"""

from datetime import datetime


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} {message}", flush=True)
