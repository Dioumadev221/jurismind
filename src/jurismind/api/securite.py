"""Qui parle à l'API, et avec quels droits.

Deux garanties, et elles ne sont pas dans l'API : elles sont dans PostgreSQL.

1. L'API ne se connecte **jamais** avec la clé propriétaire. Chaque requête ouvre une session
   au nom de l'utilisateur du jeton (`session_utilisateur`), donc soumise au RLS. Un endpoint
   mal écrit ne peut pas faire fuiter le dossier d'un autre client : la base refuse.
2. Le mot de passe n'est jamais stocké, seulement son empreinte. Les comptes importés du
   vieux logiciel portent `!` comme empreinte, qu'aucun mot de passe ne peut produire : ils
   existent, ils ne peuvent pas se connecter tant qu'on ne leur en a pas donné un.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.core.config import get_settings
from jurismind.db.models import Role, Utilisateur
from jurismind.db.session import get_engine, session_utilisateur

logger = logging.getLogger(__name__)

ALGORITHME = "HS256"
# Empreinte qu'aucun mot de passe ne peut produire : posée sur les comptes importés.
SANS_MOT_DE_PASSE = "!"
# Paramètres de scrypt (RFC 7914). `n` fixe le coût mémoire : 2^15 blocs, soit ~32 Mo par
# vérification, ce qui rend une attaque par dictionnaire coûteuse sans gêner une connexion.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
LONGUEUR_SEL = 16


def memoire_max(n: int, r: int) -> int:
    """Plafond mémoire à annoncer à OpenSSL, qui refuse au-delà de 32 Mo par défaut.

    scrypt consomme 128 * r * n octets ; avec n = 2^15 et r = 8, cela fait exactement 32 Mo
    et OpenSSL refuse. On annonce donc le double du besoin plutôt que de baisser le coût,
    qui est précisément ce qui protège les empreintes.
    """
    return 2 * 128 * r * n


def hacher(mot_de_passe: str) -> str:
    """Empreinte d'un mot de passe, avec son sel et ses paramètres, en une seule chaîne.

    `hashlib.scrypt` est dans la bibliothèque standard et c'est une fonction de dérivation
    conçue pour les mots de passe (coûteuse en mémoire). Argon2 ou bcrypt feraient aussi
    bien ; ils ajouteraient une dépendance pour le même service.
    """
    sel = secrets.token_bytes(LONGUEUR_SEL)
    empreinte = hashlib.scrypt(
        mot_de_passe.encode(),
        salt=sel,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
        maxmem=memoire_max(SCRYPT_N, SCRYPT_R),
    )
    encode = base64.b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${encode(sel).decode()}${encode(empreinte).decode()}"


def verifier(mot_de_passe: str, empreinte_stockee: str) -> bool:
    """Le mot de passe correspond-il à l'empreinte ? Faux pour toute empreinte illisible."""
    morceaux = empreinte_stockee.split("$")
    if len(morceaux) != 6 or morceaux[0] != "scrypt":
        return False  # « ! » des comptes importés, ou empreinte abîmée
    try:
        n, r, p = (int(valeur) for valeur in morceaux[1:4])
        sel = base64.b64decode(morceaux[4])
        attendue = base64.b64decode(morceaux[5])
    except (ValueError, TypeError):
        return False
    try:
        calculee = hashlib.scrypt(
            mot_de_passe.encode(),
            salt=sel,
            n=n,
            r=r,
            p=p,
            dklen=len(attendue),
            maxmem=memoire_max(n, r),
        )
    except ValueError:
        return False  # paramètres aberrants dans l'empreinte stockée
    # Comparaison à temps constant : une comparaison naïve renseigne sur le préfixe trouvé.
    return hmac.compare_digest(calculee, attendue)


def creer_jeton(utilisateur_id: int, role: Role, duree_minutes: int | None = None) -> tuple[str, int]:
    """Jeton signé pour cet utilisateur, et sa durée de vie en secondes."""
    reglages = get_settings()
    minutes = duree_minutes if duree_minutes is not None else reglages.api_duree_jeton_minutes
    expire_le = datetime.now(UTC) + timedelta(minutes=minutes)
    charge = {"sub": str(utilisateur_id), "role": str(role), "exp": expire_le}
    jeton = jwt.encode(charge, reglages.api_secret.get_secret_value(), algorithm=ALGORITHME)
    return jeton, minutes * 60


def lire_jeton(jeton: str) -> dict[str, Any]:
    """Contenu d'un jeton valide. Lève `ValueError` s'il est expiré, modifié ou illisible."""
    try:
        return dict(
            jwt.decode(
                jeton,
                get_settings().api_secret.get_secret_value(),
                algorithms=[ALGORITHME],
            )
        )
    except jwt.PyJWTError as erreur:
        raise ValueError(str(erreur)) from erreur


def authentifier(email: str, mot_de_passe: str) -> Utilisateur | None:
    """L'utilisateur si le couple est bon, `None` sinon — sans dire lequel des deux est faux."""
    with Session(get_engine()) as session:
        utilisateur = session.scalars(
            select(Utilisateur).where(Utilisateur.email == email.strip().lower())
        ).first()
        if utilisateur is None:
            # On vérifie quand même une empreinte factice : sinon le temps de réponse dit
            # si l'adresse existe.
            verifier(mot_de_passe, hacher("inexistant"))
            return None
        if not utilisateur.actif or not verifier(mot_de_passe, utilisateur.mot_de_passe_hash):
            return None
        session.expunge(utilisateur)
        return utilisateur


# --------------------------------------------------------------------------- dépendances

jeton_porteur = HTTPBearer(description="Jeton obtenu sur POST /connexion", auto_error=False)
NON_AUTORISE = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Jeton absent, expiré ou invalide",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True)
class Identite:
    """L'utilisateur de la requête en cours, tel que le jeton le déclare."""

    utilisateur_id: int
    role: Role


def identite(
    justificatif: Annotated[HTTPAuthorizationCredentials | None, Depends(jeton_porteur)],
) -> Identite:
    """Décode le jeton. C'est le seul endroit où l'API décide qui parle."""
    if justificatif is None:
        raise NON_AUTORISE
    try:
        charge = lire_jeton(justificatif.credentials)
        return Identite(int(charge["sub"]), Role(charge["role"]))
    except (ValueError, KeyError, TypeError) as erreur:
        logger.info("Jeton refusé : %s", erreur)
        raise NON_AUTORISE from erreur


def session_courante(qui: Annotated[Identite, Depends(identite)]) -> Iterator[Session]:
    """Une session ouverte **au nom de l'utilisateur** : c'est PostgreSQL qui applique ses droits."""
    with session_utilisateur(qui.utilisateur_id) as session:
        yield session


IdentiteRequise = Annotated[Identite, Depends(identite)]
SessionRequise = Annotated[Session, Depends(session_courante)]


def refuser_si(condition: bool, message: str) -> None:
    """Petit garde-fou de lisibilité pour les règles de rôle."""
    if condition:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
