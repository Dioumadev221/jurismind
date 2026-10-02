"""Agents IA de JurisMind.

Deux agents pour l'instant, qui partagent la même forme de réponse (`ReponseAgent`) :
`client` fait le point sur un client (F6), `dossier` assiste sur un dossier (F7).
Les deux s'appellent de la même façon : `assister(session, utilisateur_id, cible, demande)`.
"""

from jurismind.agents import client, dossier
from jurismind.agents.commun import ReponseAgent

__all__ = ["ReponseAgent", "client", "dossier"]
