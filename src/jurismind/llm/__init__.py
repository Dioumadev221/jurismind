"""Accès aux modèles de langage et d'embeddings."""

from jurismind.llm.fournisseur import Vitesse, modele_chat, modele_embeddings
from jurismind.llm.rejeu import ModeleIndisponible

__all__ = ["ModeleIndisponible", "Vitesse", "modele_chat", "modele_embeddings"]
