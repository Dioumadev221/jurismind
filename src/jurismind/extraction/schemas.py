"""Ce que JurisMind cherche à extraire, selon le type d'acte.

Chaque schéma est un modèle Pydantic : il sert à la fois de **consigne** pour le modèle
(les descriptions de champs valent mieux qu'un long prompt), de **contrôle** (un montant
doit être un entier, une date une date) et de **contrat** pour le reste du produit.

Tous les champs sont facultatifs : un acte incomplet, ou un scan mal lu, doit produire une
extraction partielle plutôt qu'une invention.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ActeJuridique(BaseModel):
    """Champs communs à tous les actes."""

    date_acte: date | None = Field(default=None, description="Date figurant sur l'acte, au format AAAA-MM-JJ")


class Facture(ActeJuridique):
    numero: str | None = Field(default=None, description="Numéro de la facture, ex. FA-2025-978")
    emetteur: str | None = Field(default=None, description="Société qui émet la facture")
    destinataire: str | None = Field(default=None, description="Client facturé (« Doit : … »)")
    montant_total_fcfa: int | None = Field(
        default=None, description="Montant total TTC en francs CFA, sans espaces ni devise"
    )
    delai_paiement_jours: int | None = Field(default=None, description="Délai de paiement accordé, en jours")


class MiseEnDemeure(ActeJuridique):
    expediteur: str | None = Field(default=None, description="Cabinet ou société qui met en demeure")
    destinataire: str | None = Field(default=None, description="Personne mise en demeure")
    creancier: str | None = Field(default=None, description="Client pour le compte duquel on agit")
    montant_reclame_fcfa: int | None = Field(default=None, description="Somme réclamée en FCFA")
    delai_jours: int | None = Field(default=None, description="Délai accordé pour payer, en jours")
    factures: list[str] = Field(default_factory=list, description="Numéros des factures impayées visées")


class OrdonnanceInjonctionDePayer(ActeJuridique):
    numero: str | None = Field(default=None, description="Numéro de l'ordonnance, ex. 1703/2022")
    juridiction: str | None = Field(default=None, description="Tribunal qui a rendu l'ordonnance")
    creancier: str | None = Field(default=None, description="Celui à qui la somme doit être payée")
    debiteur: str | None = Field(default=None, description="Celui qui est condamné à payer")
    montant_fcfa: int | None = Field(default=None, description="Somme en principal, en FCFA")
    delai_opposition_jours: int | None = Field(
        default=None, description="Délai pour former opposition, en jours"
    )


class PvSignification(ActeJuridique):
    huissier: str | None = Field(default=None, description="Huissier de justice instrumentaire")
    destinataire: str | None = Field(default=None, description="Personne à qui l'acte est signifié")
    acte_signifie: str | None = Field(default=None, description="Acte signifié, ex. ordonnance n° …")
    date_signification: date | None = Field(default=None, description="Date de la signification")
    delai_opposition_jours: int | None = Field(
        default=None, description="Délai pour former opposition, en jours"
    )


class Contrat(ActeJuridique):
    type_contrat: str | None = Field(
        default=None, description="Objet du contrat : distribution, prestation, fourniture…"
    )
    parties: list[str] = Field(default_factory=list, description="Sociétés signataires")
    duree_mois: int | None = Field(default=None, description="Durée du contrat, en mois")
    montant_annuel_fcfa: int | None = Field(default=None, description="Montant annuel en FCFA")
    preavis_resiliation_jours: int | None = Field(
        default=None, description="Préavis de résiliation, en jours"
    )
    penalite_retard: str | None = Field(default=None, description="Pénalité de retard prévue")
    reglement_litiges: str | None = Field(
        default=None, description="Juridiction compétente ou arbitrage prévu"
    )
    exclusivite: bool | None = Field(default=None, description="Le contrat prévoit-il une exclusivité ?")


class Jugement(ActeJuridique):
    juridiction: str | None = Field(default=None, description="Juridiction qui a statué")
    numero_rg: str | None = Field(default=None, description="Numéro de rôle, ex. RG n° 4832/2024")
    demandeur: str | None = Field(default=None, description="Partie demanderesse")
    defendeur: str | None = Field(default=None, description="Partie défenderesse")
    dispositif: str | None = Field(default=None, description="Ce que le tribunal décide, en une phrase")
    montant_alloue_fcfa: int | None = Field(default=None, description="Somme allouée, en FCFA")


class BailCommercial(ActeJuridique):
    bailleur: str | None = Field(default=None, description="Propriétaire qui donne à bail")
    preneur: str | None = Field(default=None, description="Locataire")
    local: str | None = Field(default=None, description="Local loué")
    loyer_mensuel_fcfa: int | None = Field(default=None, description="Loyer mensuel en FCFA")
    depot_garantie_fcfa: int | None = Field(default=None, description="Dépôt de garantie en FCFA")
    duree_annees: int | None = Field(default=None, description="Durée du bail, en années")


class Statuts(ActeJuridique):
    denomination: str | None = Field(default=None, description="Dénomination sociale")
    forme_juridique: str | None = Field(default=None, description="SARL, SA, SUARL, GIE…")
    capital_fcfa: int | None = Field(default=None, description="Capital social en FCFA")
    siege: str | None = Field(default=None, description="Adresse du siège social")
    gerant: str | None = Field(default=None, description="Gérant ou représentant légal")
    objet: str | None = Field(default=None, description="Objet social, en une phrase")


# Catégorie du document (celle du cabinet, ou celle détectée) → schéma à appliquer.
SCHEMAS: dict[str, type[ActeJuridique]] = {
    "FACTURE": Facture,
    "MISE_EN_DEMEURE": MiseEnDemeure,
    "ORDONNANCE_IP": OrdonnanceInjonctionDePayer,
    "ORDONNANCE_EXECUTOIRE": OrdonnanceInjonctionDePayer,
    "PV_SIGNIFICATION": PvSignification,
    "CONTRAT": Contrat,
    "PROJET_CONTRAT": Contrat,
    "JUGEMENT": Jugement,
    "ORDONNANCE_REFERE": Jugement,
    "BAIL": BailCommercial,
    "STATUTS": Statuts,
    "PROJET_STATUTS": Statuts,
}

NOMS_DE_SCHEMA = {schema.__name__: schema for schema in SCHEMAS.values()}


def schema_pour(categorie: str | None) -> type[ActeJuridique] | None:
    """Schéma correspondant à une catégorie de document, s'il en existe un."""
    return SCHEMAS.get((categorie or "").strip().upper())


def categories_extractibles() -> list[str]:
    return sorted(SCHEMAS)
