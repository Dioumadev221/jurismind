"""Production des fichiers du serveur de documents du cabinet simulé."""

from pathlib import Path

from simulation.documents.contenu import contenu
from simulation.documents.rendu import ecrire
from simulation.modeles import Monde


def generer_fichiers(monde: Monde, racine: Path) -> int:
    clients = {c.id: c for c in monde.clients}
    avocats = {a.id: a.titre for a in monde.avocats}
    n = 0
    for dossier in monde.dossiers:
        for doc in dossier.documents:
            blocs = contenu(doc, dossier, clients[dossier.client_id], avocats[dossier.responsable_id])
            ecrire(racine / doc.fichier, blocs, doc.libelle, doc.format, doc.scan, doc.id, doc.date)
            n += 1
    return n
