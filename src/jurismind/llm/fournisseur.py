"""Couche d'accès aux modèles.

Le reste du produit demande « un modèle rapide » ou « un modèle de qualité » sans
savoir s'il parle à Ollama (local) ou à OpenAI : le choix se fait dans `.env`.
"""

from enum import StrEnum
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from jurismind.core.config import get_settings

# Nombre de tokens de contexte demandé aux modèles locaux : assez pour 4-5 extraits,
# mais pas trop, car sur CPU la lecture du contexte est ce qui coûte le plus cher.
CONTEXTE = 4096
# Durée pendant laquelle Ollama garde un modèle en mémoire : un rechargement coûte
# une vingtaine de secondes sur une machine sans carte graphique.
MEMOIRE = "30m"
MEMOIRE_SECONDES = 1800  # même durée, mais OllamaEmbeddings l'attend en secondes


class Vitesse(StrEnum):
    RAPIDE = "rapide"  # l'utilisateur attend devant son écran : chat, routage, tri
    QUALITE = "qualite"  # tâche de fond : extraction structurée, résumés


@lru_cache
def modele_chat(
    vitesse: Vitesse = Vitesse.RAPIDE, json: bool = False, nom: str | None = None
) -> BaseChatModel:
    """Renvoie un modèle de génération de texte.

    `json=True` force une réponse en JSON. `nom` permet d'imposer un modèle précis
    (utilisé par le banc d'essai) au lieu de celui choisi dans `.env`.
    """
    reglages = get_settings()
    if nom is None:
        nom = reglages.modele_rapide if vitesse is Vitesse.RAPIDE else reglages.modele_qualite

    if reglages.llm_fournisseur == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=nom,
            base_url=reglages.ollama_base_url,
            temperature=0,  # pas de créativité : on veut des réponses reproductibles
            format="json" if json else None,
            num_ctx=CONTEXTE,
            keep_alive=MEMOIRE,  # évite de le recharger à chaque question
        )

    if reglages.llm_fournisseur == "openai":
        from langchain_openai import ChatOpenAI

        if reglages.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY est vide dans .env")
        return ChatOpenAI(
            model=nom,
            api_key=reglages.openai_api_key,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}} if json else {},
        )

    raise ValueError(f"Fournisseur inconnu : {reglages.llm_fournisseur!r} (attendu : ollama ou openai)")


@lru_cache
def modele_embeddings() -> Embeddings:
    """Renvoie le modèle qui transforme un texte en vecteur de 1024 nombres."""
    reglages = get_settings()

    if reglages.llm_fournisseur == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=reglages.modele_embeddings,
            base_url=reglages.ollama_base_url,
            keep_alive=MEMOIRE_SECONDES,
        )

    if reglages.llm_fournisseur == "openai":
        from langchain_openai import OpenAIEmbeddings

        if reglages.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY est vide dans .env")
        # `dimensions` ramène le vecteur à 1024 nombres, comme bge-m3 : même colonne en base.
        return OpenAIEmbeddings(
            model=reglages.modele_embeddings, api_key=reglages.openai_api_key, dimensions=1024
        )

    raise ValueError(f"Fournisseur inconnu : {reglages.llm_fournisseur!r} (attendu : ollama ou openai)")
