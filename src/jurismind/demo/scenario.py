"""Le scénario de la démonstration : ce qu'un visiteur pourra demander, et ce qui a répondu.

Le scénario passe par l'API, avec les mêmes corps de requête que l'interface : c'est la
seule façon d'être sûr que l'invite rejouée sur le serveur public sera, au caractère près,
celle qui a été enregistrée ici. Une invite qui diffère d'un espace n'a pas de réponse.

Les demandes ne sont pas écrites à la main. Les questions viennent du corrigé de la
simulation (`data/simulation/verite.json`) : la réponse attendue est connue, et le scénario
note pour chacune si JurisMind a juste, s'est abstenu, ou s'est trompé. Rien n'est retiré
après coup — une démonstration qui ne montre que ses réussites ne prouve rien.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jurismind.api.securite import creer_jeton
from jurismind.db.models import AccesDossier, Client, Communication, Document, Dossier, Utilisateur
from jurismind.db.models.metier import StatutDossier
from jurismind.db.models.utilisateur import Role
from jurismind.db.session import get_engine
from jurismind.demo import SCENARIO
from jurismind.evaluation.jeu import CORRIGE, Question, _questions_du_dossier

logger = logging.getLogger(__name__)

# Les corps que l'interface envoie : à changer ici en même temps que dans `statique/`.
DEMANDE_DOSSIER = "Résume ce dossier"
DEMANDE_CLIENT = "fais le point"
TRI_LIMITE = 20

# Des questions dont la réponse n'est dans aucune pièce : l'abstention est le bon résultat.
# La première est celle qui a imposé le cinquième contrôle (ADR 0011).
SANS_REPONSE = (
    "Quelle est la capitale du Sénégal ?",
    "Quel est le taux de TVA applicable en France en 2027 ?",
    "Quelle est l'adresse électronique personnelle du juge ?",
)

# Ce que montre chaque pièce analysée : un exemplaire de chaque, quand le dossier en a.
CATEGORIES_A_ANALYSER = ("FACTURE", "MISE_EN_DEMEURE", "JUGEMENT", "CONTRAT", "PV_SIGNIFICATION")


@dataclass
class Compte:
    email: str
    nom: str
    role: str
    dossiers: int
    presentation: str


@dataclass
class Demande:
    """Une demande enregistrée, telle que l'interface la proposera."""

    nature: str  # question | dossier | client | document | tri
    compte: str
    libelle: str
    corps: dict[str, Any]
    cible: str | None = None  # référence du dossier, identifiant du client ou de la pièce
    contexte: str | None = None  # ce qui aide le visiteur à la retrouver : dossier, client
    attendu: list[str] = field(default_factory=list)
    resultat: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- comptes


def _nombre_de_dossiers(session: Session, utilisateur_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(AccesDossier)
            .where(AccesDossier.utilisateur_id == utilisateur_id)
        )
        or 0
    )


def choisir_comptes(session: Session) -> list[Utilisateur]:
    """Deux avocats aux portefeuilles disjoints, et une assistante.

    Deux avocats parce que l'isolation ne se démontre qu'à deux : la même page, deux listes
    différentes. Le premier est celui qui a le plus de dossiers, pour que la visite soit riche.
    """
    utilisateurs = list(
        session.scalars(select(Utilisateur).where(Utilisateur.actif).order_by(Utilisateur.id))
    )
    avocats = sorted(
        (u for u in utilisateurs if u.role is Role.AVOCAT),
        key=lambda u: -_nombre_de_dossiers(session, u.id),
    )
    if len(avocats) < 2:
        raise SystemExit("Il faut au moins deux avocats dans la base : lancer les connecteurs d'abord.")
    premier = avocats[0]
    siens = set(
        session.scalars(select(AccesDossier.dossier_id).where(AccesDossier.utilisateur_id == premier.id))
    )

    def chevauchement(u: Utilisateur) -> int:
        leurs = set(
            session.scalars(select(AccesDossier.dossier_id).where(AccesDossier.utilisateur_id == u.id))
        )
        return len(siens & leurs)

    second = min(avocats[1:], key=lambda u: (chevauchement(u), -_nombre_de_dossiers(session, u.id)))
    assistants = [u for u in utilisateurs if u.role is Role.ASSISTANT]
    choisis = [premier, second]
    if assistants:
        choisis.append(max(assistants, key=lambda u: _nombre_de_dossiers(session, u.id)))
    return choisis


def _presentation(utilisateur: Utilisateur, dossiers: int, premier: bool) -> str:
    if utilisateur.role is Role.ASSISTANT:
        return f"Legal assistant, {dossiers} matters, no confidential ones"
    if premier:
        return f"Lawyer, {dossiers} matters: the guided tour starts here"
    return f"Lawyer, {dossiers} matters: open it to see data isolation at work"


# ------------------------------------------------------------------------------ plan


def _corrige() -> dict[str, Any]:
    if not CORRIGE.exists():
        raise SystemExit(f"{CORRIGE} manquant : lancer `python -m simulation` avec la même graine")
    return json.loads(CORRIGE.read_text(encoding="utf-8"))


def _questions(session: Session, avocat: Utilisateur, tirage: random.Random) -> list[Question]:
    """Une question par type de fait, prise dans les dossiers que cet avocat peut voir."""
    visibles = set(
        session.scalars(
            select(Dossier.external_id)
            .join(AccesDossier, AccesDossier.dossier_id == Dossier.id)
            .where(AccesDossier.utilisateur_id == avocat.id)
        )
    )
    possibles = [
        question
        for dossier in _corrige()["dossiers"]
        if dossier["id"] in visibles
        for question in _questions_du_dossier(dossier)
    ]
    tirage.shuffle(possibles)
    retenues: list[Question] = []
    for categorie, nombre in (("montant", 3), ("delai", 2), ("clause", 1), ("date_ocr", 1)):
        retenues += [q for q in possibles if q.categorie == categorie][:nombre]
    return retenues


def _dossiers_vivants(session: Session, utilisateur_id: int, nombre: int) -> list[Dossier]:
    """Les dossiers en cours les plus fournis : ceux où un résumé a quelque chose à dire."""
    pieces = select(Document.dossier_id, func.count().label("n")).group_by(Document.dossier_id).subquery()
    return list(
        session.scalars(
            select(Dossier)
            .join(AccesDossier, AccesDossier.dossier_id == Dossier.id)
            .join(pieces, pieces.c.dossier_id == Dossier.id)
            .where(AccesDossier.utilisateur_id == utilisateur_id, Dossier.statut == StatutDossier.EN_COURS)
            .order_by(pieces.c.n.desc(), Dossier.reference)
            .limit(nombre)
        )
    )


def _pieces(session: Session, dossiers: list[Dossier]) -> list[Document]:
    choisies: list[Document] = []
    for categorie in CATEGORIES_A_ANALYSER:
        piece = session.scalars(
            select(Document)
            .where(
                Document.dossier_id.in_([d.id for d in dossiers]),
                Document.categorie_source == categorie,
                Document.texte.is_not(None),
            )
            .order_by(Document.id)
            .limit(1)
        ).first()
        if piece is not None:
            choisies.append(piece)
    return choisies


def planifier(session: Session, graine: int = 11) -> tuple[list[Compte], list[Demande]]:
    tirage = random.Random(graine)
    utilisateurs = choisir_comptes(session)
    comptes = [
        Compte(
            email=u.email,
            nom=u.nom_complet,
            role=str(u.role),
            dossiers=(n := _nombre_de_dossiers(session, u.id)),
            presentation=_presentation(u, n, rang == 0),
        )
        for rang, u in enumerate(utilisateurs)
    ]
    guide = utilisateurs[0]
    demandes: list[Demande] = []

    # Le tri d'abord : il dépose des propositions, et la synthèse d'un client peut en tenir
    # compte. Enregistrer la synthèse avant le tri, puis exporter la base après, donnerait une
    # invite qui ne se reproduit plus.
    if session.scalar(
        select(func.count()).select_from(Communication).where(Communication.dossier_id.is_(None))
    ):
        demandes.append(Demande("tri", guide.email, "Trier le courrier entrant", {"limite": TRI_LIMITE}))

    for question in _questions(session, guide, tirage):
        demandes.append(
            Demande(
                "question",
                guide.email,
                question.question,
                {"question": question.question, "filtres": {}},
                attendu=question.attendu,
            )
        )
    for libelle in SANS_REPONSE:
        demandes.append(Demande("question", guide.email, libelle, {"question": libelle, "filtres": {}}))

    dossiers = _dossiers_vivants(session, guide.id, 3)
    for dossier in dossiers:
        demandes.append(
            Demande(
                "dossier",
                guide.email,
                DEMANDE_DOSSIER,
                {"demande": DEMANDE_DOSSIER},
                cible=dossier.reference,
                contexte=dossier.intitule,
            )
        )
    for client_id in dict.fromkeys(d.client_id for d in dossiers):
        client = session.get(Client, client_id)
        demandes.append(
            Demande(
                "client",
                guide.email,
                DEMANDE_CLIENT,
                {"demande": DEMANDE_CLIENT},
                cible=str(client_id),
                contexte=client.nom if client else None,
            )
        )
    references = {d.id: d.reference for d in dossiers}
    for piece in _pieces(session, dossiers):
        demandes.append(
            Demande(
                "document",
                guide.email,
                piece.titre,
                {"demande": ""},
                cible=str(piece.id),
                contexte=references.get(piece.dossier_id),
            )
        )

    # Le second avocat : de quoi constater qu'une question posée depuis son compte ne voit
    # que ses pièces à lui.
    for question in _questions(session, utilisateurs[1], tirage)[:2]:
        demandes.append(
            Demande(
                "question",
                utilisateurs[1].email,
                question.question,
                {"question": question.question, "filtres": {}},
                attendu=question.attendu,
            )
        )
    return comptes, demandes


# ---------------------------------------------------------------------------- exécution


def _chemin(demande: Demande) -> str:
    return {
        "question": "/questions",
        "dossier": f"/dossiers/{demande.cible}/assistant",
        "client": f"/clients/{demande.cible}/assistant",
        "document": f"/documents/{demande.cible}/analyse",
        "tri": "/courrier/tri",
    }[demande.nature]


def _chiffres(texte: str) -> str:
    return re.sub(r"[\s  .]", "", texte)


def _bilan(demande: Demande, reponse: dict[str, Any]) -> dict[str, Any]:
    assert isinstance(reponse, dict)
    bilan: dict[str, Any] = {"abstention": reponse.get("abstention"), "texte": reponse.get("texte", "")[:400]}
    if demande.attendu:
        bilan["juste"] = not reponse.get("abstention") and any(
            _chiffres(valeur) in _chiffres(reponse.get("texte", "")) for valeur in demande.attendu
        )
    elif demande.nature == "question":
        bilan["juste"] = bool(reponse.get("abstention"))  # aucune réponse n'existe : s'abstenir est juste
    return bilan


def executer(comptes: list[Compte], demandes: list[Demande]) -> list[Demande]:
    """Joue chaque demande par l'API, sous l'identité du compte qui la pose."""
    from jurismind.api.main import app

    with Session(get_engine()) as session:
        identites = {
            u.email: creer_jeton(u.id, u.role)[0]
            for u in session.scalars(
                select(Utilisateur).where(Utilisateur.email.in_([c.email for c in comptes]))
            )
        }

    client = TestClient(app)
    for rang, demande in enumerate(demandes, start=1):
        depart = time.perf_counter()
        logger.info("[%s/%s] %s — %s", rang, len(demandes), demande.nature, demande.libelle[:70])
        reponse = client.post(
            _chemin(demande),
            json=demande.corps,
            headers={"Authorization": f"Bearer {identites[demande.compte]}"},
        )
        if reponse.status_code != 200:
            demande.resultat = {"erreur": reponse.status_code, "detail": reponse.text[:300]}
            logger.warning("  → %s %s", reponse.status_code, reponse.text[:200])
            continue
        demande.resultat = _bilan(demande, reponse.json()) | {
            "secondes": round(time.perf_counter() - depart, 1)
        }
        logger.info("  → %s", demande.resultat)
    return demandes


def ecrire(comptes: list[Compte], demandes: list[Demande], date_du_cabinet: str) -> None:
    SCENARIO.parent.mkdir(parents=True, exist_ok=True)
    questions = [d for d in demandes if d.nature == "question" and "juste" in d.resultat]
    SCENARIO.write_text(
        json.dumps(
            {
                "date_du_cabinet": date_du_cabinet,
                "enregistre_le": time.strftime("%Y-%m-%d"),
                "comptes": [asdict(c) for c in comptes],
                "demandes": [asdict(d) for d in demandes if "erreur" not in d.resultat],
                "bilan": {
                    "questions": len(questions),
                    "justes": sum(1 for d in questions if d.resultat["juste"]),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
