"""Génère le monde simulé du cabinet de façon reproductible (graine aléatoire)."""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from simulation import referentiels as ref
from simulation.modeles import Avocat, Client, Contact, Correspondance, Dossier, Monde
from simulation.scenarios import SCENARIOS

TAILLES = {"small": 40, "full": 200}  # nombre de clients

MATIERES_PM = {"RECOUV": 35, "COMM": 20, "BAIL": 10, "SOC": 10, "CONTRAT": 25}
MATIERES_PP = {"RECOUV": 10, "COMM": 10, "BAIL": 40, "SOC": 40}


@dataclass
class Tiers:
    nom: str
    adresse: str
    email: str | None
    telephone: str | None


def slug(texte: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return "".join(ch if ch.isalnum() else "-" for ch in ascii_.lower()).strip("-").replace("--", "-")


class Generateur:
    def __init__(self, seed: int, reference: date) -> None:
        self.rng = random.Random(seed)
        self.reference = reference
        self._ids: dict[str, int] = {}
        self._noms_pris: set[str] = set()
        self.juridictions = ref.JURIDICTIONS
        self.banques = ref.BANQUES
        self.secteurs = ref.SECTEURS
        self.prefixes = ref.PREFIXES_SOCIETES
        self.signatures_mobile = ref.SIGNATURES_MOBILE
        self.avocats = self._equipe_cabinet()

    # ------------------------------------------------------------------ outils

    def next_id(self, cle: str) -> int:
        self._ids[cle] = self._ids.get(cle, 0) + 1
        return self._ids[cle]

    def telephone(self, fixe: bool = False) -> str:
        r = self.rng
        prefixe = "33" if fixe else r.choice(["77", "78", "76", "70", "75"])
        return f"+221 {prefixe} {r.randint(100, 999)} {r.randint(10, 99)} {r.randint(10, 99)}"

    def personne(self, femme: bool | None = None) -> str:
        r = self.rng
        femme = r.random() < 0.45 if femme is None else femme
        return f"{r.choice(ref.PRENOMS_F if femme else ref.PRENOMS_H)} {r.choice(ref.NOMS)}"

    def adresse(self, ville: str) -> str:
        r = self.rng
        if ville == "Dakar":
            return f"{r.randint(1, 120)} {r.choice(ref.RUES)}, {r.choice(ref.QUARTIERS_DAKAR)}, Dakar"
        return f"Quartier {r.choice(['Escale', 'Centre-ville', 'Médina', 'Diamaguène'])}, {ville}"

    def ville(self) -> str:
        return self.rng.choices(list(ref.VILLES), weights=ref.POIDS_VILLES)[0]

    def nom_societe(self) -> tuple[str, str, str]:
        while True:
            secteur = self.rng.choice(list(ref.SECTEURS))
            forme = self.rng.choice(ref.FORMES_SOCIETES)
            nom = f"{self.rng.choice(ref.PREFIXES_SOCIETES)} {secteur} {forme}"
            if nom not in self._noms_pris:
                self._noms_pris.add(nom)
                return nom, secteur, forme

    def rccm(self, ville: str, annee: int, personne_morale: bool = True) -> str:
        lettre = "B" if personne_morale else "A"
        return f"SN-{ref.VILLES[ville]}-{annee}-{lettre}-{self.rng.randint(1000, 99999)}"

    def ninea(self) -> str:
        return f"00{self.rng.randint(1000000, 9999999)} {self.rng.randint(1, 3)}{self.rng.choice('ABCGV')}{self.rng.randint(1, 3)}"

    def societe_tierce(self) -> Tiers:
        nom, _, _ = self.nom_societe()
        ville = self.ville()
        return Tiers(
            nom,
            self.adresse(ville),
            f"contact@{slug(nom)}.example",
            self.telephone(fixe=True),
        )

    def avocat_adverse(self) -> Tiers:
        nom = self.personne()
        return Tiers(
            f"Me {nom}, Avocat à la Cour",
            self.adresse("Dakar"),
            f"{slug(nom)}@barreau-dakar.example",
            self.telephone(fixe=True),
        )

    def huissier(self) -> Tiers:
        nom = self.personne()
        return Tiers(
            f"Me {nom}, Huissier de justice",
            self.adresse("Dakar"),
            f"etude.{slug(nom)}@huissiers.example",
            self.telephone(fixe=True),
        )

    def avocat(self, avocat_id: int) -> Avocat:
        return next(a for a in self.avocats if a.id == avocat_id)

    def par_fonction(self, fonction: str) -> list[Avocat]:
        return [a for a in self.avocats if a.fonction == fonction]

    def assistante_de(self, associe_id: int) -> Avocat:
        associes = self.par_fonction("ASSOCIE")
        assistantes = self.par_fonction("ASSIST")
        index = next(i for i, a in enumerate(associes) if a.id == associe_id)
        return assistantes[index % len(assistantes)]

    # ------------------------------------------------------------------ cabinet

    def _equipe_cabinet(self) -> list[Avocat]:
        composition = [("ASSOCIE", 2), ("COLLAB", 4), ("JURISTE", 1), ("ASSIST", 2)]
        avocats = []
        for fonction, nombre in composition:
            for _ in range(nombre):
                prenom, nom = self.personne(femme=fonction == "ASSIST" or None).split(" ", 1)
                avocats.append(
                    Avocat(
                        id=self.next_id("avocat"),
                        initiales=(prenom[0] + nom[0]).upper(),
                        prenom=prenom,
                        nom=nom,
                        email=f"{slug(prenom)[0]}.{slug(nom)}@{ref.CABINET_DOMAINE}",
                        fonction=fonction,
                    )
                )
        return avocats

    # ------------------------------------------------------------------ clients

    def client(self) -> Client:
        r = self.rng
        client_id = self.next_id("client")
        ville = self.ville()
        cree = self.reference - timedelta(days=r.randint(400, 3000))
        if r.random() < 0.7:
            nom, secteur, forme = self.nom_societe()
            domaine = f"{slug(nom)}.example"
            c = Client(
                id=client_id,
                code=f"C{client_id:05d}",
                type="PM",
                nom=nom,
                forme=forme,
                secteur=secteur,
                rccm=self.rccm(ville, cree.year - r.randint(0, 15)),
                ninea=self.ninea(),
                adresse=self.adresse(ville),
                ville=ville,
                telephone=self.telephone(fixe=True),
                email=f"contact@{domaine}",
                domaine=domaine,
                date_creation=cree,
            )
            fonctions = [
                "Gérant" if forme in ("SARL", "SUARL") else "Directeur général",
                "Directeur administratif et financier",
                "Responsable juridique",
            ]
            for fonction in fonctions[: r.randint(1, 3)]:
                prenom, nom_p = self.personne().split(" ", 1)
                c.contacts.append(
                    Contact(
                        self.next_id("contact"),
                        client_id,
                        prenom,
                        nom_p,
                        fonction,
                        f"{slug(prenom)}.{slug(nom_p)}@{domaine}",
                        self.telephone(),
                    )
                )
            return c

        prenom, nom_p = self.personne().split(" ", 1)
        email = f"{slug(prenom)}.{slug(nom_p)}{r.randint(1, 99)}@mail.example"
        c = Client(
            id=client_id,
            code=f"C{client_id:05d}",
            type="PP",
            nom=f"{prenom} {nom_p}",
            forme=None,
            secteur=None,
            rccm=self.rccm(ville, cree.year, False) if r.random() < 0.3 else None,
            ninea=None,
            adresse=self.adresse(ville),
            ville=ville,
            telephone=self.telephone(),
            email=email,
            domaine=None,
            date_creation=cree,
        )
        c.contacts.append(
            Contact(
                self.next_id("contact"),
                client_id,
                prenom,
                nom_p,
                "Client",
                email,
                c.telephone,
            )
        )
        return c

    # ------------------------------------------------------------------ dossiers

    def dossier(self, client: Client) -> Dossier:
        r = self.rng
        poids = MATIERES_PM if client.type == "PM" else MATIERES_PP
        matiere = r.choices(list(poids), weights=list(poids.values()))[0]
        type_, scenario = SCENARIOS[matiere]
        # ~45 % de dossiers récents (donc souvent en cours), le reste étalé sur 5 ans d'historique.
        anciennete = r.randint(3, 220) if r.random() < 0.45 else int(r.triangular(220, 1800, 400))
        ouverture = self.reference - timedelta(days=anciennete)
        ouverture = max(ouverture, client.date_creation)
        associe = r.choice(self.par_fonction("ASSOCIE"))
        equipe = [associe.id] + [a.id for a in r.sample(self.par_fonction("COLLAB"), r.randint(1, 2))]
        if r.random() < 0.3:
            equipe.append(self.par_fonction("JURISTE")[0].id)
        confidentiel = r.random() < 0.1
        if not confidentiel:
            equipe.append(self.assistante_de(associe.id).id)
        d = Dossier(
            id=self.next_id("dossier"),
            numero="",
            client_id=client.id,
            intitule="",
            type=type_,
            matiere=matiere,
            statut="EC",
            date_ouverture=ouverture,
            date_cloture=None,
            juridiction=None,
            numero_rg=None,
            enjeu=None,
            confidentiel=confidentiel,
            responsable_id=associe.id,
            equipe_ids=equipe,
        )
        scenario(self, d, client)
        return d

    # ------------------------------------------------------------------ boîte de réception

    def a_trier(self, dossiers: list[Dossier]) -> None:
        """Une partie des emails entrants récents n'est pas encore rattachée à un dossier."""
        limite = self.reference - timedelta(days=30)
        for d in dossiers:
            for c in d.correspondances:
                if c.type == "MAIL" and c.sens == "E" and c.date.date() >= limite and self.rng.random() < 0.4:
                    c.classee = False

    def emails_prospects(self, n: int) -> list[Correspondance]:
        r = self.rng
        associes = self.par_fonction("ASSOCIE")
        mails = []
        demandes = [
            "nous envisageons de créer une filiale au Sénégal et souhaiterions être accompagnés",
            "un de nos clients refuse de payer plusieurs factures, pouvez-vous nous aider ?",
            "nous souhaitons faire relire un contrat de distribution avant signature",
            "je souhaite céder mes parts dans une SARL et j'ai besoin de conseils",
        ]
        for _ in range(n):
            societe = self.societe_tierce()
            nom = self.personne()
            jour = self.reference - timedelta(days=r.randint(0, 20))
            mails.append(
                Correspondance(
                    id=self.next_id("corr"),
                    dossier_id=None,
                    type="MAIL",
                    sens="E",
                    date=datetime.combine(jour, time(r.randint(8, 18), r.randint(0, 59))),
                    expediteur=f"{slug(nom)}@{societe.email.split('@')[1] if societe.email else 'mail.example'}",
                    destinataires=[f"contact@{ref.CABINET_DOMAINE}"],
                    objet="Demande de rendez-vous",
                    corps=f"Bonjour,\n\nJe suis {nom}, de la société {societe.nom}. {r.choice(demandes).capitalize()}. "
                    f"Seriez-vous disponible pour un rendez-vous ?\n\nCordialement,\n{nom}\n{societe.telephone}",
                    classee=False,
                )
            )
            mails[-1].destinataires.append(r.choice(associes).email)
        return mails

    # ------------------------------------------------------------------ CRM

    def crm(
        self,
        clients: list[Client],
        dossiers: list[Dossier],
        prospects: list[Correspondance],
    ) -> dict[str, Any]:
        r = self.rng
        associes = self.par_fonction("ASSOCIE")
        accounts, contacts, opportunities, activities, tasks = [], [], [], [], []

        def iso(d: date | datetime) -> str:
            return d.isoformat()

        def nom_variante(nom: str) -> str:
            # Le CRM a été rempli à la main : noms saisis différemment de la base du cabinet.
            tirage = r.random()
            if tirage < 0.15:
                return nom.upper()
            if tirage < 0.3:
                return nom.rsplit(" ", 1)[0] if nom.split()[-1] in ref.FORMES_SOCIETES else nom
            return nom

        par_client: dict[int, list[Dossier]] = {}
        for d in dossiers:
            par_client.setdefault(d.client_id, []).append(d)

        for c in clients:
            if r.random() > 0.8:
                continue  # client jamais saisi dans le CRM
            acc_id = f"ACC-{self.next_id('crm_acc'):05d}"
            dossiers_c = par_client.get(c.id, [])
            owner = (
                self.avocat(dossiers_c[0].responsable_id).email if dossiers_c else r.choice(associes).email
            )
            accounts.append(
                {
                    "id": acc_id,
                    "name": nom_variante(c.nom),
                    "type": "company" if c.type == "PM" else "person",
                    "industry": c.secteur,
                    "city": c.ville,
                    "phone": c.telephone.replace(" ", ""),
                    "website": f"www.{c.domaine}" if c.domaine else None,
                    "owner": owner,
                    "lifecycle_stage": "client",
                    "ninea": c.ninea if r.random() < 0.5 else None,
                    "created_at": iso(c.date_creation),
                    "updated_at": iso(self.reference - timedelta(days=r.randint(0, 90))),
                }
            )
            for ct in c.contacts:
                if r.random() < 0.85:
                    contacts.append(
                        {
                            "id": f"CT-{self.next_id('crm_ct'):05d}",
                            "account_id": acc_id,
                            "first_name": ct.prenom,
                            "last_name": ct.nom,
                            "title": ct.fonction,
                            "email": ct.email,
                            "phone": ct.telephone,
                        }
                    )
            for d in dossiers_c:
                if r.random() < 0.6:
                    opportunities.append(
                        {
                            "id": f"OPP-{self.next_id('crm_opp'):05d}",
                            "account_id": acc_id,
                            "name": f"Mandat – {d.intitule}",
                            "stage": "gagnee",
                            "amount": r.randrange(500_000, 6_000_000, 250_000),
                            "currency": "XOF",
                            "close_date": iso(d.date_ouverture),
                            "owner": owner,
                        }
                    )
            if r.random() < 0.3:
                opportunities.append(
                    {
                        "id": f"OPP-{self.next_id('crm_opp'):05d}",
                        "account_id": acc_id,
                        "name": r.choice(
                            [
                                "Audit juridique annuel",
                                f"Accompagnement ouverture d'une agence à {self.ville()}",
                                "Mise en conformité des contrats commerciaux",
                                "Recouvrement de portefeuille de créances",
                            ]
                        ),
                        "stage": r.choice(["qualification", "proposition", "negociation"]),
                        "amount": r.randrange(1_000_000, 15_000_000, 500_000),
                        "currency": "XOF",
                        "close_date": iso(self.reference + timedelta(days=r.randint(15, 120))),
                        "owner": owner,
                    }
                )
            interlocuteur = c.interlocuteur
            sujet_dossier = r.choice(dossiers_c).intitule if dossiers_c else None
            notes = [
                f"Point sur le dossier « {sujet_dossier} ». Le client est satisfait du suivi."
                if sujet_dossier
                else "Présentation du cabinet et de nos domaines d'intervention.",
                f"{interlocuteur.nom_complet} s'inquiète des délais de la justice commerciale.",
                (
                    f"{interlocuteur.nom_complet} évoque un projet d'extension à {self.ville()} "
                    "(besoin probable d'un bail commercial et de contrats de travail)."
                ),
                "Le client trouve nos honoraires élevés ; proposer un forfait annuel.",
                (
                    f"Déjeuner avec {interlocuteur.nom_complet}. Envisage de nous confier le recouvrement "
                    "de l'ensemble de ses créances clients."
                ),
            ]
            for note in r.sample(notes, r.randint(1, 4)):
                jour = self.reference - timedelta(days=r.randint(1, 400))
                activities.append(
                    {
                        "id": f"ACT-{self.next_id('crm_act'):05d}",
                        "account_id": acc_id,
                        "type": r.choice(["reunion", "appel", "dejeuner"]),
                        "date": iso(jour),
                        "subject": note.split(".")[0][:80],
                        "note": note,
                        "owner": owner,
                    }
                )
            if r.random() < 0.35:
                tasks.append(
                    {
                        "id": f"TSK-{self.next_id('crm_tsk'):05d}",
                        "account_id": acc_id,
                        "title": r.choice(
                            [
                                f"Relancer {interlocuteur.nom_complet}",
                                "Envoyer la proposition d'honoraires",
                                "Organiser un point trimestriel",
                            ]
                        ),
                        "due_date": iso(self.reference + timedelta(days=r.randint(-10, 30))),
                        "status": r.choice(["ouverte", "ouverte", "terminee"]),
                        "owner": owner,
                    }
                )

        for mail in prospects:  # prospects connus du CRM mais pas encore clients
            societe = mail.corps.split("de la société ")[1].split(".")[0]
            acc_id = f"ACC-{self.next_id('crm_acc'):05d}"
            accounts.append(
                {
                    "id": acc_id,
                    "name": societe,
                    "type": "company",
                    "industry": None,
                    "city": "Dakar",
                    "phone": None,
                    "website": None,
                    "owner": mail.destinataires[-1],
                    "lifecycle_stage": "prospect",
                    "ninea": None,
                    "created_at": iso(mail.date.date()),
                    "updated_at": iso(mail.date.date()),
                }
            )

        return {
            "accounts": accounts,
            "contacts": contacts,
            "opportunities": opportunities,
            "activities": activities,
            "tasks": tasks,
        }


def generer(taille: str = "small", seed: int = 42, reference: date | None = None) -> Monde:
    g = Generateur(seed, reference or date(2026, 9, 19))
    clients = [g.client() for _ in range(TAILLES[taille])]
    dossiers: list[Dossier] = []
    for c in clients:
        for _ in range(g.rng.choices([1, 2, 3, 4], weights=[45, 30, 17, 8])[0]):
            dossiers.append(g.dossier(c))

    # Numérotation du cabinet : D<année>-<séquence> dans l'ordre d'ouverture.
    dossiers.sort(key=lambda d: d.date_ouverture)
    compteurs: dict[int, int] = {}
    for d in dossiers:
        annee = d.date_ouverture.year
        compteurs[annee] = compteurs.get(annee, 0) + 1
        d.numero = f"D{annee}-{compteurs[annee]:04d}"
        for doc in d.documents:
            doc.fichier = f"{d.numero}/{doc.fichier}"

    g.a_trier(dossiers)
    prospects = g.emails_prospects(g.rng.randint(3, 6))
    return Monde(
        reference=g.reference,
        avocats=g.avocats,
        clients=clients,
        dossiers=dossiers,
        correspondances_hors_dossier=prospects,
        crm=g.crm(clients, dossiers, prospects),
    )
