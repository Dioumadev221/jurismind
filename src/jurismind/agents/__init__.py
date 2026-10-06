"""Agents IA de JurisMind.

Trois agents, qui partagent la même forme de réponse (`ReponseAgent`) : `client` fait le
point sur un client (F6), `dossier` assiste sur un dossier (F7), `analyse` examine une
pièce (F8). Tous s'appellent de la même façon :

    assister(session, utilisateur_id, cible, demande) -> ReponseAgent

où `cible` est un identifiant de client, de dossier ou de document, et où la session porte
les droits de l'utilisateur.
"""

from jurismind.agents import analyse, client, dossier
from jurismind.agents.commun import ReponseAgent

__all__ = ["ReponseAgent", "analyse", "client", "dossier"]
