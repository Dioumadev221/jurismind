"""Construction du jeu d'évaluation à partir du corrigé de la simulation.

Les documents du cabinet ont été fabriqués à partir de faits connus (montants, délais,
dates, parties). `data/simulation/verite.json` les conserve : on peut donc écrire des
questions **dont on connaît la réponse exacte**, et mesurer la fiabilité au lieu de
l'affirmer — y compris sur des documents que seule l'OCR a rendus lisibles.

Le jeu contient aussi des questions **sans réponse** : un système honnête doit s'abstenir.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CORRIGE = Path("data/simulation/verite.json")


@dataclass
class Question:
    """Une question, sa réponse attendue, et le document qui la contient."""

    question: str
    # Valeurs qui doivent apparaître dans la réponse (chiffres comparés sans espaces).
    attendu: list[str] = field(default_factory=list)
    # Identifiant d'origine du document qui porte la réponse (pour mesurer la recherche).
    document_attendu: int | None = None
    dossier_attendu: int | None = None
    # Utilisateur qui pose la question, par son identifiant dans le logiciel du cabinet.
    avocat_attendu: int | None = None
    categorie: str = "fait"
    sans_reponse: bool = False


def _fcfa(montant: int) -> str:
    return f"{montant:,}".replace(",", " ")


def _documents(dossier: dict[str, Any], categorie: str) -> list[dict[str, Any]]:
    return [doc for doc in dossier["documents"] if doc["categorie"] == categorie]


def _questions_du_dossier(dossier: dict[str, Any]) -> list[Question]:
    """Écrit les questions possibles pour un dossier, selon les documents qu'il contient."""
    questions: list[Question] = []
    commun = {
        "dossier_attendu": dossier["id"],
        "avocat_attendu": dossier["responsable_id"],
    }

    for facture in _documents(dossier, "FACTURE"):
        faits = facture["faits"]
        questions.append(
            Question(
                question=f"Quel est le montant de la facture {faits['numero']} ?",
                attendu=[_fcfa(int(faits["montant"]))],
                document_attendu=facture["id"],
                categorie="montant",
                **commun,
            )
        )

    for mise_en_demeure in _documents(dossier, "MISE_EN_DEMEURE"):
        faits = mise_en_demeure["faits"]
        destinataire = faits.get("destinataire")
        if not destinataire or "delai_jours" not in faits:
            continue
        questions.append(
            Question(
                question=(f"Quel délai de paiement la mise en demeure accorde-t-elle à {destinataire} ?"),
                attendu=[str(faits["delai_jours"])],
                document_attendu=mise_en_demeure["id"],
                categorie="delai",
                **commun,
            )
        )

    for ordonnance in _documents(dossier, "ORDONNANCE_IP"):
        faits = ordonnance["faits"]
        questions.append(
            Question(
                question=(
                    f"Quelle somme l'ordonnance d'injonction de payer n° {faits['numero']} "
                    "met-elle à la charge du débiteur ?"
                ),
                attendu=[_fcfa(int(faits["montant"]))],
                document_attendu=ordonnance["id"],
                categorie="montant",
                **commun,
            )
        )

    # Les procès-verbaux d'huissier sont majoritairement des scans : ces questions ne
    # peuvent réussir que si l'OCR a bien fonctionné.
    for pv in _documents(dossier, "PV_SIGNIFICATION"):
        faits = pv["faits"]
        if "date_signification" not in faits:
            continue
        annee, mois, jour = faits["date_signification"].split("-")
        questions.append(
            Question(
                question=(f"À quelle date l'ordonnance a-t-elle été signifiée à {faits['destinataire']} ?"),
                attendu=[f"{jour}/{mois}/{annee}", f"{int(jour)}"],
                document_attendu=pv["id"],
                categorie="date_ocr",
                **commun,
            )
        )

    for contrat in _documents(dossier, "CONTRAT"):
        faits = contrat["faits"]
        if "preavis_resiliation_jours" not in faits:
            continue
        questions.append(
            Question(
                question=(
                    "Quel préavis de résiliation prévoit le contrat signé avec "
                    f"{faits.get('cocontractant')} ?"
                ),
                attendu=[str(faits["preavis_resiliation_jours"])],
                document_attendu=contrat["id"],
                categorie="clause",
                **commun,
            )
        )

    return questions


def questions_sans_reponse(monde: dict[str, Any], nombre: int, tirage: random.Random) -> list[Question]:
    """Questions dont la réponse ne peut pas se trouver dans les pièces du cabinet."""
    modeles = [
        "Quelle est la capitale du Sénégal ?",
        "Quel est le taux de TVA applicable en France en 2027 ?",
        "Quelle est la date de naissance du gérant de {societe} ?",
        "Combien de salariés compte {societe} ?",
        "Quelle est l'adresse électronique personnelle du juge ?",
    ]
    dossiers = tirage.sample(monde["dossiers"], min(nombre, len(monde["dossiers"])))
    questions = []
    for rang, dossier in enumerate(dossiers):
        societe = dossier["intitule"].split(" c/ ")[0]
        questions.append(
            Question(
                question=modeles[rang % len(modeles)].format(societe=societe),
                sans_reponse=True,
                dossier_attendu=dossier["id"],
                avocat_attendu=dossier["responsable_id"],
                categorie="sans_reponse",
            )
        )
    return questions


def construire(
    nombre: int = 40, part_sans_reponse: float = 0.2, graine: int = 7, corrige: Path = CORRIGE
) -> list[Question]:
    """Tire un jeu de questions reproductible : même graine, même jeu."""
    if not corrige.exists():
        raise FileNotFoundError(f"{corrige} manquant : lancer `python -m simulation`")
    monde = json.loads(corrige.read_text(encoding="utf-8"))
    tirage = random.Random(graine)

    possibles: list[Question] = []
    for dossier in monde["dossiers"]:
        possibles.extend(_questions_du_dossier(dossier))
    tirage.shuffle(possibles)

    sans_reponse = int(nombre * part_sans_reponse)
    jeu = possibles[: nombre - sans_reponse]
    jeu.extend(questions_sans_reponse(monde, sans_reponse, tirage))
    tirage.shuffle(jeu)
    return jeu
