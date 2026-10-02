"""Extraction de données structurées depuis un acte juridique.

Deux principes repris du RAG :

- **Le modèle propose, le code vérifie.** Chaque valeur chiffrée (montant, délai, date)
  doit se retrouver dans le texte du document ; sinon le champ est signalé comme douteux.
- **Rien n'est validé automatiquement.** Une extraction est une proposition : un avocat la
  relit et la valide (F5, et matrice des droits du §3.1 de la conception).

L'extraction tourne avec le modèle « qualité », en tâche de fond : sur une machine sans
carte graphique, elle prend plusieurs dizaines de secondes par document.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.core.config import get_settings
from jurismind.db.models import Document, Dossier, Extraction, StatutExtraction, StatutTraitement
from jurismind.extraction.schemas import ActeJuridique, schema_pour
from jurismind.llm import Vitesse, modele_chat

logger = logging.getLogger(__name__)

# Un acte tient rarement en plus de quelques pages ; au-delà, le début et la fin suffisent
# (en-tête, parties, montants, dispositif) et le modèle reste rapide sur CPU.
CARACTERES_MAX = 6000

CONSIGNE = """Tu extrais des informations d'un acte juridique sénégalais (droit OHADA).

Acte ({categorie}) :
{texte}

Champs à renseigner :
{champs}

Renvoie uniquement un objet JSON contenant TOUS ces champs.
- Les montants sont des nombres entiers, sans espaces ni devise : « 13 750 000 FCFA » -> 13750000.
- Les dates sont au format AAAA-MM-JJ.
- Mets null pour tout champ absent de l'acte. N'invente jamais une valeur.
"""

TYPES_LISIBLES = {"integer": "entier", "string": "texte", "boolean": "oui/non", "array": "liste"}


@dataclass
class Proposition:
    """Ce que l'IA propose pour un document, avant relecture humaine."""

    schema: str
    donnees: dict[str, Any]
    champs_douteux: list[str]
    modele: str

    @property
    def champs_remplis(self) -> int:
        return sum(1 for valeur in self.donnees.values() if valeur not in (None, [], ""))


def champs_attendus(schema: type[ActeJuridique]) -> str:
    """Liste des champs et de leur description, tirée du schéma : pas de consigne en double."""
    lignes = []
    for nom, champ in schema.model_fields.items():
        json_schema = schema.model_json_schema()["properties"][nom]
        types = json_schema.get("anyOf", [json_schema])
        type_lisible = next(
            (TYPES_LISIBLES[t["type"]] for t in types if t.get("type") in TYPES_LISIBLES), "texte"
        )
        lignes.append(f"- {nom} ({type_lisible}) : {champ.description or nom}")
    return "\n".join(lignes)


def _entier(valeur: Any) -> int | None:
    """« 13 750 000 FCFA » ou « 13.750.000 » deviennent 13750000."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        return valeur
    chiffres = re.sub(r"\D", "", str(valeur or ""))
    return int(chiffres) if chiffres else None


def _date(valeur: Any) -> str | None:
    """Accepte AAAA-MM-JJ et JJ/MM/AAAA, les deux écritures que produisent les modèles."""
    brut = str(valeur or "").strip()
    for motif in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            # Une date d'acte n'a pas de fuseau : c'est une date civile, pas un instant.
            return datetime.strptime(brut[:10], motif).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return None


def convertir(schema: type[ActeJuridique], donnees: dict[str, Any]) -> dict[str, Any]:
    """Met les valeurs du modèle dans la forme attendue par le schéma, sans rien inventer."""
    propres: dict[str, Any] = {}
    proprietes = schema.model_json_schema()["properties"]
    for nom in schema.model_fields:
        valeur = donnees.get(nom)
        if valeur in (None, "", "null", [], {}):
            continue
        json_schema = proprietes[nom]
        types = {t.get("type") for t in json_schema.get("anyOf", [json_schema])}
        if "integer" in types:
            propres[nom] = _entier(valeur)
        elif "string" in types and json_schema.get("format") == "date" or nom.startswith("date_"):
            propres[nom] = _date(valeur)
        elif "array" in types:
            propres[nom] = valeur if isinstance(valeur, list) else [str(valeur)]
        elif "boolean" in types:
            propres[nom] = (
                valeur if isinstance(valeur, bool) else str(valeur).lower() in {"oui", "true", "vrai"}
            )
        else:
            propres[nom] = str(valeur).strip()
    return {nom: valeur for nom, valeur in propres.items() if valeur is not None}


def texte_utile(document: Document) -> str:
    """Texte soumis au modèle : début et fin de l'acte si celui-ci est long."""
    texte = (document.texte or "").strip()
    if len(texte) <= CARACTERES_MAX:
        return texte
    moitie = CARACTERES_MAX // 2
    return f"{texte[:moitie]}\n[…]\n{texte[-moitie:]}"


def _chiffres(valeur: Any) -> list[str]:
    """Suites de chiffres d'une valeur extraite : montants, délais, dates."""
    if isinstance(valeur, bool) or valeur is None:
        return []
    if isinstance(valeur, int):
        return [str(valeur)]
    if isinstance(valeur, date):
        return [valeur.strftime("%Y%m%d"), valeur.strftime("%d%m%Y")]
    if isinstance(valeur, list):
        return [chiffre for element in valeur for chiffre in _chiffres(element)]
    return [re.sub(r"\D", "", morceau) for morceau in re.findall(r"[\d  .,/-]*\d", str(valeur))]


def champs_douteux(donnees: dict[str, Any], texte: str) -> list[str]:
    """Champs dont les chiffres ne se retrouvent pas dans l'acte : à faire relire en priorité."""
    chiffres_du_texte = re.sub(r"\D", "", texte)
    douteux = []
    for champ, valeur in donnees.items():
        attendus = [chiffre for chiffre in _chiffres(valeur) if len(chiffre) >= 2]
        if attendus and not any(chiffre in chiffres_du_texte for chiffre in attendus):
            douteux.append(champ)
    return douteux


def extraire(document: Document, vitesse: Vitesse = Vitesse.QUALITE) -> Proposition | None:
    """Applique le schéma correspondant au document et vérifie les valeurs chiffrées."""
    categorie = document.categorie_detectee or document.categorie_source
    schema = schema_pour(categorie)
    if schema is None:
        logger.debug("Aucun schéma pour la catégorie %r", categorie)
        return None

    texte = texte_utile(document)
    if not texte:
        logger.info("Document %s sans texte : ingestion à refaire", document.id)
        return None

    reglages = get_settings()
    invite = CONSIGNE.format(categorie=categorie, texte=texte, champs=champs_attendus(schema))
    # JSON libre plutôt que « structured output » : sur un modèle local, la génération
    # contrainte par un schéma fait perdre des champs (montants manquants constatés).
    brut = str(modele_chat(vitesse, json=True).invoke(invite).content)
    try:
        proposees = json.loads(brut)
    except ValueError:
        logger.warning("Réponse illisible pour le document %s : %r", document.id, brut[:160])
        return None

    acte = schema.model_validate(convertir(schema, proposees))
    donnees = acte.model_dump(mode="json", exclude_none=False)
    return Proposition(
        schema=schema.__name__,
        donnees=donnees,
        champs_douteux=champs_douteux(acte.model_dump(), texte),
        modele=reglages.modele_qualite if vitesse is Vitesse.QUALITE else reglages.modele_rapide,
    )


def enregistrer(session: Session, document: Document, proposition: Proposition) -> Extraction:
    """Remplace la proposition précédente pour ce document et ce schéma."""
    existante = session.scalars(
        select(Extraction).where(
            Extraction.document_id == document.id, Extraction.schema == proposition.schema
        )
    ).first()

    if existante is not None and existante.statut is StatutExtraction.VALIDEE:
        # Une extraction validée par un avocat fait foi : l'IA ne l'écrase pas.
        logger.info("Extraction déjà validée pour le document %s : conservée", document.id)
        return existante

    extraction = existante or Extraction(document_id=document.id, schema=proposition.schema)
    extraction.donnees = proposition.donnees
    extraction.champs_douteux = proposition.champs_douteux
    extraction.modele = proposition.modele
    extraction.statut = StatutExtraction.PROPOSEE
    if existante is None:
        session.add(extraction)
    return extraction


def valider(
    session: Session, extraction: Extraction, utilisateur_id: int, corrections: dict[str, Any] | None = None
) -> Extraction:
    """Un avocat relit : il corrige si besoin, puis valide. C'est cette version qui fait foi."""
    if corrections:
        extraction.donnees = {**extraction.donnees, **corrections}
        extraction.champs_douteux = [champ for champ in extraction.champs_douteux if champ not in corrections]
    extraction.statut = StatutExtraction.VALIDEE
    extraction.valide_par_id = utilisateur_id
    extraction.valide_le = datetime.now(UTC)
    return extraction


def documents_a_extraire(
    session: Session, limite: int | None = None, dossier: str | None = None
) -> list[Document]:
    """Documents lus, dont la catégorie a un schéma, et sans proposition à jour.

    `dossier` restreint à une référence : c'est ce qu'on veut en exploitation quand un
    dossier vient de bouger, plutôt que de relancer une campagne complète.
    """
    deja_faits = select(Extraction.document_id)
    requete = (
        select(Document)
        .where(
            Document.statut_traitement == StatutTraitement.TRAITE,
            Document.texte.is_not(None),
            Document.id.not_in(deja_faits),
        )
        .order_by(Document.id)
    )
    if dossier:
        requete = requete.join(Dossier, Document.dossier_id == Dossier.id).where(Dossier.reference == dossier)
    documents = [
        document
        for document in session.scalars(requete)
        if schema_pour(document.categorie_detectee or document.categorie_source)
    ]
    return documents[:limite] if limite else documents
