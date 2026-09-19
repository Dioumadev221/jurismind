"""Histoires de dossiers : chaque matière suit un déroulé réaliste qui produit
documents et correspondances datés.

Les étapes sont exprimées en jours depuis l'ouverture. Tout ce qui tomberait
après la date de référence n'est pas généré : le dossier est alors « en cours ».
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from simulation.modeles import Avocat, Client, Correspondance, Document, Dossier, Partie

if TYPE_CHECKING:
    from simulation.generateur import Generateur


def fcfa(montant: int) -> str:
    return f"{montant:,}".replace(",", " ") + " FCFA"


def jj(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class Recit:
    """Construit la chronologie d'un dossier en s'arrêtant à la date de référence."""

    def __init__(self, g: Generateur, dossier: Dossier) -> None:
        self.g = g
        self.d = dossier
        self.termine = False  # une étape a dépassé la date de référence

    def date_de(self, jour: int) -> date:
        return self.d.date_ouverture + timedelta(days=jour)

    def _visible(self, jour: int) -> bool:
        if self.termine or self.date_de(jour) > self.g.reference:
            self.termine = True
            return False
        return True

    def doc(
        self,
        jour: int,
        categorie: str,
        libelle: str,
        sens: str,
        auteur: str,
        faits: dict[str, Any] | None = None,
        scan: float = 0.0,
        format: str = "pdf",
    ) -> Document | None:
        if not self._visible(jour):
            return None
        doc_id = self.g.next_id("doc")
        d = self.date_de(jour)
        est_scan = format == "pdf" and self.g.rng.random() < scan
        document = Document(
            id=doc_id,
            dossier_id=self.d.id,
            categorie=categorie,
            libelle=libelle,
            date=d,
            sens=sens,
            auteur=auteur,
            fichier=f"{d:%Y%m%d}_{categorie}_{doc_id}.{format}",  # préfixé du n° de dossier ensuite
            format=format,
            scan=est_scan,
            faits=faits or {},
        )
        self.d.documents.append(document)
        return document

    def corr(
        self,
        jour: int,
        sens: str,
        expediteur: str,
        destinataires: list[str],
        objet: str,
        corps: str,
        pj: list[Document | None] | None = None,
        type: str = "MAIL",
    ) -> Correspondance | None:
        if not self._visible(jour):
            return None
        rng = self.g.rng
        heure = time(rng.randint(7, 19), rng.choice([0, 5, 12, 20, 34, 41, 47, 58]))
        if sens == "E" and type == "MAIL":
            corps += rng.choice(self.g.signatures_mobile)
        c = Correspondance(
            id=self.g.next_id("corr"),
            dossier_id=self.d.id,
            type=type,
            sens=sens,
            date=datetime.combine(self.date_de(jour), heure),
            expediteur=expediteur,
            destinataires=destinataires,
            objet=objet,
            corps=corps,
            pieces_jointes=[p.id for p in (pj or []) if p is not None],
        )
        self.d.correspondances.append(c)
        return c

    def cloture(self, jour: int) -> None:
        if self._visible(jour):
            d = self.date_de(jour)
            self.d.date_cloture = d
            self.d.statut = "AR" if (self.g.reference - d).days > 730 else "CL"


# --------------------------------------------------------------------------
# Contexte commun
# --------------------------------------------------------------------------


class Acteurs:
    def __init__(self, g: Generateur, dossier: Dossier, client: Client) -> None:
        self.client = client
        self.contact = client.interlocuteur
        self.resp: Avocat = g.avocat(dossier.responsable_id)
        collab_id = next((i for i in dossier.equipe_ids if g.avocat(i).fonction == "COLLAB"), None)
        self.collab: Avocat = g.avocat(collab_id) if collab_id else self.resp
        self.assist: Avocat = g.assistante_de(dossier.responsable_id)

    def signature_client(self) -> str:
        c = self.contact
        if self.client.type == "PM":
            return f"{c.nom_complet}\n{c.fonction} – {self.client.nom}\nTél. : {c.telephone}"
        return f"{c.nom_complet}\nTél. : {c.telephone}"


# --------------------------------------------------------------------------
# Contentieux — recouvrement de créance (injonction de payer, AUPSRVE)
# --------------------------------------------------------------------------


def recouvrement(g: Generateur, d: Dossier, client: Client) -> None:
    rng = g.rng
    a = Acteurs(g, d, client)
    r = Recit(g, d)
    debiteur = g.societe_tierce()
    avocat_adv = g.avocat_adverse()
    huissier = g.huissier()

    nb = rng.randint(2, 4)
    factures: list[dict[str, Any]] = []
    for i in range(nb):
        dt = d.date_ouverture - timedelta(days=rng.randint(90, 300))
        factures.append(
            {
                "numero": f"FA-{dt.year}-{rng.randint(100, 999)}",
                "date": dt.isoformat(),
                "montant": rng.randrange(800_000, 9_000_000, 50_000),
            }
        )
    factures.sort(key=lambda f: f["date"])
    total = sum(f["montant"] for f in factures)
    d.enjeu = total
    d.intitule = f"{client.nom} c/ {debiteur.nom} – Recouvrement"
    d.juridiction = g.juridictions["commerce"]
    d.parties += [
        Partie("ADV", debiteur.nom, debiteur.adresse, debiteur.email, debiteur.telephone),
        Partie("HUIS", huissier.nom, huissier.adresse, huissier.email),
    ]
    d.faits.update(debiteur=debiteur.nom, montant_principal=total, factures=factures)
    liste = ", ".join(f["numero"] for f in factures)

    pieces = [
        r.doc(
            0,
            "FACTURE",
            f"Facture {f['numero']}",
            "E",
            client.nom,
            {
                "numero": f["numero"],
                "date": f["date"],
                "montant": f["montant"],
                "debiteur": debiteur.nom,
            },
            scan=0.3,
        )
        for f in factures
    ]
    pieces.append(
        r.doc(
            0,
            "BON_LIVRAISON",
            "Bons de livraison signés",
            "E",
            client.nom,
            {"debiteur": debiteur.nom},
            scan=0.8,
        )
    )
    r.corr(
        0,
        "E",
        a.contact.email,
        [a.resp.email],
        f"Impayés {debiteur.nom}",
        f"Maître,\n\nNous rencontrons des difficultés de paiement avec notre client {debiteur.nom}, "
        f"qui reste nous devoir la somme de {fcfa(total)} au titre des factures {liste}. "
        "Malgré plusieurs relances de notre service comptable, aucun règlement n'est intervenu.\n\n"
        "Vous trouverez en pièces jointes les factures et les bons de livraison correspondants. "
        "Nous souhaitons engager le recouvrement dans les meilleurs délais.\n\n"
        f"Cordialement,\n{a.signature_client()}",
        pieces,
    )
    r.corr(
        2,
        "S",
        a.collab.email,
        [a.contact.email],
        f"RE: Impayés {debiteur.nom}",
        f"Madame, Monsieur,\n\nNous accusons réception de votre dossier. Nous adressons dès cette semaine "
        f"une mise en demeure à {debiteur.nom} lui laissant un délai de huit jours pour régler "
        f"la somme de {fcfa(total)}.\n\nBien à vous,\n{a.collab.titre}",
    )
    med = r.doc(
        4,
        "MISE_EN_DEMEURE",
        f"Mise en demeure adressée à {debiteur.nom}",
        "S",
        a.resp.titre,
        {
            "destinataire": debiteur.nom,
            "montant": total,
            "delai_jours": 8,
            "factures": factures,
        },
        format="docx",
    )
    r.corr(
        4,
        "S",
        a.resp.email,
        [debiteur.adresse or debiteur.nom],
        "Mise en demeure – règlement de factures",
        f"Lettre recommandée avec accusé de réception adressée à {debiteur.nom}.",
        [med],
        type="COURRIER",
    )

    if rng.random() < 0.25:  # règlement amiable
        gerant = g.personne()
        r.corr(
            15,
            "E",
            debiteur.telephone or "inconnu",
            [a.collab.email],
            "Appel du débiteur",
            f"Appel de M. {gerant}, gérant de {debiteur.nom}. Reconnaît la dette, invoque des difficultés "
            "de trésorerie et propose un paiement en trois échéances mensuelles.",
            type="TEL",
        )
        r.corr(
            16,
            "S",
            a.collab.email,
            [a.contact.email],
            f"{debiteur.nom} – proposition d'échéancier",
            f"Madame, Monsieur,\n\n{debiteur.nom} propose de régler {fcfa(total)} en trois mensualités. "
            "Nous vous recommandons d'accepter sous réserve d'un protocole écrit prévoyant la déchéance "
            f"du terme en cas d'impayé.\n\nMerci de nous confirmer votre accord.\n\n{a.collab.titre}",
        )
        r.corr(
            18,
            "E",
            a.contact.email,
            [a.collab.email],
            f"RE: {debiteur.nom} – proposition d'échéancier",
            f"Maître,\n\nNous acceptons l'échéancier aux conditions que vous indiquez.\n\n{a.signature_client()}",
        )
        r.doc(
            25,
            "PROTOCOLE",
            f"Protocole d'accord transactionnel avec {debiteur.nom}",
            "S",
            a.resp.titre,
            {
                "debiteur": debiteur.nom,
                "montant": total,
                "echeances": 3,
                "decheance_du_terme": True,
            },
            format="docx",
        )
        r.corr(
            100,
            "S",
            a.collab.email,
            [a.contact.email],
            f"{debiteur.nom} – dossier soldé",
            f"Madame, Monsieur,\n\n{debiteur.nom} a réglé la dernière échéance. Nous clôturons le dossier."
            f"\n\n{a.collab.titre}",
        )
        r.cloture(102)
        return

    r.corr(
        24,
        "S",
        a.collab.email,
        [a.contact.email],
        f"{debiteur.nom} – absence de règlement",
        f"Madame, Monsieur,\n\nLe délai de la mise en demeure est expiré sans règlement. Nous vous proposons "
        "de présenter une requête en injonction de payer devant le Président du Tribunal de commerce "
        f"hors classe de Dakar.\n\n{a.collab.titre}",
    )
    r.corr(
        26,
        "E",
        a.contact.email,
        [a.collab.email],
        f"RE: {debiteur.nom} – absence de règlement",
        f"Maître,\n\nNous vous donnons notre accord pour engager la procédure.\n\n{a.signature_client()}",
    )
    requete = r.doc(
        30,
        "REQUETE_IP",
        "Requête aux fins d'injonction de payer",
        "S",
        a.resp.titre,
        {
            "creancier": client.nom,
            "debiteur": debiteur.nom,
            "montant": total,
            "juridiction": d.juridiction,
        },
        format="docx",
    )
    num_ord = f"{rng.randint(100, 2999)}/{r.date_de(45).year}"
    ordo = r.doc(
        45,
        "ORDONNANCE_IP",
        f"Ordonnance d'injonction de payer n° {num_ord}",
        "E",
        f"Président du {d.juridiction}",
        {
            "numero": num_ord,
            "debiteur": debiteur.nom,
            "montant": total,
            "date": r.date_de(45).isoformat(),
        },
        scan=0.6,
    )
    r.corr(
        47,
        "S",
        a.collab.email,
        [a.contact.email],
        f"{debiteur.nom} – ordonnance d'injonction de payer",
        f"Madame, Monsieur,\n\nNous avons obtenu l'ordonnance d'injonction de payer n° {num_ord} condamnant "
        f"{debiteur.nom} au paiement de {fcfa(total)}. Nous la faisons signifier par huissier.\n\n"
        f"{a.collab.titre}",
        [ordo],
    )
    r.corr(
        48,
        "S",
        a.assist.email,
        [huissier.email or huissier.nom],
        f"Signification – ordonnance n° {num_ord}",
        f"Maître,\n\nNous vous prions de bien vouloir signifier l'ordonnance ci-jointe à {debiteur.nom}, "
        f"{debiteur.adresse}.\n\nRespectueusement,\n{a.assist.nom_complet}\nAssistante de {a.resp.titre}",
        [ordo, requete],
    )
    date_sign = r.date_de(55)
    pv = r.doc(
        55,
        "PV_SIGNIFICATION",
        "Procès-verbal de signification de l'ordonnance",
        "E",
        huissier.nom,
        {
            "date_signification": date_sign.isoformat(),
            "destinataire": debiteur.nom,
            "ordonnance": num_ord,
        },
        scan=0.8,
    )
    r.corr(
        57,
        "E",
        huissier.email or huissier.nom,
        [a.assist.email],
        f"PV de signification – {debiteur.nom}",
        f"Madame,\n\nVeuillez trouver ci-joint le procès-verbal de signification de l'ordonnance n° {num_ord}, "
        f"signifiée le {jj(date_sign)} à {debiteur.nom}.\n\nL'Étude",
        [pv],
    )

    if rng.random() < 0.35:  # opposition du débiteur
        d.parties.append(Partie("AVADV", avocat_adv.nom, avocat_adv.adresse, avocat_adv.email))
        opp = r.doc(
            66,
            "OPPOSITION",
            "Exploit d'opposition avec assignation",
            "E",
            avocat_adv.nom,
            {
                "opposant": debiteur.nom,
                "avocat": avocat_adv.nom,
                "motif": "contestation de la conformité des marchandises livrées",
            },
            scan=0.7,
        )
        r.corr(
            68,
            "E",
            avocat_adv.email or avocat_adv.nom,
            [a.resp.email],
            f"{client.nom} c/ {debiteur.nom}",
            f"Mon cher confrère,\n\nJe vous informe que je suis constitué pour {debiteur.nom}, qui a formé "
            f"opposition à l'ordonnance n° {num_ord}.\n\nBien confraternellement,\n{avocat_adv.nom}",
            [opp],
        )
        r.corr(
            69,
            "S",
            a.resp.email,
            [a.contact.email],
            f"{debiteur.nom} – opposition",
            f"Madame, Monsieur,\n\n{debiteur.nom} a formé opposition à l'ordonnance. L'affaire sera donc "
            "débattue au fond devant le Tribunal de commerce. Nous préparons nos conclusions.\n\n"
            f"{a.resp.titre}",
        )
        d.numero_rg = f"RG n° {rng.randint(100, 4999)}/{r.date_de(70).year}"
        r.doc(
            95,
            "CONCLUSIONS",
            "Conclusions en réponse",
            "S",
            a.resp.titre,
            {"rg": d.numero_rg, "demande": total},
            format="docx",
        )
        r.doc(
            125,
            "CONCLUSIONS_ADV",
            "Conclusions de l'opposant",
            "E",
            avocat_adv.nom,
            {"rg": d.numero_rg},
        )
        date_delib = r.date_de(170)
        r.corr(
            140,
            "S",
            a.collab.email,
            [a.contact.email],
            f"{debiteur.nom} – mise en délibéré",
            f"Madame, Monsieur,\n\nL'affaire a été plaidée ce jour et mise en délibéré au {jj(date_delib)}."
            f"\n\n{a.collab.titre}",
        )
        gagne = rng.random() < 0.75
        r.doc(
            170,
            "JUGEMENT",
            "Jugement du Tribunal de commerce",
            "E",
            d.juridiction,
            {
                "rg": d.numero_rg,
                "date": date_delib.isoformat(),
                "dispositif": "rejette l'opposition et condamne le débiteur"
                if gagne
                else "déclare l'opposition partiellement fondée",
                "montant_alloue": total if gagne else total // 2,
            },
            scan=0.5,
        )
        r.corr(
            173,
            "S",
            a.resp.email,
            [a.contact.email],
            f"{debiteur.nom} – jugement rendu",
            f"Madame, Monsieur,\n\nLe tribunal a rendu sa décision : "
            f"{'il rejette l’opposition et condamne' if gagne else 'il réduit la condamnation de'} "
            f"{debiteur.nom}. Montant alloué : {fcfa(total if gagne else total // 2)}.\n\n{a.resp.titre}",
        )
        r.cloture(200)
        return

    r.doc(
        75,
        "ORDONNANCE_EXECUTOIRE",
        "Ordonnance revêtue de la formule exécutoire",
        "E",
        d.juridiction,
        {"ordonnance": num_ord},
        scan=0.6,
    )
    banque = rng.choice(g.banques)
    saisie = r.doc(
        85,
        "PV_SAISIE",
        "Procès-verbal de saisie-attribution de créances",
        "E",
        huissier.nom,
        {"tiers_saisi": banque, "montant": total, "debiteur": debiteur.nom},
        scan=0.8,
    )
    r.corr(
        86,
        "E",
        huissier.email or huissier.nom,
        [a.assist.email],
        f"Saisie-attribution – {debiteur.nom}",
        f"Madame,\n\nLa saisie-attribution a été pratiquée entre les mains de {banque}.\n\nL'Étude",
        [saisie],
    )
    r.corr(
        115,
        "S",
        a.collab.email,
        [a.contact.email],
        f"{debiteur.nom} – fonds recouvrés",
        f"Madame, Monsieur,\n\nLes fonds saisis ont été versés. Nous vous adressons le décompte et "
        f"clôturons le dossier.\n\n{a.collab.titre}",
    )
    r.cloture(118)


# --------------------------------------------------------------------------
# Contentieux — litige commercial au fond
# --------------------------------------------------------------------------


def litige_commercial(g: Generateur, d: Dossier, client: Client) -> None:
    rng = g.rng
    a = Acteurs(g, d, client)
    r = Recit(g, d)
    adverse = g.societe_tierce()
    avocat_adv = g.avocat_adverse()
    huissier = g.huissier()
    objet = rng.choice(
        [
            "inexécution d'un contrat de fourniture",
            "rupture brutale d'un contrat de distribution",
            "livraison de marchandises non conformes",
            "non-paiement de travaux réalisés",
        ]
    )
    prejudice = rng.randrange(5_000_000, 150_000_000, 500_000)
    d.enjeu = prejudice
    d.intitule = f"{client.nom} c/ {adverse.nom} – {objet.capitalize()}"
    d.juridiction = g.juridictions["commerce"]
    d.parties += [
        Partie("ADV", adverse.nom, adverse.adresse, adverse.email),
        Partie("AVADV", avocat_adv.nom, avocat_adv.adresse, avocat_adv.email),
        Partie("HUIS", huissier.nom, huissier.adresse, huissier.email),
    ]
    d.faits.update(adverse=adverse.nom, objet=objet, prejudice=prejudice)
    date_contrat = d.date_ouverture - timedelta(days=rng.randint(200, 900))

    contrat = r.doc(
        0,
        "CONTRAT",
        f"Contrat du {jj(date_contrat)} avec {adverse.nom}",
        "E",
        client.nom,
        {"date": date_contrat.isoformat(), "cocontractant": adverse.nom},
        scan=0.5,
    )
    r.corr(
        0,
        "E",
        a.contact.email,
        [a.resp.email],
        f"Litige avec {adverse.nom}",
        f"Maître,\n\nNous sommes en litige avec {adverse.nom} ({objet}). Le préjudice que nous subissons est "
        f"estimé à {fcfa(prejudice)}. Je vous transmets le contrat signé le {jj(date_contrat)}.\n\n"
        f"Pouvons-nous nous voir cette semaine ?\n\n{a.signature_client()}",
        [contrat],
    )
    r.doc(
        6,
        "NOTE",
        "Note d'analyse – chances de succès et stratégie",
        "I",
        a.collab.titre,
        {"objet": objet, "recommandation": "mise en demeure puis assignation au fond"},
        format="docx",
    )
    r.doc(
        12,
        "MISE_EN_DEMEURE",
        f"Mise en demeure adressée à {adverse.nom}",
        "S",
        a.resp.titre,
        {"destinataire": adverse.nom, "montant": prejudice, "delai_jours": 15},
        format="docx",
    )
    assign = r.doc(
        40,
        "ASSIGNATION",
        f"Assignation de {adverse.nom} devant le Tribunal de commerce",
        "S",
        a.resp.titre,
        {"defendeur": adverse.nom, "demande": prejudice, "juridiction": d.juridiction},
        format="docx",
    )
    r.corr(
        41,
        "S",
        a.assist.email,
        [huissier.email or huissier.nom],
        f"Assignation – {adverse.nom}",
        f"Maître,\n\nMerci de bien vouloir délivrer l'assignation ci-jointe à {adverse.nom}.\n\n"
        f"{a.assist.nom_complet}",
        [assign],
    )
    d.numero_rg = f"RG n° {rng.randint(100, 4999)}/{r.date_de(50).year}"
    r.corr(
        75,
        "E",
        avocat_adv.email or avocat_adv.nom,
        [a.resp.email],
        f"{d.intitule} – {d.numero_rg}",
        f"Mon cher confrère,\n\nJe me constitue pour {adverse.nom} et vous communique mes conclusions.\n\n"
        f"Bien confraternellement,\n{avocat_adv.nom}",
        [
            r.doc(
                74,
                "CONCLUSIONS_ADV",
                "Conclusions en défense",
                "E",
                avocat_adv.nom,
                {
                    "rg": d.numero_rg,
                    "moyens": "force majeure et absence de préjudice prouvé",
                },
            )
        ],
    )
    r.doc(
        105,
        "CONCLUSIONS",
        "Conclusions en réplique",
        "S",
        a.resp.titre,
        {"rg": d.numero_rg},
        format="docx",
    )
    renvoi = r.date_de(150)
    r.corr(
        130,
        "S",
        a.collab.email,
        [a.contact.email],
        f"{adverse.nom} – renvoi",
        f"Madame, Monsieur,\n\nÀ l'audience de ce jour, l'affaire a été renvoyée au {jj(renvoi)} à la demande "
        f"de la partie adverse.\n\n{a.collab.titre}",
    )
    delib = r.date_de(190)
    r.corr(
        150,
        "S",
        a.collab.email,
        [a.contact.email],
        f"{adverse.nom} – mise en délibéré",
        f"Madame, Monsieur,\n\nL'affaire a été plaidée et mise en délibéré au {jj(delib)}.\n\n{a.collab.titre}",
    )
    alloue = int(prejudice * rng.choice([0, 0.4, 0.6, 0.8, 1.0]))
    r.doc(
        190,
        "JUGEMENT",
        "Jugement du Tribunal de commerce",
        "E",
        d.juridiction,
        {
            "rg": d.numero_rg,
            "date": delib.isoformat(),
            "montant_alloue": alloue,
            "dispositif": "déboute le demandeur" if alloue == 0 else "condamne le défendeur",
        },
        scan=0.5,
    )
    r.corr(
        193,
        "S",
        a.resp.email,
        [a.contact.email],
        f"{adverse.nom} – jugement",
        f"Madame, Monsieur,\n\nLe tribunal a statué. Montant alloué : {fcfa(alloue)}. "
        "Vous disposez d'un délai pour interjeter appel ; nous vous proposons d'en discuter.\n\n"
        f"{a.resp.titre}",
    )
    if alloue == 0 and rng.random() < 0.6:
        d.juridiction = g.juridictions["appel"]
        r.doc(
            205,
            "ACTE_APPEL",
            "Acte d'appel",
            "S",
            a.resp.titre,
            {"jugement_rg": d.numero_rg},
            format="docx",
        )
        return
    r.cloture(230)


# --------------------------------------------------------------------------
# Contentieux — bail commercial (loyers impayés, expulsion en référé)
# --------------------------------------------------------------------------


def bail_commercial(g: Generateur, d: Dossier, client: Client) -> None:
    rng = g.rng
    a = Acteurs(g, d, client)
    r = Recit(g, d)
    locataire = g.societe_tierce()
    huissier = g.huissier()
    loyer = rng.randrange(300_000, 3_500_000, 50_000)
    mois = rng.randint(3, 12)
    local = f"local commercial sis {g.adresse('Dakar')}"
    d.enjeu = loyer * mois
    d.intitule = f"{client.nom} c/ {locataire.nom} – Bail commercial"
    d.juridiction = g.juridictions["tgi"]
    d.parties += [
        Partie("ADV", locataire.nom, locataire.adresse, locataire.email),
        Partie("HUIS", huissier.nom, huissier.adresse, huissier.email),
    ]
    d.faits.update(locataire=locataire.nom, loyer_mensuel=loyer, mois_impayes=mois, local=local)

    bail = r.doc(
        0,
        "BAIL",
        f"Bail commercial – {locataire.nom}",
        "E",
        client.nom,
        {"preneur": locataire.nom, "loyer_mensuel": loyer, "local": local},
        scan=0.6,
    )
    etat = r.doc(
        0,
        "ETAT_LOYERS",
        "État des loyers impayés",
        "E",
        client.nom,
        {"mois_impayes": mois, "total": loyer * mois},
    )
    r.corr(
        0,
        "E",
        a.contact.email,
        [a.resp.email],
        f"Loyers impayés – {locataire.nom}",
        f"Maître,\n\nNotre locataire {locataire.nom} ne paie plus son loyer de {fcfa(loyer)} depuis {mois} mois "
        f"({local}). Nous souhaitons récupérer les sommes dues et, à défaut, le local.\n\n"
        f"{a.signature_client()}",
        [bail, etat],
    )
    r.doc(
        5,
        "MISE_EN_DEMEURE",
        f"Mise en demeure adressée à {locataire.nom}",
        "S",
        a.resp.titre,
        {"destinataire": locataire.nom, "montant": loyer * mois, "delai_jours": 30},
        format="docx",
    )
    r.corr(
        38,
        "S",
        a.assist.email,
        [huissier.email or huissier.nom],
        f"Commandement de payer – {locataire.nom}",
        f"Maître,\n\nMerci de délivrer un commandement de payer les loyers à {locataire.nom}.\n\n"
        f"{a.assist.nom_complet}",
    )
    r.doc(
        45,
        "COMMANDEMENT",
        "Commandement de payer visant la clause résolutoire",
        "E",
        huissier.nom,
        {"montant": loyer * mois, "delai_jours": 30},
        scan=0.8,
    )
    r.doc(
        85,
        "ASSIGNATION_REFERE",
        "Assignation en référé aux fins d'expulsion",
        "S",
        a.resp.titre,
        {
            "defendeur": locataire.nom,
            "demande": "constat de la résiliation du bail et expulsion",
        },
        format="docx",
    )
    d.numero_rg = f"Référé n° {rng.randint(100, 2999)}/{r.date_de(90).year}"
    r.doc(
        110,
        "ORDONNANCE_REFERE",
        "Ordonnance de référé",
        "E",
        f"Président du {d.juridiction}",
        {
            "numero": d.numero_rg,
            "dispositif": "constate la résiliation du bail, ordonne l'expulsion",
            "condamnation": loyer * mois,
        },
        scan=0.6,
    )
    r.corr(
        112,
        "S",
        a.resp.email,
        [a.contact.email],
        f"{locataire.nom} – ordonnance d'expulsion",
        f"Madame, Monsieur,\n\nLe juge des référés a constaté la résiliation du bail et ordonné l'expulsion "
        f"de {locataire.nom}, condamné à payer {fcfa(loyer * mois)}.\n\n{a.resp.titre}",
    )
    r.cloture(150)


# --------------------------------------------------------------------------
# Affaires — droit des sociétés (constitution ou cession de parts)
# --------------------------------------------------------------------------


def societe(g: Generateur, d: Dossier, client: Client) -> None:
    rng = g.rng
    a = Acteurs(g, d, client)
    r = Recit(g, d)
    greffe = "Greffe du Tribunal de commerce hors classe de Dakar"

    if client.type == "PP":
        secteur = rng.choice(list(g.secteurs))
        denomination = f"{rng.choice(g.prefixes)} {secteur} SARL"
        capital = rng.choice([1_000_000, 2_000_000, 5_000_000, 10_000_000])
        associes = [client.nom, g.personne()]
        parts = rng.choice([(60, 40), (50, 50), (70, 30)])
        d.intitule = f"Constitution de la société {denomination}"
        d.faits.update(
            operation="constitution",
            denomination=denomination,
            capital=capital,
            associes=dict(zip(associes, parts, strict=True)),
            gerant=client.nom,
            objet=g.secteurs[secteur],
            siege=g.adresse("Dakar"),
        )
        r.corr(
            0,
            "E",
            a.contact.email,
            [a.resp.email],
            "Création de société",
            f"Maître,\n\nJe souhaite créer une SARL dans le secteur {g.secteurs[secteur]} avec un associé, "
            f"au capital de {fcfa(capital)}. Pouvez-vous m'accompagner ?\n\n{a.signature_client()}",
        )
        r.corr(
            3,
            "S",
            a.collab.email,
            [a.contact.email],
            "RE: Création de société",
            "Monsieur,\n\nMerci de nous transmettre : la dénomination envisagée, la répartition du capital, "
            "l'adresse du siège et les pièces d'identité des associés.\n\n" + a.collab.titre,
        )
        projet = r.doc(
            15,
            "PROJET_STATUTS",
            f"Projet de statuts – {denomination}",
            "S",
            a.collab.titre,
            dict(d.faits),
            format="docx",
        )
        r.corr(
            15,
            "S",
            a.collab.email,
            [a.contact.email],
            f"Projet de statuts – {denomination}",
            f"Monsieur,\n\nVeuillez trouver ci-joint le projet de statuts pour relecture.\n\n{a.collab.titre}",
            [projet],
        )
        r.corr(
            22,
            "E",
            a.contact.email,
            [a.collab.email],
            f"RE: Projet de statuts – {denomination}",
            "Maître,\n\nMerci. Mon associé souhaite que les cessions de parts à des tiers soient soumises à "
            "l'agrément unanime des associés.\n\n" + a.signature_client(),
        )
        r.doc(
            28,
            "STATUTS",
            f"Statuts signés – {denomination}",
            "E",
            client.nom,
            {**d.faits, "agrement_cession": "unanimité"},
            scan=0.7,
        )
        rccm = f"SN-DKR-{r.date_de(45).year}-B-{rng.randint(10000, 99999)}"
        r.doc(
            45,
            "ATTESTATION_RCCM",
            "Attestation d'immatriculation au RCCM",
            "E",
            greffe,
            {"denomination": denomination, "rccm": rccm},
            scan=0.9,
        )
        r.corr(
            46,
            "S",
            a.collab.email,
            [a.contact.email],
            f"{denomination} – immatriculation",
            f"Monsieur,\n\nLa société {denomination} est immatriculée sous le numéro {rccm}.\n\n{a.collab.titre}",
        )
        r.cloture(50)
        return

    cedant, cessionnaire = g.personne(), g.personne()
    nb_parts = rng.choice([100, 250, 500, 1000])
    prix = nb_parts * rng.choice([10_000, 20_000, 50_000])
    d.intitule = f"{client.nom} – Cession de parts sociales"
    d.enjeu = prix
    d.faits.update(
        operation="cession",
        cedant=cedant,
        cessionnaire=cessionnaire,
        parts=nb_parts,
        prix=prix,
    )
    r.corr(
        0,
        "E",
        a.contact.email,
        [a.resp.email],
        "Cession de parts",
        f"Maître,\n\nM. {cedant} souhaite céder ses {nb_parts} parts à M. {cessionnaire} pour {fcfa(prix)}. "
        f"Merci de préparer les actes.\n\n{a.signature_client()}",
    )
    r.doc(
        8,
        "ACTE_CESSION",
        "Acte de cession de parts sociales",
        "S",
        a.collab.titre,
        dict(d.faits),
        format="docx",
    )
    r.doc(
        15,
        "PV_AG",
        "Procès-verbal d'assemblée générale extraordinaire – agrément du cessionnaire",
        "S",
        a.collab.titre,
        {"decision": f"agrément de {cessionnaire}", "majorite": "unanimité"},
        format="docx",
    )
    r.doc(
        20,
        "STATUTS",
        "Statuts mis à jour",
        "S",
        a.collab.titre,
        {"client": client.nom},
        format="docx",
    )
    r.doc(
        40,
        "ATTESTATION_RCCM",
        "Inscription modificative au RCCM",
        "E",
        greffe,
        {"rccm": client.rccm, "modification": "cession de parts"},
        scan=0.9,
    )
    r.cloture(45)


# --------------------------------------------------------------------------
# Affaires — rédaction et négociation d'un contrat commercial
# --------------------------------------------------------------------------


def contrat_commercial(g: Generateur, d: Dossier, client: Client) -> None:
    rng = g.rng
    a = Acteurs(g, d, client)
    r = Recit(g, d)
    partenaire = g.societe_tierce()
    avocat_adv = g.avocat_adverse()
    type_contrat = rng.choice(
        [
            "distribution exclusive",
            "prestation de services",
            "fourniture",
            "sous-traitance",
        ]
    )
    duree = rng.choice([12, 24, 36, 60])
    montant = rng.randrange(10_000_000, 400_000_000, 1_000_000)
    clauses = {
        "type": type_contrat,
        "cocontractant": partenaire.nom,
        "duree_mois": duree,
        "montant_annuel": montant,
        "preavis_resiliation_jours": rng.choice([30, 60, 90]),
        "penalite_retard": f"{rng.choice([0.5, 1, 2])} % par semaine de retard",
        "exclusivite": type_contrat == "distribution exclusive",
        "territoire": rng.choice(["Sénégal", "Sénégal et Gambie", "zone UEMOA"]),
        "reglement_litiges": rng.choice(["arbitrage CAMC-D", "Tribunal de commerce hors classe de Dakar"]),
        "droit_applicable": "droit OHADA et droit sénégalais",
    }
    d.intitule = f"{client.nom} – Contrat de {type_contrat} avec {partenaire.nom}"
    d.enjeu = montant
    d.parties += [
        Partie("TIERS", partenaire.nom, partenaire.adresse, partenaire.email),
        Partie("AVADV", avocat_adv.nom, avocat_adv.adresse, avocat_adv.email),
    ]
    d.faits.update(clauses)

    r.corr(
        0,
        "E",
        a.contact.email,
        [a.resp.email],
        f"Contrat avec {partenaire.nom}",
        f"Maître,\n\nNous allons signer un contrat de {type_contrat} avec {partenaire.nom} pour {duree} mois, "
        f"pour un montant annuel d'environ {fcfa(montant)}. Pouvez-vous rédiger le contrat ?\n\n"
        f"{a.signature_client()}",
    )
    v1 = r.doc(
        7,
        "PROJET_CONTRAT",
        f"Projet de contrat de {type_contrat} – v1",
        "S",
        a.collab.titre,
        clauses,
        format="docx",
    )
    r.corr(
        8,
        "S",
        a.collab.email,
        [a.contact.email],
        f"Projet de contrat – {partenaire.nom}",
        f"Madame, Monsieur,\n\nVeuillez trouver le projet de contrat. Points d'attention : durée de {duree} mois, "
        f"préavis de résiliation de {clauses['preavis_resiliation_jours']} jours, règlement des litiges par "
        f"{clauses['reglement_litiges']}.\n\n{a.collab.titre}",
        [v1],
    )
    obs = {"demande": "réduire la pénalité de retard et allonger le préavis à 120 jours"}
    r.corr(
        20,
        "E",
        avocat_adv.email or avocat_adv.nom,
        [a.collab.email],
        f"Projet de contrat – {client.nom}",
        f"Chère consœur, cher confrère,\n\nMa cliente {partenaire.nom} souhaite {obs['demande']}. "
        f"Vous trouverez mes observations en pièce jointe.\n\nBien confraternellement,\n{avocat_adv.nom}",
        [
            r.doc(
                20,
                "OBSERVATIONS",
                "Observations de la partie adverse sur le projet",
                "E",
                avocat_adv.nom,
                obs,
                format="docx",
            )
        ],
    )
    final = {**clauses, "preavis_resiliation_jours": 90}
    r.doc(
        28,
        "PROJET_CONTRAT",
        f"Projet de contrat de {type_contrat} – v2",
        "S",
        a.collab.titre,
        final,
        format="docx",
    )
    signe = r.doc(
        40,
        "CONTRAT",
        f"Contrat de {type_contrat} signé avec {partenaire.nom}",
        "E",
        client.nom,
        {**final, "date_signature": r.date_de(40).isoformat()},
        scan=0.7,
    )
    r.corr(
        41,
        "E",
        a.contact.email,
        [a.collab.email],
        f"Contrat signé – {partenaire.nom}",
        f"Maître,\n\nLe contrat a été signé hier, vous trouverez l'exemplaire scanné.\n\n{a.signature_client()}",
        [signe],
    )
    r.cloture(45)


SCENARIOS = {
    "RECOUV": ("CTX", recouvrement),
    "COMM": ("CTX", litige_commercial),
    "BAIL": ("CTX", bail_commercial),
    "SOC": ("CSL", societe),
    "CONTRAT": ("CSL", contrat_commercial),
}
