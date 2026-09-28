"""Connecteur vers le logiciel de gestion du cabinet (base `legacy`).

Rôle : traduire le monde de l'ancien logiciel (codes `PM`, `EC`, `CTX`, champs vides,
téléphones saisis de quatre façons, fiches clients en double) vers le modèle propre de
JurisMind. Aucune de ces conventions ne doit franchir ce fichier.

La synchronisation est **idempotente** : la relancer ne crée pas de doublon, elle met à
jour ce qui a changé. Le lien avec la source est gardé dans `external_id`.

Usage : uv run python -m jurismind.connectors.legacy
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from jurismind.db.base import Base
from jurismind.db.models import (
    AccesDossier,
    AliasClient,
    Canal,
    Client,
    Communication,
    Contact,
    Document,
    Dossier,
    Partie,
    QualitePartie,
    Role,
    SensEchange,
    StatutDossier,
    TypeClient,
    TypeDossier,
    Utilisateur,
)
from jurismind.db.models.documents import pieces_jointes
from jurismind.db.session import get_engine, get_legacy_engine

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- traductions

TYPES_CLIENT = {"PM": TypeClient.SOCIETE, "PP": TypeClient.PARTICULIER}
TYPES_DOSSIER = {"CTX": TypeDossier.CONTENTIEUX, "CSL": TypeDossier.CONSEIL}
STATUTS_DOSSIER = {
    "EC": StatutDossier.EN_COURS,
    "CL": StatutDossier.CLOS,
    "AR": StatutDossier.ARCHIVE,
}
QUALITES = {
    "ADV": QualitePartie.ADVERSE,
    "AVADV": QualitePartie.AVOCAT_ADVERSE,
    "HUIS": QualitePartie.HUISSIER,
    "TIERS": QualitePartie.TIERS,
}
SENS = {"E": SensEchange.ENTRANT, "S": SensEchange.SORTANT, "I": SensEchange.INTERNE}
CANAUX = {"MAIL": Canal.EMAIL, "COURRIER": Canal.COURRIER, "TEL": Canal.TELEPHONE}
# Le cabinet distingue associés, collaborateurs, juristes et assistantes ;
# JurisMind ne connaît que trois rôles (voir la matrice des droits).
ROLES = {
    "ASSOCIE": Role.AVOCAT,
    "COLLAB": Role.AVOCAT,
    "JURISTE": Role.AVOCAT,
    "ASSIST": Role.ASSISTANT,
}
# Tant que l'authentification n'existe pas, aucun compte importé ne peut se connecter.
SANS_MOT_DE_PASSE = "!"

Ligne = Mapping[str, Any]


class DonneeIllisible(ValueError):
    """Une valeur de la base d'origine ne correspond à rien de connu."""


def _traduire(table: Mapping[str, Any], code: Any, champ: str) -> Any:
    valeur = table.get(str(code).strip().upper()) if code is not None else None
    if valeur is None:
        raise DonneeIllisible(f"{champ} : code inconnu {code!r} (attendu : {', '.join(table)})")
    return valeur


def texte(valeur: Any, longueur: int | None = None) -> str | None:
    """Nettoie une chaîne : les blancs et les chaînes vides deviennent `None`."""
    if valeur is None:
        return None
    nettoye = " ".join(str(valeur).split())
    if not nettoye:
        return None
    return nettoye[:longueur] if longueur else nettoye


def telephone(valeur: Any) -> str | None:
    """Ramène les quatre formats de saisie du cabinet à `+221XXXXXXXXX`."""
    brut = texte(valeur)
    if brut is None:
        return None
    chiffres = re.sub(r"\D", "", brut)
    for indicatif in ("00221", "221"):
        if chiffres.startswith(indicatif) and len(chiffres) > 9:
            chiffres = chiffres[len(indicatif) :]
            break
    if len(chiffres) != 9:
        logger.debug("Téléphone inexploitable : %r", brut)
        return None
    return f"+221{chiffres}"


def normaliser(valeur: str) -> str:
    """Forme comparable d'un nom : sans accents, sans ponctuation, en minuscules."""
    sans_accent = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", sans_accent.lower()).split())


def cle_identite(ligne: Ligne) -> str:
    """Clé permettant de reconnaître deux fiches d'un même client.

    Prudence volontaire : on préfère garder deux fiches d'un même client (corrigeable
    ensuite) plutôt que fusionner deux clients différents (faute de confidentialité).
    - le RCCM est un identifiant officiel : deux fiches qui le partagent sont la même société ;
    - sans RCCM, une société est reconnue par sa dénomination complète et sa ville ;
    - un particulier n'est rapproché que si son nom ET un moyen de contact coïncident,
      car « Cissé » ou « Samb » désignent des dizaines de clients différents.
    """
    rccm = texte(ligne["cli_rccm"])
    if rccm:
        return f"rccm:{normaliser(rccm)}"

    if str(ligne["cli_type"]).strip().upper() == "PM":
        denomination = normaliser(texte(ligne["cli_raison_soc"]) or "")
        return f"pm:{denomination}:{normaliser(texte(ligne['cli_ville']) or '')}"

    nom = normaliser(" ".join(filter(None, (texte(ligne["cli_prenom"]), texte(ligne["cli_nom"])))))
    contact = telephone(ligne["cli_tel"]) or (texte(ligne["cli_email"]) or "").lower()
    if not nom or not contact:
        return f"fiche:{ligne['cli_id']}"  # trop peu d'informations : on ne fusionne pas
    return f"pp:{nom}:{contact}"


# --------------------------------------------------------------------------- conversions


def convertir_avocat(ligne: Ligne) -> Utilisateur:
    prenom = texte(ligne["av_prenom"]) or ""
    nom = texte(ligne["av_nom"]) or ""
    return Utilisateur(
        external_id=ligne["av_id"],
        email=(texte(ligne["av_email"]) or f"inconnu-{ligne['av_id']}@cabinet.invalid").lower(),
        nom_complet=f"{prenom} {nom}".strip(),
        mot_de_passe_hash=SANS_MOT_DE_PASSE,
        role=_traduire(ROLES, ligne["av_fonction"], "AV_FONCTION"),
        actif=str(ligne["av_actif"]).upper() != "N",
    )


def convertir_client(ligne: Ligne) -> Client:
    type_client = _traduire(TYPES_CLIENT, ligne["cli_type"], "CLI_TYPE")
    if type_client is TypeClient.SOCIETE:
        nom = texte(ligne["cli_raison_soc"]) or f"Client {ligne['cli_code']}"
    else:
        nom = " ".join(filter(None, (texte(ligne["cli_prenom"]), texte(ligne["cli_nom"])))) or (
            f"Client {ligne['cli_code']}"
        )
    societe = type_client is TypeClient.SOCIETE
    return Client(
        external_id=ligne["cli_id"],
        type=type_client,
        nom=texte(nom, 200) or "",
        forme_juridique=texte(ligne["cli_forme"], 20) if societe else None,
        rccm=texte(ligne["cli_rccm"], 40),
        ninea=texte(ligne["cli_ninea"], 20) if societe else None,
        adresse=texte(ligne["cli_adresse"], 250),
        ville=texte(ligne["cli_ville"], 60),
        telephone=telephone(ligne["cli_tel"]),
        email=(texte(ligne["cli_email"], 255) or "").lower() or None,
    )


def convertir_contact(ligne: Ligne) -> Contact:
    return Contact(
        external_id=ligne["ct_id"],
        prenom=texte(ligne["ct_prenom"], 60),
        nom=texte(ligne["ct_nom"], 60) or "",
        fonction=texte(ligne["ct_fonction"], 80),
        email=(texte(ligne["ct_email"], 255) or "").lower() or None,
        telephone=telephone(ligne["ct_tel"]),
    )


def convertir_dossier(ligne: Ligne) -> Dossier:
    statut = _traduire(STATUTS_DOSSIER, ligne["dos_statut"], "DOS_STATUT")
    cloture = ligne["dos_dt_clo"]
    # Un dossier clos sans date de clôture : défaut de saisie fréquent, on prend l'ouverture.
    if statut is not StatutDossier.EN_COURS and cloture is None:
        cloture = ligne["dos_dt_ouv"]
    return Dossier(
        external_id=ligne["dos_id"],
        reference=texte(ligne["dos_num"], 20) or f"D-{ligne['dos_id']}",
        intitule=texte(ligne["dos_intitule"], 300) or "Sans intitulé",
        type=_traduire(TYPES_DOSSIER, ligne["dos_type"], "DOS_TYPE"),
        matiere=texte(ligne["dos_matiere"], 30) or "AUTRE",
        statut=statut,
        date_ouverture=ligne["dos_dt_ouv"],
        date_cloture=cloture,
        juridiction=texte(ligne["dos_juridiction"], 150),
        numero_rg=texte(ligne["dos_num_rg"], 40),
        enjeu_fcfa=int(ligne["dos_enjeu"]) if ligne["dos_enjeu"] is not None else None,
        confidentiel=str(ligne["dos_confidentiel"]).upper() == "O",
    )


def convertir_partie(ligne: Ligne) -> Partie:
    return Partie(
        external_id=ligne["int_id"],
        qualite=_traduire(QUALITES, ligne["int_qualite"], "INT_QUALITE"),
        nom=texte(ligne["int_nom"], 200) or "Inconnu",
        adresse=texte(ligne["int_adresse"], 250),
        email=(texte(ligne["int_email"], 255) or "").lower() or None,
        telephone=telephone(ligne["int_tel"]),
    )


def convertir_document(ligne: Ligne) -> Document:
    chemin = texte(ligne["doc_fichier"], 500) or ""
    _, _, extension = chemin.rpartition(".")
    return Document(
        external_id=ligne["doc_id"],
        titre=texte(ligne["doc_libelle"], 300) or "Sans titre",
        # La catégorie saisie dans le cabinet est parfois « DIVERS » ou fausse :
        # l'IA proposera la sienne dans `categorie_detectee` (F8).
        categorie_source=texte(ligne["doc_categ"], 40),
        sens=_traduire(SENS, ligne["doc_sens"], "DOC_SENS"),
        date_document=ligne["doc_dt"],
        auteur=texte(ligne["doc_auteur"], 200),
        chemin_fichier=chemin,
        format=(extension or "inconnu").lower()[:10],
    )


def convertir_communication(ligne: Ligne) -> Communication:
    destinataires = [
        adresse for adresse in (texte(part) for part in str(ligne["cor_dest"] or "").split(";")) if adresse
    ]
    return Communication(
        external_id=ligne["cor_id"],
        canal=_traduire(CANAUX, ligne["cor_type"], "COR_TYPE"),
        sens=_traduire(SENS, ligne["cor_sens"], "COR_SENS"),
        date_echange=ligne["cor_date"],
        expediteur=texte(ligne["cor_exped"], 255) or "inconnu",
        destinataires=destinataires,
        objet=texte(ligne["cor_objet"], 300),
        corps=str(ligne["cor_corps"] or ""),
    )


def pieces_jointes_de(ligne: Ligne) -> list[int]:
    """`COR_PJ` entasse les documents joints dans une seule case : « 180;181;182 »."""
    return [int(part) for part in str(ligne["cor_pj"] or "").split(";") if part.strip().isdigit()]


# --------------------------------------------------------------------------- doublons


def choisir_fiche_principale(fiches: Sequence[Ligne]) -> Ligne:
    """Entre plusieurs fiches d'un même client, garde la plus complète, puis la plus ancienne."""

    def richesse(ligne: Ligne) -> tuple[int, int]:
        remplis = sum(1 for champ in ("cli_ninea", "cli_email", "cli_rccm", "cli_tel") if texte(ligne[champ]))
        return (remplis, -int(ligne["cli_id"]))

    return max(fiches, key=richesse)


def regrouper_doublons(lignes: Sequence[Ligne]) -> dict[int, list[Ligne]]:
    """Regroupe les fiches clients par identité réelle ; la clé du résultat est la fiche retenue."""
    groupes: dict[str, list[Ligne]] = {}
    for ligne in lignes:
        groupes.setdefault(cle_identite(ligne), []).append(ligne)
    return {int(choisir_fiche_principale(g)["cli_id"]): g for g in groupes.values()}


# --------------------------------------------------------------------------- synchronisation

REQUETES = {
    "avocats": "SELECT * FROM t_avocat",
    "clients": "SELECT * FROM t_client",
    "contacts": "SELECT * FROM t_contact",
    "dossiers": "SELECT * FROM t_dossier",
    "equipes": "SELECT * FROM t_dossier_avocat",
    "intervenants": "SELECT * FROM t_intervenant",
    "documents": "SELECT * FROM t_document",
    "correspondances": "SELECT * FROM t_correspondance",
}

M = TypeVar("M", bound=Base)


@dataclass
class Bilan:
    """Ce que la synchronisation a fait, pour l'afficher et pour le journal."""

    crees: dict[str, int] = field(default_factory=dict)
    mis_a_jour: dict[str, int] = field(default_factory=dict)
    ignores: dict[str, int] = field(default_factory=dict)
    doublons_fusionnes: int = 0

    def compter(self, table: str, cree: bool) -> None:
        cible = self.crees if cree else self.mis_a_jour
        cible[table] = cible.get(table, 0) + 1

    def ignorer(self, table: str) -> None:
        self.ignores[table] = self.ignores.get(table, 0) + 1

    def total(self, table: str) -> int:
        return self.crees.get(table, 0) + self.mis_a_jour.get(table, 0)


COLONNES_TECHNIQUES = {"id", "cree_le", "modifie_le"}


def reference(objet: Base) -> int | None:
    """Identifiant de la ligne dans la base d'origine (`external_id`), s'il existe."""
    return getattr(objet, "external_id", None)


def champs_renseignes(objet: Base) -> set[str]:
    """Colonnes explicitement données à la construction de l'objet (les autres sont absentes)."""
    colonnes = {colonne.name for colonne in objet.__table__.columns}
    return {champ for champ in vars(objet) if champ in colonnes} - COLONNES_TECHNIQUES


class Synchronisation:
    """Copie la base du cabinet dans JurisMind, en une transaction, de façon rejouable."""

    def __init__(self, session: Session, bilan: Bilan | None = None) -> None:
        self.session = session
        self.bilan = bilan or Bilan()

    def _existants(self, modele: type[M]) -> dict[int, M]:
        objets = self.session.scalars(select(modele)).all()
        return {ref: objet for objet in objets if (ref := reference(objet)) is not None}

    def _appliquer(self, table: str, existants: dict[int, M], nouveau: M) -> M:
        """Insère la ligne, ou met à jour celle déjà importée (même `external_id`).

        Seules les colonnes que le connecteur a renseignées sont recopiées : les colonnes
        remplies plus tard par l'ingestion ou par l'IA (texte, empreinte, catégorie détectée,
        vecteurs…) appartiennent à ces traitements et ne doivent jamais être écrasées ici.
        """
        ref = reference(nouveau)
        assert ref is not None, f"{table} : ligne sans external_id"
        ancien = existants.get(ref)
        if ancien is None:
            self.session.add(nouveau)
            existants[ref] = nouveau
            self.bilan.compter(table, cree=True)
            return nouveau
        for champ in champs_renseignes(nouveau):
            setattr(ancien, champ, getattr(nouveau, champ))
        self.bilan.compter(table, cree=False)
        return ancien

    def executer(self, source: Engine) -> Bilan:
        with source.connect() as connexion:
            donnees = {
                nom: [dict(ligne._mapping) for ligne in connexion.execute(text(requete)).all()]
                for nom, requete in REQUETES.items()
            }

        utilisateurs = self._utilisateurs(donnees["avocats"])
        clients = self._clients(donnees["clients"])
        self._contacts(donnees["contacts"], clients)
        dossiers = self._dossiers(donnees["dossiers"], clients)
        self._equipes(donnees["equipes"], dossiers, utilisateurs)
        self._parties(donnees["intervenants"], dossiers)
        documents = self._documents(donnees["documents"], dossiers)
        self._communications(donnees["correspondances"], dossiers, documents)
        self.session.flush()
        return self.bilan

    # -- table par table ---------------------------------------------------

    def _utilisateurs(self, lignes: Sequence[Ligne]) -> dict[int, Utilisateur]:
        existants = self._existants(Utilisateur)
        for ligne in lignes:
            self._appliquer("utilisateurs", existants, convertir_avocat(ligne))
        self.session.flush()
        return existants

    def _clients(self, lignes: Sequence[Ligne]) -> dict[int, Client]:
        groupes = regrouper_doublons(lignes)
        existants = self._existants(Client)
        alias: dict[int, Client] = {}
        for id_principal, fiches in groupes.items():
            principale = next(f for f in fiches if int(f["cli_id"]) == id_principal)
            client = self._appliquer("clients", existants, convertir_client(principale))
            for fiche in fiches:
                alias[int(fiche["cli_id"])] = client
            self.bilan.doublons_fusionnes += len(fiches) - 1
        self.session.flush()
        self._enregistrer_alias(alias)
        return alias

    def _enregistrer_alias(self, alias: Mapping[int, Client]) -> None:
        """Garde la trace des fiches en double, pour que la synchronisation reste rejouable."""
        connus = {a.external_id for a in self.session.scalars(select(AliasClient)).all()}
        for external_id, client in alias.items():
            if external_id not in connus:
                self.session.add(AliasClient(external_id=external_id, client_id=client.id))
        self.session.flush()

    def _contacts(self, lignes: Sequence[Ligne], clients: Mapping[int, Client]) -> None:
        existants = self._existants(Contact)
        for ligne in lignes:
            client = clients.get(int(ligne["cli_id"]))
            if client is None:
                self.bilan.ignorer("contacts")
                continue
            contact = convertir_contact(ligne)
            contact.client_id = client.id
            self._appliquer("contacts", existants, contact)
        self.session.flush()

    def _dossiers(self, lignes: Sequence[Ligne], clients: Mapping[int, Client]) -> dict[int, Dossier]:
        existants = self._existants(Dossier)
        for ligne in lignes:
            client = clients.get(int(ligne["cli_id"]))
            if client is None:
                self.bilan.ignorer("dossiers")
                continue
            dossier = convertir_dossier(ligne)
            dossier.client_id = client.id
            self._appliquer("dossiers", existants, dossier)
        self.session.flush()
        return existants

    def _equipes(
        self,
        lignes: Sequence[Ligne],
        dossiers: Mapping[int, Dossier],
        utilisateurs: Mapping[int, Utilisateur],
    ) -> None:
        """Les accès n'ont pas d'identifiant d'origine : on les réécrit entièrement."""
        self.session.execute(delete(AccesDossier))
        vus: set[tuple[int, int]] = set()
        for ligne in lignes:
            dossier = dossiers.get(int(ligne["dos_id"]))
            utilisateur = utilisateurs.get(int(ligne["av_id"]))
            if dossier is None or utilisateur is None:
                self.bilan.ignorer("acces_dossiers")
                continue
            if (dossier.id, utilisateur.id) in vus:
                continue
            vus.add((dossier.id, utilisateur.id))
            self.session.add(
                AccesDossier(
                    dossier_id=dossier.id,
                    utilisateur_id=utilisateur.id,
                    est_responsable=str(ligne["da_role"]).upper() == "RESP",
                )
            )
            self.bilan.compter("acces_dossiers", cree=True)
        self.session.flush()

    def _parties(self, lignes: Sequence[Ligne], dossiers: Mapping[int, Dossier]) -> None:
        existants = self._existants(Partie)
        for ligne in lignes:
            dossier = dossiers.get(int(ligne["dos_id"]))
            if dossier is None:
                self.bilan.ignorer("parties")
                continue
            partie = convertir_partie(ligne)
            partie.dossier_id = dossier.id
            self._appliquer("parties", existants, partie)
        self.session.flush()

    def _documents(self, lignes: Sequence[Ligne], dossiers: Mapping[int, Dossier]) -> dict[int, Document]:
        existants = self._existants(Document)
        for ligne in lignes:
            dossier = dossiers.get(int(ligne["dos_id"]))
            if dossier is None:
                self.bilan.ignorer("documents")
                continue
            document = convertir_document(ligne)
            document.dossier_id = dossier.id
            self._appliquer("documents", existants, document)
        self.session.flush()
        return existants

    def _communications(
        self,
        lignes: Sequence[Ligne],
        dossiers: Mapping[int, Dossier],
        documents: Mapping[int, Document],
    ) -> None:
        existants = self._existants(Communication)
        liens: list[dict[str, int]] = []
        for ligne in lignes:
            communication = convertir_communication(ligne)
            # `dos_id` vide = email pas encore classé : c'est le travail de l'agent de tri (F9).
            if ligne["dos_id"] is not None:
                dossier = dossiers.get(int(ligne["dos_id"]))
                if dossier is None:
                    self.bilan.ignorer("communications")
                    continue
                communication.dossier_id = dossier.id
            enregistree = self._appliquer("communications", existants, communication)
            self.session.flush()
            for document_externe in pieces_jointes_de(ligne):
                document = documents.get(document_externe)
                if document is not None:
                    liens.append({"communication_id": enregistree.id, "document_id": document.id})
        # Les pièces jointes n'ont pas d'identifiant propre : on les réécrit entièrement.
        self.session.execute(delete(pieces_jointes))
        if liens:
            self.session.execute(pieces_jointes.insert(), liens)


def synchroniser(source: Engine | None = None, cible: Engine | None = None) -> Bilan:
    """Copie tout le logiciel du cabinet dans JurisMind. Rejouable sans créer de doublon."""
    with Session(cible or get_engine()) as session, session.begin():
        return Synchronisation(session).executer(source or get_legacy_engine())
