"""Enregistrer les appels aux modèles, puis les rejouer sans modèle.

Une démonstration publique tourne sur un serveur gratuit : 512 Mo de mémoire, pas de
carte graphique, de quoi servir l'API mais pas un modèle de 3 milliards de paramètres. On
pourrait la brancher sur OpenAI, mais une démonstration qui coûte à chaque visite finit
éteinte. Elle rejoue donc des appels réellement faits, une fois, sur la machine de
développement :

    LLM_ENREGISTREMENT=demo/enregistrements.jsonl   # pendant le scénario
    LLM_FOURNISSEUR=demo                                 # sur le serveur public

**Seul le modèle est rejoué.** La recherche, les cinq contrôles, les règles des agents et
l'isolation par PostgreSQL s'exécutent pour de vrai à chaque requête : la réponse rejouée
repasse par les mêmes garde-fous que la première fois. C'est aussi ce qui rend le rejeu
honnête — il ne peut rien afficher que le pipeline n'aurait pas laissé passer.

La clé d'un enregistrement est l'empreinte de l'invite complète, extraits compris. Une
invite jamais vue (une question libre, un autre dossier) n'a pas de réponse enregistrée :
`ModeleIndisponible` est levée, et chaque appelant la traite à sa façon — la recherche se
passe alors de la voie vectorielle, l'API répond 503 avec une phrase qui l'explique.
"""

from __future__ import annotations

import hashlib
import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

MESSAGE_INDISPONIBLE = (
    "Démonstration publique : cette demande n'a pas été préparée, et ce serveur ne fait pas "
    "tourner de modèle. Essayez une des demandes proposées ; la recherche seule, la chronologie, "
    "les points d'attention et les échéances fonctionnent partout, sans modèle. Installé avec ses "
    "modèles (docker compose up), JurisMind répond à n'importe quelle question."
)


class ModeleIndisponible(RuntimeError):
    """Aucun modèle ne peut répondre à cette invite : ni local, ni distant, ni enregistré."""

    def __init__(self, message: str = MESSAGE_INDISPONIBLE) -> None:
        super().__init__(message)


def cle(nature: str, contenu: str) -> str:
    return hashlib.sha256(f"{nature}\x00{contenu}".encode()).hexdigest()


def _texte(messages: list[BaseMessage]) -> str:
    """Le projet n'envoie que des invites d'un seul message ; on garde le cas général."""
    return "\n\x1e\n".join(f"{message.type}:{message.content}" for message in messages)


# ------------------------------------------------------------------------- enregistrement


class Registre:
    """Fichier JSONL où l'on ajoute, sans jamais réécrire, chaque appel fait aux modèles."""

    def __init__(self, chemin: Path) -> None:
        self.chemin = chemin
        self._verrou = threading.Lock()
        chemin.parent.mkdir(parents=True, exist_ok=True)

    def ajouter(self, ligne: dict[str, Any]) -> None:
        with self._verrou, self.chemin.open("a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(ligne, ensure_ascii=False) + "\n")


class ChatEnregistre(BaseChatModel):
    """Passe chaque appel au vrai modèle, et en garde la trace."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    interne: BaseChatModel
    registre: Registre
    json_impose: bool = False

    @property
    def _llm_type(self) -> str:
        return "jurismind-enregistre"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        reponse = self.interne.invoke(messages, stop=stop)
        contenu = str(reponse.content)
        invite = _texte(messages)
        self.registre.ajouter(
            {
                "type": "chat",
                "cle": cle(f"chat:{self.json_impose}", invite),
                "invite": invite,
                "reponse": contenu,
            }
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=contenu))])


class VecteursEnregistres(Embeddings):
    """Garde les vecteurs des questions. Ceux des pièces sont déjà en base : inutile de les doubler."""

    def __init__(self, interne: Embeddings, registre: Registre) -> None:
        self.interne = interne
        self.registre = registre

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.interne.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        vecteur = self.interne.embed_query(text)
        self.registre.ajouter(
            {"type": "vecteur", "cle": cle("vecteur", text), "texte": text, "vecteur": vecteur}
        )
        return vecteur


# ------------------------------------------------------------------------------- rejeu


@lru_cache
def charger(chemin: str) -> dict[str, Any]:
    """Toutes les réponses enregistrées, par clé. La dernière enregistrée l'emporte."""
    reponses: dict[str, Any] = {}
    fichier = Path(chemin)
    if not fichier.exists():
        return reponses
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        if ligne.strip():
            donnees = json.loads(ligne)
            reponses[donnees["cle"]] = donnees["reponse"] if donnees["type"] == "chat" else donnees["vecteur"]
    return reponses


class ChatRejoue(BaseChatModel):
    """Répond ce que le vrai modèle a répondu à la même invite, ou rien."""

    chemin: str
    json_impose: bool = False

    @property
    def _llm_type(self) -> str:
        return "jurismind-rejoue"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        reponse = charger(self.chemin).get(cle(f"chat:{self.json_impose}", _texte(messages)))
        if reponse is None:
            raise ModeleIndisponible
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reponse))])


class VecteursRejoues(Embeddings):
    def __init__(self, chemin: str) -> None:
        self.chemin = chemin

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ModeleIndisponible("Démonstration publique : l'indexation de nouvelles pièces est désactivée.")

    def embed_query(self, text: str) -> list[float]:
        vecteur = charger(self.chemin).get(cle("vecteur", text))
        if vecteur is None:
            raise ModeleIndisponible
        return list(vecteur)
