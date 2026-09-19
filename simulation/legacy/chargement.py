"""Écrit le monde simulé dans la base legacy, en y ajoutant les défauts d'une vraie
base saisie à la main pendant des années. Les défauts introduits sont renvoyés
pour que le jeu d'évaluation sache ce que le connecteur doit corriger.
"""

import random
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from simulation.modeles import Client, Correspondance, Monde

SCHEMA = Path(__file__).with_name("schema.sql")

OBSERVATIONS = [
    "Client exigeant, préfère être contacté par téléphone.",
    "Honoraires souvent réglés en retard.",
    "Recommandé par un confrère.",
    "RDV uniquement le matin.",
    "Ancien client du cabinet, revenu en 2024.",
]


def _faute(rng: random.Random, texte: str) -> str:
    """Inverse deux lettres voisines : l'erreur de saisie la plus courante."""
    i = rng.randrange(1, max(2, len(texte) - 2))
    return texte[:i] + texte[i + 1] + texte[i] + texte[i + 2 :] if texte[i].isalpha() else texte


def _telephone(rng: random.Random, tel: str) -> str:
    chiffres = tel.replace("+221", "").replace(" ", "")
    return rng.choice(
        [
            tel,
            chiffres,
            f"00221{chiffres}",
            f"{chiffres[:2]}.{chiffres[2:5]}.{chiffres[5:]}",
        ]
    )


def _ligne_client(rng: random.Random, c: Client) -> dict[str, Any]:
    raison = c.nom if c.type == "PM" else None
    if raison and rng.random() < 0.15:
        raison = raison.upper()
    if raison and rng.random() < 0.05:
        raison = _faute(rng, raison)
    prenom, _, nom = c.nom.partition(" ") if c.type == "PP" else (None, "", None)
    return {
        "id": c.id,
        "code": c.code,
        "type": c.type,
        "raison": raison,
        "forme": c.forme,
        "nom": nom.upper() if nom and rng.random() < 0.5 else nom,
        "prenom": prenom,
        "rccm": c.rccm,
        "ninea": None if rng.random() < 0.12 else c.ninea,
        "adresse": c.adresse,
        "ville": c.ville,
        "tel": _telephone(rng, c.telephone),
        "email": None if rng.random() < 0.10 else c.email,
        "crea": c.date_creation,
        "obs": rng.choice(OBSERVATIONS) if rng.random() < 0.2 else None,
    }


def charger(monde: Monde, engine: Engine, seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed + 1)
    defauts: dict[str, Any] = {"doublons_clients": {}, "dossiers_sans_date_cloture": []}

    clients = [_ligne_client(rng, c) for c in monde.clients]
    rattachement = {d.id: d.client_id for d in monde.dossiers}

    # Doublons : la même société recréée plus tard sous un autre code, sans NINEA,
    # et un de ses dossiers rattaché par erreur à ce doublon.
    prochain_id = max(c.id for c in monde.clients) + 1
    for c in monde.clients:
        if c.type != "PM" or rng.random() > 0.08:
            continue
        doublon = _ligne_client(rng, c) | {
            "id": prochain_id,
            "code": f"C{prochain_id:05d}",
            "ninea": None,
            "email": None,
            "raison": rng.choice([c.nom.upper(), c.nom.rsplit(" ", 1)[0], _faute(rng, c.nom)]),
            "obs": f"Voir aussi fiche {c.code} ?",
        }
        clients.append(doublon)
        dossiers_c = [d for d in monde.dossiers if d.client_id == c.id]
        if len(dossiers_c) > 1:
            rattachement[dossiers_c[-1].id] = prochain_id
        defauts["doublons_clients"][prochain_id] = c.id
        prochain_id += 1

    contacts = [
        {
            "id": ct.id,
            "cli": ct.client_id,
            "nom": ct.nom,
            "prenom": ct.prenom,
            "fonction": ct.fonction,
            "email": ct.email,
            "tel": _telephone(rng, ct.telephone),
        }
        for c in monde.clients
        if c.type == "PM"
        for ct in c.contacts
    ]

    dossiers: list[dict[str, Any]] = []
    equipes: list[dict[str, Any]] = []
    intervenants: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    correspondances: list[Correspondance] = []
    for d in monde.dossiers:
        date_clo = d.date_cloture
        if date_clo and rng.random() < 0.10:
            date_clo = None
            defauts["dossiers_sans_date_cloture"].append(d.numero)
        dossiers.append(
            {
                "id": d.id,
                "num": d.numero,
                "cli": rattachement[d.id],
                "intitule": d.intitule,
                "type": d.type,
                "matiere": d.matiere,
                "statut": d.statut,
                "ouv": d.date_ouverture,
                "clo": date_clo,
                "juridiction": d.juridiction,
                "rg": d.numero_rg,
                "enjeu": None if rng.random() < 0.15 else d.enjeu,
                "conf": "O" if d.confidentiel else "N",
                "resp": d.responsable_id,
            }
        )
        for av_id in d.equipe_ids:
            fonction = next(a.fonction for a in monde.avocats if a.id == av_id)
            role = "RESP" if av_id == d.responsable_id else fonction
            equipes.append({"dos": d.id, "av": av_id, "role": role})
        for p in d.parties:
            intervenants.append(
                {
                    "id": len(intervenants) + 1,
                    "dos": d.id,
                    "qualite": p.qualite,
                    "nom": p.nom,
                    "adresse": p.adresse,
                    "email": p.email,
                    "tel": p.telephone,
                }
            )
        for doc in d.documents:
            documents.append(
                {
                    "id": doc.id,
                    "dos": d.id,
                    "libelle": doc.libelle,
                    "categ": "DIVERS" if rng.random() < 0.08 else doc.categorie,
                    "fichier": doc.fichier,
                    "dt": doc.date,
                    "sens": doc.sens,
                    "auteur": None if rng.random() < 0.10 else doc.auteur,
                }
            )
        correspondances += d.correspondances
    correspondances += monde.correspondances_hors_dossier

    lignes_corr = [
        {
            "id": c.id,
            "dos": c.dossier_id if c.classee else None,
            "type": c.type,
            "sens": c.sens,
            "dt": c.date,
            "exped": c.expediteur,
            "dest": ";".join(c.destinataires),
            "objet": c.objet,
            "corps": c.corps,
            "pj": ";".join(map(str, c.pieces_jointes)) or None,
        }
        for c in correspondances
    ]

    with engine.begin() as conn:
        conn.exec_driver_sql(SCHEMA.read_text(encoding="utf-8"))
        conn.execute(
            text("INSERT INTO T_AVOCAT VALUES (:id, :ini, :nom, :prenom, :email, :fonction, 'O')"),
            [
                {
                    "id": a.id,
                    "ini": a.initiales,
                    "nom": a.nom,
                    "prenom": a.prenom,
                    "email": a.email,
                    "fonction": a.fonction,
                }
                for a in monde.avocats
            ],
        )
        conn.execute(
            text(
                "INSERT INTO T_CLIENT VALUES (:id, :code, :type, :raison, :forme, :nom, :prenom, :rccm, :ninea,"
                " :adresse, :ville, :tel, :email, :crea, :obs)"
            ),
            clients,
        )
        conn.execute(
            text("INSERT INTO T_CONTACT VALUES (:id, :cli, :nom, :prenom, :fonction, :email, :tel)"),
            contacts,
        )
        conn.execute(
            text(
                "INSERT INTO T_DOSSIER VALUES (:id, :num, :cli, :intitule, :type, :matiere, :statut, :ouv, :clo,"
                " :juridiction, :rg, :enjeu, :conf, :resp)"
            ),
            dossiers,
        )
        conn.execute(text("INSERT INTO T_DOSSIER_AVOCAT VALUES (:dos, :av, :role)"), equipes)
        conn.execute(
            text("INSERT INTO T_INTERVENANT VALUES (:id, :dos, :qualite, :nom, :adresse, :email, :tel)"),
            intervenants,
        )
        conn.execute(
            text(
                "INSERT INTO T_DOCUMENT VALUES (:id, :dos, :libelle, :categ, :fichier, :dt, :sens, :auteur)"
            ),
            documents,
        )
        conn.execute(
            text(
                "INSERT INTO T_CORRESPONDANCE VALUES (:id, :dos, :type, :sens, :dt, :exped, :dest, :objet, :corps,"
                " :pj)"
            ),
            lignes_corr,
        )

    defauts["comptes"] = {
        "avocats": len(monde.avocats),
        "clients": len(clients),
        "contacts": len(contacts),
        "dossiers": len(dossiers),
        "intervenants": len(intervenants),
        "documents": len(documents),
        "correspondances": len(lignes_corr),
        "correspondances_a_trier": sum(1 for c in lignes_corr if c["dos"] is None),
    }
    return defauts
