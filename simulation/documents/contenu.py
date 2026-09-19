"""Contenu des documents du cabinet, par catégorie.

Chaque modèle renvoie une liste de blocs indépendante du format de sortie :
    ("entete", [lignes])      en-tête (papier à lettre, juridiction…)
    ("titre", texte)          titre centré
    ("section", texte)        intertitre
    ("para", texte)           paragraphe
    ("liste", [lignes])       liste à puces
    ("tableau", [[cellules]]) tableau, première ligne = en-têtes
    ("signature", [lignes])   bloc de signature aligné à droite

Les documents sont réalistes dans leur forme mais fictifs : les références aux
textes OHADA servent à la vraisemblance, pas de source juridique.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from simulation import referentiels as ref
from simulation.modeles import Client, Document, Dossier
from simulation.scenarios import fcfa, jj

Bloc = tuple[str, Any]

REPUBLIQUE = ["RÉPUBLIQUE DU SÉNÉGAL", "Un Peuple – Un But – Une Foi"]
AUPSRVE = (
    "l'Acte uniforme OHADA portant organisation des procédures simplifiées de recouvrement et des "
    "voies d'exécution (AUPSRVE)"
)
AUDCG = "l'Acte uniforme OHADA relatif au droit commercial général (AUDCG)"
AUSCGIE = (
    "l'Acte uniforme OHADA relatif au droit des sociétés commerciales et du groupement d'intérêt économique"
)


class Ctx:
    """Tout ce dont un modèle a besoin pour rédiger un document."""

    def __init__(self, doc: Document, dossier: Dossier, client: Client, avocat: str) -> None:
        self.doc = doc
        self.avocat = avocat  # avocat du cabinet responsable du dossier
        self.d = dossier
        self.client = client
        self.f: dict[str, Any] = {**dossier.faits, **doc.faits}
        self.rng = random.Random(doc.id)  # noms de magistrats, etc. stables par document
        self.parties = {p.qualite: p for p in dossier.parties}

    def partie(self, qualite: str, defaut: str = "") -> str:
        p = self.parties.get(qualite)
        return p.nom if p else defaut

    def adresse(self, qualite: str) -> str:
        p = self.parties.get(qualite)
        return (p.adresse or "") if p else ""

    @property
    def adverse(self) -> str:
        return str(
            self.f.get("debiteur")
            or self.f.get("adverse")
            or self.f.get("locataire")
            or self.partie("ADV")
            or self.partie("TIERS")
        )

    @property
    def avocat_cabinet(self) -> str:
        """Signataire : l'auteur si c'est un avocat du cabinet, sinon le responsable du dossier."""
        auteur = self.doc.auteur
        return auteur if self.doc.sens in ("S", "I") and auteur.startswith("Me ") else self.avocat

    def magistrat(self) -> str:
        return f"{self.rng.choice(ref.PRENOMS_H + ref.PRENOMS_F)} {self.rng.choice(ref.NOMS)}"

    def identite_client(self) -> str:
        c = self.client
        if c.type == "PM":
            rep = c.interlocuteur
            return (
                f"La société {c.nom}{'' if c.nom.endswith(c.forme or '') else ', ' + str(c.forme)}, immatriculée au RCCM sous le n° {c.rccm}, NINEA {c.ninea}, "
                f"dont le siège est sis {c.adresse}, prise en la personne de son représentant légal, "
                f"{rep.nom_complet}, {rep.fonction}"
            )
        return f"{c.nom}, demeurant {c.adresse}"

    def conseil(self) -> str:
        return (
            f"ayant pour conseil {self.avocat_cabinet}, avocat au Barreau du Sénégal, {ref.CABINET_NOM}, "
            f"{ref.CABINET_ADRESSE}, en l'étude duquel domicile est élu"
        )


def papier_cabinet() -> Bloc:
    return (
        "entete",
        [
            ref.CABINET_NOM,
            "Avocats au Barreau du Sénégal",
            ref.CABINET_ADRESSE,
            f"Tél. +221 33 821 40 40 – contact@{ref.CABINET_DOMAINE}",
        ],
    )


def lieu_date(d: date) -> Bloc:
    return ("para", f"Dakar, le {jj(d)}")


def audience(c: Ctx, jours: int = 30) -> str:
    return jj(c.doc.date + timedelta(days=jours))


# ---------------------------------------------------------------- pièces du client


def facture(c: Ctx) -> list[Bloc]:
    cl = c.client
    montant = int(c.f.get("montant", 0))
    quantite = c.rng.choice([10, 20, 25, 40, 50, 100])
    secteur = ref.SECTEURS.get(cl.secteur or "", "marchandises")
    return [
        ("entete", [cl.nom, cl.adresse, f"RCCM : {cl.rccm} – NINEA : {cl.ninea}", f"Tél. : {cl.telephone}"]),
        ("titre", f"FACTURE N° {c.f.get('numero')}"),
        ("para", f"Date : {jj(date.fromisoformat(c.f['date']))}" if "date" in c.f else "Date :"),
        ("para", f"Doit : {c.f.get('debiteur')}"),
        (
            "tableau",
            [
                ["Désignation", "Quantité", "Prix unitaire", "Montant"],
                [f"Fourniture – {secteur}", str(quantite), fcfa(montant // quantite), fcfa(montant)],
            ],
        ),
        ("para", f"Montant total TTC : {fcfa(montant)}"),
        ("para", "Conditions de paiement : à 30 jours date de facture, par virement bancaire."),
        ("para", "Tout retard de paiement entraînera l'application d'intérêts au taux légal."),
    ]


def bons_livraison(c: Ctx) -> list[Bloc]:
    lignes = [["N° BL", "Date de livraison", "Facture liée", "Réceptionnaire"]]
    for i, fa in enumerate(c.f.get("factures", []), start=1):
        livraison = date.fromisoformat(fa["date"]) - timedelta(days=2)
        lignes.append(
            [
                f"BL-{livraison.year}-{c.rng.randint(1000, 9999)}",
                jj(livraison),
                fa["numero"],
                f"Magasinier {c.adverse}" if i % 2 else "Chef de dépôt",
            ]
        )
    return [
        ("entete", [c.client.nom, c.client.adresse]),
        ("titre", "BONS DE LIVRAISON"),
        ("para", f"Client livré : {c.adverse}"),
        ("tableau", lignes),
        ("para", "Marchandises reçues en bon état et conformes à la commande."),
        ("signature", ["Reçu conforme", "Cachet et signature du client"]),
    ]


def etat_loyers(c: Ctx) -> list[Bloc]:
    loyer = int(c.f.get("loyer_mensuel", 0))
    mois = int(c.f.get("mois_impayes", 0))
    lignes = [["Échéance", "Loyer dû", "Payé", "Reste dû"]]
    for i in range(mois, 0, -1):
        echeance = c.d.date_ouverture.replace(day=1) - timedelta(days=30 * i)
        lignes.append([echeance.strftime("%m/%Y"), fcfa(loyer), fcfa(0), fcfa(loyer)])
    lignes.append(["TOTAL", fcfa(loyer * mois), fcfa(0), fcfa(loyer * mois)])
    return [
        ("entete", [c.client.nom, c.client.adresse]),
        ("titre", "ÉTAT DES LOYERS IMPAYÉS"),
        ("para", f"Locataire : {c.adverse} – {c.f.get('local', '')}"),
        ("tableau", lignes),
        ("para", f"Arrêté au {jj(c.doc.date)} à la somme de {fcfa(loyer * mois)}."),
    ]


# ---------------------------------------------------------------- courriers et actes du cabinet


def mise_en_demeure(c: Ctx) -> list[Bloc]:
    montant = int(c.f.get("montant", 0))
    delai = c.f.get("delai_jours", 8)
    factures = c.f.get("factures") or []
    detail = (
        " au titre des factures " + ", ".join(f"{fa['numero']} ({fcfa(fa['montant'])})" for fa in factures)
        if factures
        else ""
    )
    return [
        papier_cabinet(),
        lieu_date(c.doc.date),
        ("para", f"À l'attention de : {c.f.get('destinataire', c.adverse)}"),
        ("para", "Lettre recommandée avec accusé de réception"),
        ("para", f"Objet : Mise en demeure – {c.client.nom}"),
        ("para", "Madame, Monsieur,"),
        (
            "para",
            (
                f"Nous intervenons en qualité de conseil de {c.client.nom}, qui nous a chargés de la défense de "
                "ses intérêts dans le différend qui l'oppose à vous."
            ),
        ),
        (
            "para",
            (
                f"Notre client nous indique que vous restez lui devoir la somme de {fcfa(montant)}{detail}, "
                "malgré plusieurs relances restées sans effet."
            ),
        ),
        (
            "para",
            (
                f"En conséquence, nous vous mettons en demeure de régler cette somme dans un délai de {delai} jours "
                "à compter de la réception de la présente."
            ),
        ),
        (
            "para",
            (
                "À défaut, notre client nous a donné instruction d'engager à votre encontre toute procédure "
                "judiciaire utile, sans autre avis, et à vos frais."
            ),
        ),
        ("para", "Veuillez agréer, Madame, Monsieur, l'expression de nos salutations distinguées."),
        ("signature", [c.avocat_cabinet, "Avocat au Barreau du Sénégal"]),
    ]


def protocole(c: Ctx) -> list[Bloc]:
    montant = int(c.f.get("montant", 0))
    n = int(c.f.get("echeances", 3))
    part = montant // n
    lignes = [["Échéance", "Date", "Montant"]] + [
        [str(i), jj(c.doc.date + timedelta(days=30 * i)), fcfa(part if i < n else montant - part * (n - 1))]
        for i in range(1, n + 1)
    ]
    return [
        ("titre", "PROTOCOLE D'ACCORD TRANSACTIONNEL"),
        ("section", "ENTRE LES SOUSSIGNÉS"),
        ("para", f"{c.identite_client()}, ci-après « le Créancier »,"),
        ("para", f"ET la société {c.adverse}, ci-après « le Débiteur »."),
        ("section", "IL A ÉTÉ PRÉALABLEMENT EXPOSÉ"),
        (
            "para",
            (
                f"Le Créancier a mis en demeure le Débiteur de lui régler la somme de {fcfa(montant)}. "
                "Le Débiteur a reconnu sa dette et sollicité des délais de paiement."
            ),
        ),
        ("section", "CECI EXPOSÉ, IL A ÉTÉ CONVENU CE QUI SUIT"),
        (
            "para",
            (
                f"Article 1 – Reconnaissance de dette. Le Débiteur reconnaît devoir au Créancier la somme de "
                f"{fcfa(montant)}."
            ),
        ),
        (
            "para",
            f"Article 2 – Échéancier. Le Débiteur s'engage à s'acquitter de cette somme en {n} échéances :",
        ),
        ("tableau", lignes),
        (
            "para",
            (
                "Article 3 – Déchéance du terme. Le défaut de paiement d'une seule échéance à sa date rendra "
                "immédiatement exigible la totalité des sommes restant dues, huit jours après une simple mise "
                "en demeure restée sans effet."
            ),
        ),
        (
            "para",
            (
                "Article 4 – Renonciation. Sous réserve de la parfaite exécution du présent protocole, le "
                "Créancier renonce à toute action judiciaire relative à cette créance."
            ),
        ),
        ("para", f"Fait à Dakar, le {jj(c.doc.date)}, en deux exemplaires originaux."),
        ("signature", ["Pour le Créancier", "", "Pour le Débiteur"]),
    ]


def requete_ip(c: Ctx) -> list[Bloc]:
    montant = int(c.f.get("montant", 0))
    factures = c.f.get("factures") or []
    return [
        papier_cabinet(),
        ("titre", "REQUÊTE AUX FINS D'INJONCTION DE PAYER"),
        ("para", f"À Monsieur le Président du {c.f.get('juridiction', ref.JURIDICTIONS['commerce'])}"),
        ("section", "A L'HONNEUR DE VOUS EXPOSER"),
        ("para", f"{c.identite_client()}, {c.conseil()} ;"),
        (
            "para",
            (
                f"Que la requérante a livré des marchandises à la société {c.adverse}, qui n'en a pas réglé le "
                f"prix malgré une mise en demeure demeurée infructueuse ;"
            ),
        ),
        (
            "para",
            f"Qu'elle reste ainsi créancière de la somme de {fcfa(montant)} en principal, détaillée comme suit :",
        ),
        (
            "tableau",
            [["Facture", "Date", "Montant"]]
            + [[fa["numero"], jj(date.fromisoformat(fa["date"])), fcfa(fa["montant"])] for fa in factures],
        ),
        ("section", "EN DROIT"),
        (
            "para",
            (
                f"Aux termes des articles 1er et 2 de {AUPSRVE}, le recouvrement d'une créance certaine, liquide et "
                "exigible ayant une cause contractuelle peut être demandé suivant la procédure d'injonction de "
                "payer ;"
            ),
        ),
        (
            "para",
            (
                "Que la créance de la requérante, fondée sur des factures acceptées et des bons de livraison "
                "signés, remplit ces conditions ;"
            ),
        ),
        ("section", "PAR CES MOTIFS"),
        (
            "para",
            (
                f"Plaise à Monsieur le Président enjoindre à la société {c.adverse}, {c.adresse('ADV')}, de payer "
                f"à la requérante la somme de {fcfa(montant)} en principal, outre les intérêts et frais."
            ),
        ),
        ("section", "PIÈCES JOINTES"),
        (
            "liste",
            ["Factures impayées", "Bons de livraison signés", "Mise en demeure et accusé de réception"],
        ),
        lieu_date(c.doc.date),
        ("signature", [c.avocat_cabinet]),
    ]


def conclusions(c: Ctx, pour_le_cabinet: bool) -> list[Bloc]:
    rg = c.f.get("rg") or c.d.numero_rg or ""
    demandeur, defendeur = c.client.nom, c.adverse
    if c.d.matiere == "RECOUV":
        faits = (
            f"{demandeur} a livré à {defendeur} des marchandises facturées pour un montant de "
            f"{fcfa(int(c.f.get('montant_principal', 0)))}. Une ordonnance d'injonction de payer a été rendue, "
            f"à laquelle {defendeur} a formé opposition."
        )
    else:
        faits = (
            f"{demandeur} et {defendeur} étaient liées par un contrat. {demandeur} reproche à {defendeur} "
            f"{c.f.get('objet', 'un manquement contractuel')} et évalue son préjudice à "
            f"{fcfa(int(c.f.get('prejudice', 0)))}."
        )
    if pour_le_cabinet:
        auteur, titre = (
            c.avocat_cabinet,
            "CONCLUSIONS EN RÉPONSE" if c.d.matiere == "RECOUV" else "CONCLUSIONS EN RÉPLIQUE",
        )
        moyens = [
            "La créance est certaine : elle résulte de factures et de bons de livraison signés sans réserve.",
            "Aucune réclamation n'a été formulée au moment de la livraison ; la contestation est tardive.",
            f"{defendeur} ne rapporte la preuve d'aucun cas de force majeure ni d'aucune non-conformité.",
        ]
        demandes = [
            f"Déclarer {defendeur} mal fondé en ses demandes et l'en débouter",
            f"Condamner {defendeur} au paiement des sommes réclamées",
            f"Condamner {defendeur} aux dépens",
        ]
    else:
        auteur, titre = c.partie("AVADV", "Conseil de la partie adverse"), "CONCLUSIONS"
        moyens = [
            f"Les marchandises livrées n'étaient pas conformes : {c.f.get('motif', 'plusieurs lots ont été refusés')}.",
            f"Les manquements reprochés relèvent de la force majeure ({c.f.get('moyens', 'événements imprévisibles')}).",
            f"{demandeur} ne justifie pas du préjudice allégué.",
        ]
        demandes = [
            f"Débouter {demandeur} de l'ensemble de ses demandes",
            f"Condamner {demandeur} aux dépens",
        ]
    return [
        ("entete", [c.d.juridiction or ref.JURIDICTIONS["commerce"], rg, f"Audience du {audience(c, 20)}"]),
        ("titre", titre),
        ("para", f"POUR : {demandeur if pour_le_cabinet else defendeur}"),
        ("para", f"CONTRE : {defendeur if pour_le_cabinet else demandeur}"),
        ("section", "I. RAPPEL DES FAITS ET DE LA PROCÉDURE"),
        ("para", faits),
        ("section", "II. DISCUSSION"),
        ("liste", moyens),
        ("section", "PAR CES MOTIFS"),
        ("para", "Plaise au Tribunal :"),
        ("liste", demandes),
        ("signature", [f"Sous toutes réserves – {auteur}"]),
    ]


def assignation(c: Ctx) -> list[Bloc]:
    huissier = c.partie("HUIS", "Huissier de justice")
    prejudice = int(c.f.get("demande") or c.f.get("prejudice") or 0)
    return [
        ("entete", [huissier, "Huissier de justice à Dakar"]),
        ("titre", "ASSIGNATION DEVANT LE TRIBUNAL DE COMMERCE HORS CLASSE DE DAKAR"),
        ("para", f"L'an {c.doc.date.year} et le {jj(c.doc.date)},"),
        ("para", f"À la requête de : {c.identite_client()}, {c.conseil()} ;"),
        (
            "para",
            (
                f"J'ai, {huissier}, soussigné, donné assignation à la société {c.adverse}, {c.adresse('ADV')}, "
                f"d'avoir à comparaître à l'audience du {audience(c)} à 9 heures devant le "
                f"{ref.JURIDICTIONS['commerce']}, statuant en matière commerciale."
            ),
        ),
        ("section", "OBJET DE LA DEMANDE"),
        (
            "para",
            (
                f"La requérante reproche à {c.adverse} {c.f.get('objet', 'des manquements contractuels')}, "
                "en violation des engagements pris dans le contrat liant les parties."
            ),
        ),
        (
            "para",
            (
                "Les dispositions du Code des obligations civiles et commerciales relatives à la responsabilité "
                "contractuelle obligent le débiteur défaillant à réparer le préjudice causé par l'inexécution."
            ),
        ),
        ("section", "PAR CES MOTIFS"),
        (
            "liste",
            [
                f"Constater l'inexécution fautive du contrat par {c.adverse}",
                f"Condamner {c.adverse} à payer la somme de {fcfa(prejudice)} à titre de dommages et intérêts",
                "Ordonner l'exécution provisoire",
                f"Condamner {c.adverse} aux dépens",
            ],
        ),
        ("signature", [huissier]),
    ]


def acte_appel(c: Ctx) -> list[Bloc]:
    return [
        papier_cabinet(),
        ("titre", "ACTE D'APPEL"),
        ("para", f"À la requête de {c.identite_client()}, {c.conseil()} ;"),
        (
            "para",
            (
                f"Il est déclaré interjeter appel du jugement rendu par le {ref.JURIDICTIONS['commerce']} dans "
                f"l'affaire {c.f.get('jugement_rg', '')} opposant la requérante à {c.adverse}, ledit jugement "
                "ayant débouté la requérante de l'ensemble de ses demandes."
            ),
        ),
        (
            "para",
            (
                "L'appelante entend voir infirmer le jugement en toutes ses dispositions. Ses moyens seront "
                "développés dans ses conclusions devant la Cour d'appel de Dakar."
            ),
        ),
        lieu_date(c.doc.date),
        ("signature", [c.avocat_cabinet]),
    ]


def assignation_refere(c: Ctx) -> list[Bloc]:
    montant = fcfa(int(c.f.get("loyer_mensuel", 0)) * int(c.f.get("mois_impayes", 0)))
    return [
        papier_cabinet(),
        ("titre", "ASSIGNATION EN RÉFÉRÉ AUX FINS D'EXPULSION"),
        ("para", f"À la requête de {c.identite_client()}, {c.conseil()} ;"),
        (
            "para",
            (
                f"Il est donné assignation à la société {c.adverse}, preneuse du {c.f.get('local', 'local')}, "
                f"d'avoir à comparaître devant le Président du {ref.JURIDICTIONS['tgi']}, statuant en référé, "
                f"à l'audience du {audience(c, 15)}."
            ),
        ),
        ("section", "EXPOSÉ"),
        (
            "para",
            (
                f"La défenderesse ne paie plus son loyer de {fcfa(int(c.f.get('loyer_mensuel', 0)))} depuis "
                f"{c.f.get('mois_impayes')} mois, soit un arriéré de {montant}. Un commandement de payer visant "
                "la clause résolutoire lui a été signifié et est resté sans effet pendant plus d'un mois."
            ),
        ),
        (
            "para",
            (
                f"En application de l'article 133 de {AUDCG}, la juridiction compétente, statuant à bref délai, "
                "peut constater la résiliation du bail et ordonner l'expulsion du preneur."
            ),
        ),
        ("section", "PAR CES MOTIFS"),
        (
            "liste",
            [
                "Constater la résiliation du bail",
                f"Ordonner l'expulsion de {c.adverse} et de tous occupants",
                f"Condamner {c.adverse} à payer {montant} au titre des loyers échus",
            ],
        ),
        ("signature", [c.avocat_cabinet]),
    ]


def note_interne(c: Ctx) -> list[Bloc]:
    return [
        ("titre", "NOTE INTERNE – CONFIDENTIELLE"),
        ("para", f"De : {c.avocat_cabinet} – Dossier {c.d.numero} – {c.d.intitule}"),
        ("section", "1. Faits"),
        (
            "para",
            (
                f"Notre client {c.client.nom} reproche à {c.adverse} {c.f.get('objet', '')}. Le préjudice "
                f"allégué s'élève à {fcfa(int(c.f.get('prejudice', 0)))}."
            ),
        ),
        ("section", "2. Analyse"),
        (
            "para",
            (
                "Le contrat met à la charge du cocontractant une obligation de résultat. La preuve de "
                "l'inexécution résulte des correspondances échangées. Le quantum du préjudice devra être étayé "
                "par des pièces comptables."
            ),
        ),
        ("section", "3. Risques"),
        (
            "liste",
            [
                "Invocation de la force majeure par la partie adverse",
                "Durée de la procédure au fond (12 à 18 mois)",
                "Solvabilité incertaine de la partie adverse",
            ],
        ),
        ("section", "4. Recommandation"),
        ("para", str(c.f.get("recommandation", "Tenter une résolution amiable avant toute action."))),
    ]


# ---------------------------------------------------------------- décisions de justice


def ordonnance_ip(c: Ctx) -> list[Bloc]:
    montant = int(c.f.get("montant", 0))
    president = c.magistrat()
    return [
        ("entete", REPUBLIQUE + [ref.JURIDICTIONS["commerce"].upper()]),
        ("titre", f"ORDONNANCE D'INJONCTION DE PAYER N° {c.f.get('numero')}"),
        ("para", f"Nous, {president}, Président du {ref.JURIDICTIONS['commerce']} ;"),
        ("para", f"Vu la requête présentée par {c.client.nom}, ayant pour conseil le {ref.CABINET_NOM} ;"),
        ("para", f"Vu les articles 1 à 18 de {AUPSRVE} ;"),
        ("para", "Vu les pièces produites, notamment les factures et les bons de livraison ;"),
        ("para", "Attendu que la créance invoquée paraît fondée en tout ou partie ;"),
        ("section", "PAR CES MOTIFS"),
        (
            "para",
            (
                f"Enjoignons à la société {c.adverse} de payer à {c.client.nom} la somme de {fcfa(montant)} en "
                "principal, outre les frais de la présente procédure ;"
            ),
        ),
        (
            "para",
            (
                "Disons que le débiteur dispose d'un délai de quinze jours à compter de la signification de la "
                "présente ordonnance pour former opposition ; qu'à défaut, il pourra y être contraint par toutes "
                "voies de droit."
            ),
        ),
        ("para", f"Fait en notre cabinet, à Dakar, le {jj(c.doc.date)}."),
        ("signature", ["Le Président", president, "", "Le Greffier"]),
    ]


def ordonnance_executoire(c: Ctx) -> list[Bloc]:
    return ordonnance_ip(c)[:-2] + [
        ("section", "FORMULE EXÉCUTOIRE"),
        (
            "para",
            (
                "Aucune opposition n'ayant été formée dans le délai de quinze jours suivant la signification, "
                "conformément à l'article 16 de l'AUPSRVE, la présente ordonnance est revêtue de la formule "
                "exécutoire."
            ),
        ),
        (
            "para",
            (
                "En conséquence, la République du Sénégal mande et ordonne à tous huissiers de justice, sur ce "
                "requis, de mettre la présente décision à exécution."
            ),
        ),
        ("para", f"Délivré à Dakar, le {jj(c.doc.date)}."),
        ("signature", ["Le Greffier en chef"]),
    ]


def jugement(c: Ctx) -> list[Bloc]:
    rg = c.f.get("rg") or c.d.numero_rg or ""
    alloue = int(c.f.get("montant_alloue", 0))
    president, juge1, juge2 = c.magistrat(), c.magistrat(), c.magistrat()
    date_jgt = date.fromisoformat(c.f["date"]) if "date" in c.f else c.doc.date
    dispositif = ["Statuant publiquement, contradictoirement, en matière commerciale et en premier ressort ;"]
    if alloue:
        dispositif += [
            f"{str(c.f.get('dispositif', 'Condamne le défendeur')).capitalize()} ;",
            f"Condamne {c.adverse} à payer à {c.client.nom} la somme de {fcfa(alloue)} ;",
            f"Condamne {c.adverse} aux dépens.",
        ]
    else:
        dispositif += [
            f"Déboute {c.client.nom} de l'ensemble de ses demandes ;",
            f"Condamne {c.client.nom} aux dépens.",
        ]
    return [
        ("entete", REPUBLIQUE + [ref.JURIDICTIONS["commerce"].upper(), rg]),
        ("titre", f"JUGEMENT DU {jj(date_jgt)}"),
        ("para", "AU NOM DU PEUPLE SÉNÉGALAIS"),
        (
            "para",
            (
                f"Le {ref.JURIDICTIONS['commerce']}, composé de {president}, Président, {juge1} et {juge2}, "
                "juges consulaires, assistés du greffier, a rendu le jugement suivant :"
            ),
        ),
        ("para", f"ENTRE : {c.identite_client()}, {c.conseil()}, demanderesse,"),
        (
            "para",
            f"ET : la société {c.adverse}, ayant pour conseil {c.partie('AVADV', 'un avocat')}, défenderesse.",
        ),
        ("section", "FAITS ET PROCÉDURE"),
        (
            "para",
            (
                f"Les parties étaient en relation d'affaires. Un différend est né au sujet de "
                f"{c.f.get('objet', 'factures demeurées impayées')}. L'affaire a été enrôlée sous le {rg}, "
                "renvoyée à plusieurs reprises, puis retenue et mise en délibéré."
            ),
        ),
        ("section", "MOTIFS DE LA DÉCISION"),
        (
            "para",
            "Attendu que la demanderesse produit le contrat, les factures et les correspondances échangées ;",
        ),
        (
            "para",
            "Attendu que la défenderesse ne rapporte pas la preuve des faits justificatifs qu'elle invoque ;"
            if alloue
            else "Attendu que la demanderesse ne rapporte pas la preuve du préjudice allégué ;",
        ),
        ("section", "PAR CES MOTIFS"),
        ("liste", dispositif),
        ("signature", ["Le Président", president, "", "Le Greffier"]),
    ]


def ordonnance_refere(c: Ctx) -> list[Bloc]:
    president = c.magistrat()
    return [
        ("entete", REPUBLIQUE + [ref.JURIDICTIONS["tgi"].upper()]),
        ("titre", f"ORDONNANCE DE RÉFÉRÉ – {c.f.get('numero', c.d.numero_rg or '')}"),
        (
            "para",
            f"Nous, {president}, Président du {ref.JURIDICTIONS['tgi']}, statuant en matière de référé ;",
        ),
        ("para", f"Vu l'assignation délivrée à la requête de {c.client.nom} à l'encontre de {c.adverse} ;"),
        ("para", f"Vu l'article 133 de {AUDCG} ;"),
        (
            "para",
            (
                "Attendu qu'un commandement de payer visant la clause résolutoire a été signifié au preneur et est "
                "resté infructueux pendant plus d'un mois ;"
            ),
        ),
        ("section", "PAR CES MOTIFS"),
        (
            "liste",
            [
                f"{str(c.f.get('dispositif', '')).capitalize()} ;",
                (
                    f"Condamnons {c.adverse} à payer à {c.client.nom} la somme de "
                    f"{fcfa(int(c.f.get('condamnation', 0)))} ;"
                ),
                "Disons que la présente ordonnance est exécutoire par provision.",
            ],
        ),
        ("para", f"Fait à Dakar, le {jj(c.doc.date)}."),
        ("signature", ["Le Président", president]),
    ]


# ---------------------------------------------------------------- actes d'huissier


def _exploit(c: Ctx, titre: str, corps: list[Bloc]) -> list[Bloc]:
    huissier = c.partie("HUIS", "Me l'Huissier")
    parlant = c.rng.choice(
        [
            "son gérant, ainsi déclaré",
            "un employé qui a accepté de recevoir la copie",
            "la secrétaire de direction, ainsi déclarée",
        ]
    )
    return [
        (
            "entete",
            [huissier, "Huissier de justice près le Tribunal de grande instance hors classe de Dakar"],
        ),
        ("titre", titre),
        ("para", f"L'an {c.doc.date.year} et le {jj(c.doc.date)},"),
        ("para", f"À la requête de {c.identite_client()}, {c.conseil()} ;"),
        *corps,
        ("para", f"Parlant à : {parlant}."),
        ("para", f"Coût du présent acte : {fcfa(c.rng.choice([15_000, 25_000, 35_000]))}"),
        ("signature", [huissier]),
    ]


def pv_signification(c: Ctx) -> list[Bloc]:
    return _exploit(
        c,
        "SIGNIFICATION D'ORDONNANCE D'INJONCTION DE PAYER",
        [
            (
                "para",
                (
                    f"J'ai signifié et laissé copie à la société {c.adverse}, {c.adresse('ADV')}, de l'ordonnance "
                    f"d'injonction de payer n° {c.f.get('ordonnance')} rendue par le Président du "
                    f"{ref.JURIDICTIONS['commerce']}."
                ),
            ),
            (
                "para",
                (
                    "Et à même requête, j'ai fait sommation au débiteur de payer au créancier le montant de la "
                    "condamnation, ou de former opposition."
                ),
            ),
            (
                "para",
                (
                    "TRÈS IMPORTANT : le débiteur est informé qu'il dispose d'un délai de QUINZE (15) JOURS à compter "
                    "de la présente signification pour former opposition devant la juridiction ayant rendu la "
                    "décision, par acte extrajudiciaire. À défaut, l'ordonnance deviendra définitive."
                ),
            ),
        ],
    )


def opposition(c: Ctx) -> list[Bloc]:
    avocat = c.f.get("avocat") or c.partie("AVADV")
    return [
        ("entete", [c.partie("HUIS", "Huissier de justice"), "Huissier de justice à Dakar"]),
        ("titre", "EXPLOIT D'OPPOSITION AVEC ASSIGNATION"),
        ("para", f"L'an {c.doc.date.year} et le {jj(c.doc.date)},"),
        ("para", f"À la requête de la société {c.adverse}, ayant pour conseil {avocat} ;"),
        (
            "para",
            (
                f"Déclare former opposition à l'ordonnance d'injonction de payer rendue au profit de "
                f"{c.client.nom}, et donne assignation à {c.client.nom} à comparaître devant le "
                f"{ref.JURIDICTIONS['commerce']} à l'audience du {audience(c)}."
            ),
        ),
        ("section", "MOTIFS"),
        (
            "para",
            f"L'opposante conteste la créance réclamée en raison de la {c.f.get('motif', 'non-conformité')}.",
        ),
        ("section", "PAR CES MOTIFS"),
        (
            "liste",
            [
                "Déclarer l'opposition recevable en la forme",
                "La déclarer fondée",
                "Rétracter l'ordonnance d'injonction de payer",
            ],
        ),
        ("signature", [str(avocat)]),
    ]


def pv_saisie(c: Ctx) -> list[Bloc]:
    principal = int(c.f.get("montant", 0))
    interets = principal * 5 // 100
    frais = 85_000
    return _exploit(
        c,
        "PROCÈS-VERBAL DE SAISIE-ATTRIBUTION DE CRÉANCES",
        [
            (
                "para",
                "Agissant en vertu d'une ordonnance d'injonction de payer revêtue de la formule exécutoire ;",
            ),
            (
                "para",
                (
                    f"J'ai saisi entre les mains de {c.f.get('tiers_saisi')}, tiers saisi, toutes les sommes dont il "
                    f"est ou sera débiteur envers la société {c.adverse}, en application des articles 153 et suivants "
                    "de l'AUPSRVE, pour sûreté et paiement de la somme suivante :"
                ),
            ),
            (
                "tableau",
                [
                    ["Décompte", "Montant"],
                    ["Principal", fcfa(principal)],
                    ["Intérêts échus", fcfa(interets)],
                    ["Frais de procédure", fcfa(frais)],
                    ["TOTAL", fcfa(principal + interets + frais)],
                ],
            ),
            (
                "para",
                (
                    "Le tiers saisi est tenu de déclarer sur-le-champ l'étendue de ses obligations à l'égard du "
                    "débiteur et de communiquer les pièces justificatives."
                ),
            ),
        ],
    )


def commandement(c: Ctx) -> list[Bloc]:
    montant = int(c.f.get("montant", 0))
    return _exploit(
        c,
        "COMMANDEMENT DE PAYER VISANT LA CLAUSE RÉSOLUTOIRE",
        [
            (
                "para",
                (
                    f"J'ai fait commandement à la société {c.adverse}, preneuse du {c.f.get('local', 'local')}, "
                    f"d'avoir à payer dans le délai d'un mois la somme de {fcfa(montant)} au titre des loyers échus "
                    "et impayés."
                ),
            ),
            (
                "para",
                (
                    f"Lui déclarant qu'à défaut de paiement dans ce délai, le bailleur entend se prévaloir de la clause "
                    f"résolutoire stipulée au bail et saisir la juridiction compétente, conformément à l'article 133 "
                    f"de {AUDCG}."
                ),
            ),
        ],
    )


# ---------------------------------------------------------------- contrats et droit des sociétés


def contrat(c: Ctx, projet: str | None = None) -> list[Bloc]:
    f = c.f
    partenaire = f.get("cocontractant") or c.adverse
    type_ = f.get("type", "fourniture")
    date_sig = f.get("date_signature") or f.get("date")
    blocs: list[Bloc] = []
    if projet:
        blocs += [("para", f"PROJET – {projet} – document de travail, non contractuel")]
    blocs += [
        ("titre", f"CONTRAT DE {str(type_).upper()}"),
        ("section", "ENTRE LES SOUSSIGNÉS"),
        ("para", f"{c.identite_client()}, ci-après « le Client »,"),
        ("para", f"ET la société {partenaire}, ci-après « le Partenaire »."),
        (
            "para",
            (
                "Article 1 – Objet. Le présent contrat a pour objet de définir les conditions dans lesquelles le "
                f"Partenaire assure au profit du Client des prestations de {type_}."
            ),
        ),
        (
            "para",
            (
                f"Article 2 – Durée. Le contrat est conclu pour une durée de {f.get('duree_mois', 24)} mois à compter "
                "de sa signature. Il se renouvelle par tacite reconduction pour des périodes d'un an."
            ),
        ),
        (
            "para",
            f"Article 3 – Prix. Le montant annuel est fixé à {fcfa(int(f.get('montant_annuel', 0)))} hors taxes, "
            "payable trimestriellement à 30 jours fin de mois."
            if f.get("montant_annuel")
            else "Article 3 – Prix. Les prix sont ceux figurant aux bons de commande acceptés.",
        ),
        (
            "para",
            f"Article 4 – Territoire. Le contrat s'exécute sur le territoire suivant : "
            f"{f.get('territoire', 'Sénégal')}."
            + (
                " Le Partenaire bénéficie d'une exclusivité sur ce territoire."
                if f.get("exclusivite")
                else ""
            ),
        ),
        (
            "para",
            (
                f"Article 5 – Pénalités. Tout retard d'exécution imputable au Partenaire donne lieu à une pénalité "
                f"de {f.get('penalite_retard', '1 % par semaine de retard')}, plafonnée à 10 % du montant annuel."
            ),
        ),
        (
            "para",
            (
                f"Article 6 – Résiliation. Chaque partie peut résilier le contrat moyennant un préavis de "
                f"{f.get('preavis_resiliation_jours', 60)} jours notifié par lettre recommandée. En cas de "
                "manquement grave, la résiliation intervient de plein droit quinze jours après une mise en "
                "demeure restée sans effet."
            ),
        ),
        (
            "para",
            (
                "Article 7 – Confidentialité. Les parties s'engagent à garder confidentielles les informations "
                "échangées pendant toute la durée du contrat et deux ans après son terme."
            ),
        ),
        (
            "para",
            (
                f"Article 8 – Droit applicable et litiges. Le contrat est soumis au "
                f"{f.get('droit_applicable', 'droit OHADA et droit sénégalais')}. Tout différend sera soumis à : "
                f"{f.get('reglement_litiges', ref.JURIDICTIONS['commerce'])}."
            ),
        ),
        (
            "para",
            f"Fait à Dakar, le {jj(date.fromisoformat(date_sig)) if date_sig else '……'}, en deux exemplaires.",
        ),
        ("signature", ["Pour le Client", "", "Pour le Partenaire"]),
    ]
    return blocs


def projet_contrat(c: Ctx) -> list[Bloc]:
    return contrat(c, projet="v1" if "v1" in c.doc.libelle else "v2")


def observations(c: Ctx) -> list[Bloc]:
    return [
        ("entete", [c.doc.auteur, "Avocat à la Cour"]),
        ("titre", "OBSERVATIONS SUR LE PROJET DE CONTRAT"),
        (
            "para",
            f"Pour : {c.f.get('cocontractant') or c.partie('TIERS')} – Projet transmis par {ref.CABINET_NOM}",
        ),
        (
            "liste",
            [
                (
                    "Article 5 – Pénalités : le taux proposé est excessif ; nous demandons de le ramener à 0,5 % par "
                    "semaine, plafonné à 5 %."
                ),
                (
                    "Article 6 – Résiliation : le préavis doit être porté à 120 jours pour permettre la réorganisation "
                    "de l'activité."
                ),
                "Article 8 – Litiges : notre cliente accepte l'arbitrage sous réserve que le siège soit fixé à Dakar.",
            ],
        ),
        ("para", f"Synthèse de la demande : {c.f.get('demande', '')}."),
        lieu_date(c.doc.date),
        ("signature", [c.doc.auteur]),
    ]


def bail(c: Ctx) -> list[Bloc]:
    loyer = int(c.f.get("loyer_mensuel", 0))
    debut = c.d.date_ouverture - timedelta(days=c.rng.randint(400, 1500))
    return [
        ("titre", "BAIL À USAGE PROFESSIONNEL"),
        ("section", "ENTRE LES SOUSSIGNÉS"),
        ("para", f"{c.identite_client()}, ci-après « le Bailleur »,"),
        ("para", f"ET la société {c.adverse}, ci-après « le Preneur »."),
        (
            "para",
            f"Article 1 – Désignation. Le Bailleur donne à bail au Preneur un {c.f.get('local', 'local')}.",
        ),
        (
            "para",
            (
                f"Article 2 – Durée. Le bail est consenti pour trois ans à compter du {jj(debut)}, renouvelable "
                f"dans les conditions prévues par {AUDCG}."
            ),
        ),
        (
            "para",
            f"Article 3 – Loyer. Le loyer mensuel est fixé à {fcfa(loyer)}, payable d'avance le 5 de chaque mois.",
        ),
        (
            "para",
            f"Article 4 – Dépôt de garantie. Le Preneur verse un dépôt de garantie de {fcfa(loyer * 3)}.",
        ),
        (
            "para",
            (
                "Article 5 – Clause résolutoire. À défaut de paiement d'un seul terme de loyer à son échéance, et "
                "un mois après un commandement de payer demeuré infructueux, le bail sera résilié de plein droit "
                "si bon semble au Bailleur."
            ),
        ),
        ("para", f"Fait à Dakar, le {jj(debut)}."),
        ("signature", ["Le Bailleur", "", "Le Preneur"]),
    ]


def statuts(c: Ctx) -> list[Bloc]:
    f = c.f
    if f.get("operation") == "cession":
        denomination = c.client.nom
        capital = int(f.get("parts", 100)) * 10_000 * 4
        associes = {f.get("cessionnaire", "Associé A"): 25, c.client.interlocuteur.nom_complet: 75}
        gerant = c.client.interlocuteur.nom_complet
        siege = c.client.adresse
        objet = ref.SECTEURS.get(c.client.secteur or "", "toutes activités commerciales")
        agrement = "unanimité des associés"
    else:
        denomination = f.get("denomination", "")
        capital = int(f.get("capital", 1_000_000))
        associes = f.get("associes", {})
        gerant = f.get("gerant", "")
        siege = f.get("siege", "")
        objet = f.get("objet", "")
        agrement = (
            "unanimité des associés"
            if f.get("agrement_cession")
            else "majorité des associés représentant au moins les trois quarts des parts sociales"
        )
    nb_parts = capital // 10_000
    blocs: list[Bloc] = []
    if c.doc.categorie == "PROJET_STATUTS":
        blocs.append(("para", "PROJET – document de travail soumis à la relecture du client"))
    blocs += [
        ("titre", f"STATUTS DE LA SOCIÉTÉ {denomination.upper()}"),
        ("para", f"Société à responsabilité limitée au capital de {fcfa(capital)} – Siège social : {siege}"),
        ("section", "TITRE I – FORME, OBJET, DÉNOMINATION, SIÈGE, DURÉE"),
        (
            "para",
            (
                f"Article 1 – Forme. Il est formé une société à responsabilité limitée régie par {AUSCGIE} et par "
                "les présents statuts."
            ),
        ),
        ("para", f"Article 2 – Objet. La société a pour objet, au Sénégal et à l'étranger : {objet}."),
        ("para", f"Article 3 – Dénomination. La société a pour dénomination : {denomination}."),
        ("para", f"Article 4 – Siège. Le siège social est fixé à : {siege}."),
        (
            "para",
            (
                "Article 5 – Durée. La durée de la société est fixée à 99 ans à compter de son immatriculation au "
                "Registre du Commerce et du Crédit Mobilier."
            ),
        ),
        ("section", "TITRE II – APPORTS, CAPITAL SOCIAL"),
        (
            "para",
            (
                f"Article 6 – Capital. Le capital social est fixé à {fcfa(capital)}, divisé en {nb_parts} parts "
                "sociales de 10 000 FCFA chacune, entièrement souscrites et libérées, réparties comme suit :"
            ),
        ),
        (
            "tableau",
            [["Associé", "Pourcentage", "Nombre de parts"]]
            + [[nom, f"{pct} %", str(nb_parts * int(pct) // 100)] for nom, pct in associes.items()],
        ),
        ("section", "TITRE III – CESSION DES PARTS"),
        (
            "para",
            (
                f"Article 7 – Agrément. Les parts sociales ne peuvent être cédées à des tiers qu'avec le "
                f"consentement de la {agrement}."
            ),
        ),
        ("section", "TITRE IV – GÉRANCE"),
        (
            "para",
            f"Article 8 – Gérance. La société est gérée par {gerant}, nommé(e) pour une durée indéterminée.",
        ),
        ("section", "TITRE V – DÉCISIONS COLLECTIVES, EXERCICE SOCIAL"),
        (
            "para",
            (
                "Article 9 – Assemblées. Les décisions ordinaires sont adoptées par un ou plusieurs associés "
                "représentant plus de la moitié du capital social."
            ),
        ),
        (
            "para",
            (
                "Article 10 – Exercice social. L'exercice social commence le 1er janvier et se termine le "
                "31 décembre de chaque année."
            ),
        ),
        ("para", f"Fait à Dakar, le {jj(c.doc.date)}."),
        ("signature", ["Les associés"] + list(associes)),
    ]
    return blocs


def attestation_rccm(c: Ctx) -> list[Bloc]:
    f = c.f
    modificative = "modification" in f
    lignes = [
        ["Rubrique", "Information"],
        ["Dénomination", f.get("denomination") or c.client.nom],
        ["Numéro RCCM", f.get("rccm") or c.client.rccm or ""],
        ["Date d'inscription", jj(c.doc.date)],
    ]
    if modificative:
        lignes.append(["Nature de la modification", str(f.get("modification"))])
    else:
        lignes += [
            ["Forme juridique", "Société à responsabilité limitée"],
            ["Capital social", fcfa(int(f.get("capital", 0)))],
            ["Siège social", str(f.get("siege", ""))],
            ["Gérant", str(f.get("gerant", ""))],
        ]
    return [
        (
            "entete",
            REPUBLIQUE
            + [
                "Greffe du Tribunal de commerce hors classe de Dakar",
                "Registre du Commerce et du Crédit Mobilier",
            ],
        ),
        ("titre", "INSCRIPTION MODIFICATIVE" if modificative else "ATTESTATION D'IMMATRICULATION"),
        ("tableau", lignes),
        ("para", "La présente attestation est délivrée pour servir et valoir ce que de droit."),
        ("signature", ["Le Greffier en chef"]),
    ]


def acte_cession(c: Ctx) -> list[Bloc]:
    f = c.f
    return [
        ("titre", "ACTE DE CESSION DE PARTS SOCIALES"),
        ("section", "ENTRE LES SOUSSIGNÉS"),
        ("para", f"{f.get('cedant')}, associé de la société {c.client.nom}, ci-après « le Cédant »,"),
        ("para", f"ET {f.get('cessionnaire')}, ci-après « le Cessionnaire »."),
        (
            "para",
            (
                f"Article 1 – Cession. Le Cédant cède au Cessionnaire {f.get('parts')} parts sociales de la société "
                f"{c.client.nom}, RCCM {c.client.rccm}."
            ),
        ),
        (
            "para",
            (
                f"Article 2 – Prix. La cession est consentie moyennant le prix global de "
                f"{fcfa(int(f.get('prix', 0)))}, payé comptant ce jour, dont quittance."
            ),
        ),
        (
            "para",
            (
                "Article 3 – Agrément. La cession est soumise à l'agrément de la collectivité des associés dans les "
                f"conditions prévues par les statuts et par {AUSCGIE}."
            ),
        ),
        (
            "para",
            (
                "Article 4 – Opposabilité. La cession sera rendue opposable à la société et aux tiers par dépôt "
                "d'un original au siège social et inscription modificative au RCCM."
            ),
        ),
        ("para", f"Fait à Dakar, le {jj(c.doc.date)}."),
        ("signature", ["Le Cédant", "", "Le Cessionnaire"]),
    ]


def pv_ag(c: Ctx) -> list[Bloc]:
    f = c.f
    return [
        ("titre", f"PROCÈS-VERBAL DE L'ASSEMBLÉE GÉNÉRALE EXTRAORDINAIRE DU {jj(c.doc.date)}"),
        ("para", f"Société {c.client.nom} – RCCM {c.client.rccm} – {c.client.adresse}"),
        (
            "para",
            (
                "Les associés se sont réunis en assemblée générale extraordinaire sur convocation de la gérance. "
                "Tous les associés sont présents ou représentés ; l'assemblée peut valablement délibérer."
            ),
        ),
        ("section", "ORDRE DU JOUR"),
        (
            "liste",
            [
                f"Agrément de {f.get('cessionnaire')} en qualité de nouvel associé",
                "Modification corrélative des statuts",
                "Pouvoirs pour formalités",
            ],
        ),
        (
            "para",
            (
                f"Première résolution – L'assemblée agrée {f.get('cessionnaire')} en qualité de nouvel associé, "
                f"à la suite de la cession de {f.get('parts')} parts par {f.get('cedant')}. Adoptée à l'"
                f"{f.get('majorite', 'unanimité')}."
            ),
        ),
        (
            "para",
            (
                "Deuxième résolution – L'assemblée décide de modifier l'article 6 des statuts relatif à la "
                "répartition du capital. Adoptée à l'unanimité."
            ),
        ),
        (
            "para",
            (
                "Troisième résolution – Tous pouvoirs sont donnés au porteur d'une copie du présent procès-verbal "
                "pour accomplir les formalités légales. Adoptée à l'unanimité."
            ),
        ),
        ("signature", ["Le Gérant", c.client.interlocuteur.nom_complet]),
    ]


MODELES: dict[str, Callable[[Ctx], list[Bloc]]] = {
    "FACTURE": facture,
    "BON_LIVRAISON": bons_livraison,
    "ETAT_LOYERS": etat_loyers,
    "MISE_EN_DEMEURE": mise_en_demeure,
    "PROTOCOLE": protocole,
    "REQUETE_IP": requete_ip,
    "CONCLUSIONS": lambda c: conclusions(c, pour_le_cabinet=True),
    "CONCLUSIONS_ADV": lambda c: conclusions(c, pour_le_cabinet=False),
    "ASSIGNATION": assignation,
    "ACTE_APPEL": acte_appel,
    "ASSIGNATION_REFERE": assignation_refere,
    "NOTE": note_interne,
    "ORDONNANCE_IP": ordonnance_ip,
    "ORDONNANCE_EXECUTOIRE": ordonnance_executoire,
    "JUGEMENT": jugement,
    "ORDONNANCE_REFERE": ordonnance_refere,
    "PV_SIGNIFICATION": pv_signification,
    "OPPOSITION": opposition,
    "PV_SAISIE": pv_saisie,
    "COMMANDEMENT": commandement,
    "CONTRAT": contrat,
    "PROJET_CONTRAT": projet_contrat,
    "OBSERVATIONS": observations,
    "BAIL": bail,
    "PROJET_STATUTS": statuts,
    "STATUTS": statuts,
    "ATTESTATION_RCCM": attestation_rccm,
    "ACTE_CESSION": acte_cession,
    "PV_AG": pv_ag,
}


def contenu(doc: Document, dossier: Dossier, client: Client, avocat: str) -> list[Bloc]:
    return MODELES[doc.categorie](Ctx(doc, dossier, client, avocat))
