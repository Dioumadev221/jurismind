"use strict";

/**
 * Le dossier, et l'échéancier.
 *
 * Tout le reste de l'interface est une porte d'entrée ; c'est ici qu'on arrive. Un avocat ne
 * travaille pas sur « un document » ni sur « un client » : il travaille sur une affaire, et
 * une affaire est un paquet — des parties, une juridiction, un enjeu, une équipe qui y a
 * accès, des pièces, des courriers, des délais. Cet écran les met côte à côte, parce qu'une
 * pièce lue hors de son dossier ne veut rien dire.
 *
 * L'échéancier répond à l'autre question, celle qu'aucune fiche de dossier ne pose : qu'est-ce
 * qui tombe cette semaine, tous dossiers confondus ? Un délai ne se rate pas faute de l'avoir
 * compris, il se rate faute d'avoir rouvert le dossier à temps.
 */

const QUALITES = {
  adverse: "Partie adverse",
  avocat_adverse: "Avocat adverse",
  huissier: "Huissier",
  tiers: "Tiers",
};

const STATUTS = { en_cours: "En cours", clos: "Clos", archive: "Archivé" };

const ONGLETS_DOSSIER = [
  { cle: "chrono", label: "Chronologie" },
  { cle: "pieces", label: "Pièces" },
  { cle: "echanges", label: "Échanges" },
  { cle: "conflits", label: "Conflits" },
  { cle: "assistant", label: "Assistant" },
];

/** Le seul chemin d'entrée : il met l'état à jour puis laisse le routeur faire son travail. */
function ouvrirDossier(reference, onglet = "chrono") {
  etat.dossierCourant = reference;
  etat.ongletDossier = onglet;
  etat.demandeDossier = "";
  aller("dossier");
}

async function ecranDossier() {
  const reference = etat.dossierCourant;
  if (!reference) {
    aller("dossiers");
    return;
  }
  patienter(`Ouverture du dossier ${reference}…`);
  const base = `/dossiers/${encodeURIComponent(reference)}`;

  // Cinq lectures en parallèle : elles ne touchent que la base, donc l'écran s'affiche d'un
  // coup. Les conflits et l'assistant, eux, attendent qu'on ouvre leur onglet.
  const [fiche, attention, chronologie, pieces, echanges] = await Promise.all([
    api(base),
    api(`${base}/attention`),
    api(`${base}/chronologie`),
    api(`${base}/documents`),
    api(`${base}/echanges`),
  ]);

  $("#fil-ariane").textContent = `Dossiers · ${fiche.reference}`;
  const parties = fiche.parties.filter((partie) => partie.qualite !== "client");
  const comptes = {
    chrono: chronologie.length,
    pieces: pieces.length,
    echanges: echanges.length,
    conflits: parties.filter((partie) => partie.qualite === "adverse").length,
    assistant: "",
  };

  $("#ecran").innerHTML = `
    <button id="retour-dossiers" class="btn btn-ghost" style="white-space:nowrap;align-self:flex-start;margin-bottom:-12px">
      <svg width="15" height="15" viewBox="0 0 24 24" style="fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round"><path d="m12 19-7-7 7-7"></path><path d="M19 12H5"></path></svg>
      Mes dossiers
    </button>

    <div style="display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap">
      <div style="flex:1;min-width:300px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">
          <span style="font-family:var(--font-heading);font-weight:600;font-size:15px;color:var(--color-accent-700)">${texte(fiche.reference)}</span>
          <span class="tag tag-accent">${texte(STATUTS[fiche.statut] || fiche.statut)}</span>
          ${/* La colonne porte déjà son préfixe, et ce n'est pas toujours « RG » : il y a des « Référé ». */ ""}
          ${fiche.numero_rg ? `<span class="tag tag-outline">${texte(fiche.numero_rg)}</span>` : ""}
          ${fiche.confidentiel ? `<span class="tag tag-outline">Confidentiel</span>` : ""}
        </div>
        <h1 style="font-size:30px;margin:0;max-width:820px;text-wrap:pretty">${texte(fiche.intitule)}</h1>
      </div>
    </div>

    ${blocDelais(attention)}

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));border:1px solid var(--color-divider)">
      ${caseFiche("Client", fiche.client || "—", fiche.client ? 'data-client="oui"' : "")}
      ${caseFiche("Matière", MATIERES[fiche.matiere] || fiche.matiere || "—")}
      ${caseFiche("Enjeu (FCFA)", montant(fiche.enjeu_fcfa), "", true)}
      ${caseFiche("Juridiction", fiche.juridiction || "—")}
      ${caseFiche("Ouvert le", dateLongue(fiche.date_ouverture))}
      ${caseFiche("Pièces · échanges", `${fiche.nombre_documents} · ${fiche.nombre_echanges}`)}
    </div>

    <div style="display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;align-items:start">
      <div style="display:flex;flex-direction:column;min-width:0">
        <div style="display:flex;gap:4px;border-bottom:1px solid var(--color-divider);margin-bottom:18px;flex-wrap:wrap">
          ${ONGLETS_DOSSIER.map((onglet) => {
            const actif = onglet.cle === etat.ongletDossier;
            return `<button data-onglet-dossier="${onglet.cle}" style="border:0;background:transparent;font:inherit;font-size:14px;padding:9px 12px;cursor:pointer;margin-bottom:-1px;border-bottom:2px solid ${actif ? "var(--color-accent)" : "transparent"};color:${actif ? "var(--color-text)" : "var(--color-neutral-700)"}">${texte(onglet.label)}<span style="font-size:11px;color:var(--color-neutral-600);margin-left:6px">${texte(comptes[onglet.cle])}</span></button>`;
          }).join("")}
        </div>
        <div id="corps-onglet" style="min-width:0"></div>
      </div>

      <aside style="display:flex;flex-direction:column;gap:18px">
        ${carteParties(parties)}
        ${carteEquipe(fiche.equipe)}
      </aside>
    </div>`;

  $("#retour-dossiers").addEventListener("click", () => aller("dossiers"));
  const lienClient = $("[data-client]");
  if (lienClient) {
    lienClient.addEventListener("click", (evenement) => {
      evenement.preventDefault();
      etat.clientRecherche = fiche.client;
      aller("clients");
    });
  }
  $$("[data-onglet-dossier]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      etat.ongletDossier = bouton.dataset.ongletDossier;
      ecranDossier().catch(montrerErreur);
    }),
  );

  rendreOnglet({ fiche, chronologie, pieces, echanges });
}

/** Le contenu de l'onglet actif. Séparé pour que l'ossature de l'écran reste lisible. */
function rendreOnglet({ fiche, chronologie, pieces, echanges }) {
  const zone = $("#corps-onglet");

  if (etat.ongletDossier === "chrono") {
    zone.innerHTML = chronologie.length
      ? `<p style="margin:0 0 14px;font-size:12px;color:var(--color-neutral-700)">Construite par le code à partir des dates en base — aucun modèle n'intervient.</p>
         <div style="display:flex;flex-direction:column">${chronologie.map(ligneChronologie).join("")}</div>`
      : attente("Aucune date n'est encore rattachée à ce dossier.");
    return;
  }

  if (etat.ongletDossier === "pieces") {
    zone.innerHTML = pieces.length
      ? `<div style="overflow-x:auto">
           <table class="table" style="min-width:720px">
             <thead><tr><th>N°</th><th>Pièce</th><th>Reconnu</th><th>Saisi par le cabinet</th><th>Date</th><th>Lecture</th></tr></thead>
             <tbody>${pieces.map(lignePiece).join("")}</tbody>
           </table>
         </div>
         <p style="margin:12px 0 0;font-size:12px;color:var(--color-neutral-700)">
           Une catégorie signalée « à vérifier » marque un désaccord entre la saisie du cabinet et
           la lecture de JurisMind. La saisie n'est jamais écrasée.
         </p>`
      : attente("Aucune pièce n'a encore été versée à ce dossier.");
    $$("[data-piece]").forEach((ligne) =>
      ligne.addEventListener("click", () => {
        etat.dossierPiece = fiche.reference;
        etat.piece = Number(ligne.dataset.piece);
        aller("pieces");
      }),
    );
    return;
  }

  if (etat.ongletDossier === "echanges") {
    zone.innerHTML = echanges.length
      ? `<div style="display:flex;flex-direction:column;border:1px solid var(--color-divider)">${echanges.map(ligneEchangeDossier).join("")}</div>`
      : attente("Aucun courrier n'est rattaché à ce dossier.");
    return;
  }

  if (etat.ongletDossier === "conflits") {
    zone.innerHTML = attente("Confrontation des parties adverses aux clients du cabinet…");
    verifierConflitsDuDossier(fiche.reference).catch(
      (echec) => (zone.innerHTML = encadreErreur(echec)),
    );
    return;
  }

  zone.innerHTML = formulaireAssistant(fiche);
  $("#bouton-assistant").addEventListener("click", () => interrogerDossier(fiche.reference));
  $$("[data-suggestion]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      $("#champ-assistant").value = bouton.dataset.suggestion;
      interrogerDossier(fiche.reference);
    }),
  );
}

// ------------------------------------------------------------------- morceaux de l'écran

/** Les délais de ce dossier, en tête d'écran : c'est ce qui engage une responsabilité. */
function blocDelais(points) {
  if (!points.length) return "";
  // La référence est retirée de chaque carte : elle est déjà en titre, la répéter est du bruit.
  const sansRedite = points.map((point) => ({ ...point, dossier: null }));
  return `<div style="display:flex;flex-direction:column;gap:10px">${sansRedite.map(cartePoint).join("")}</div>`;
}

function caseFiche(libelle, valeur, attributs = "", chiffre = false) {
  const contenu = attributs ? `<a href="#" ${attributs}>${texte(valeur)}</a>` : texte(valeur);
  return `<div style="padding:12px 16px;border-right:1px solid var(--color-divider)">
      <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-neutral-700)">${texte(libelle)}</div>
      <div style="margin-top:3px;font-weight:500;${chiffre ? "font-variant-numeric:tabular-nums;" : ""}">${contenu}</div>
    </div>`;
}

function carteParties(parties) {
  const corps = parties.length
    ? parties
        .map(
          (partie) => `<div>
            <div style="color:var(--color-neutral-700);font-size:11px">${texte(QUALITES[partie.qualite] || partie.qualite)}</div>
            <div style="font-weight:500">${texte(partie.nom)}</div>
            ${partie.adresse ? `<div style="color:var(--color-neutral-700)">${texte(partie.adresse)}</div>` : ""}
          </div>`,
        )
        .join("")
    : `<div style="color:var(--color-neutral-700)">Aucune partie extérieure n'est enregistrée.</div>`;
  return `<div class="blueprint" style="padding:16px 18px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:10px">Parties</div>
      <div style="display:flex;flex-direction:column;gap:12px;font-size:13px">${corps}</div>
    </div>`;
}

/** « avocat » → « Avocat ». La base stocke des codes ; l'écran parle à un humain. */
function capitale(mot) {
  return mot ? mot[0].toUpperCase() + mot.slice(1) : "";
}

/** L'isolation rendue visible : la liste vient de la table que lisent les règles RLS. */
function carteEquipe(equipe) {
  return `<div class="blueprint" style="padding:16px 18px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:10px">Équipe · accès au dossier</div>
      <div style="display:flex;flex-direction:column;gap:8px;font-size:13px">
        ${equipe
          .map(
            (membre) => `<div style="display:flex;justify-content:space-between;gap:10px">
              <span>${texte(membre.nom)}</span>
              <span style="color:var(--color-neutral-700);white-space:nowrap">${texte(membre.responsable ? "Responsable" : capitale(membre.role))}</span>
            </div>`,
          )
          .join("")}
      </div>
      <p style="margin:12px 0 0;font-size:11px;color:var(--color-neutral-700)">
        Hors de cette liste, le dossier répond 404 — pas 403. On ne révèle pas son existence.
      </p>
    </div>`;
}

function ligneChronologie(evenement) {
  const plein = evenement.type === "etape" ? "var(--color-accent)" : "transparent";
  return `<div style="display:grid;grid-template-columns:96px 22px minmax(0,1fr);gap:10px">
      <div style="font-size:13px;font-variant-numeric:tabular-nums;color:var(--color-neutral-800);padding-top:1px">${texte(dateLongue(evenement.date))}</div>
      <div style="display:flex;flex-direction:column;align-items:center">
        <span style="width:9px;height:9px;margin-top:5px;border:1.5px solid var(--color-accent);background:${plein}"></span>
        <span style="flex:1;width:1px;background:var(--color-divider)"></span>
      </div>
      <div style="padding-bottom:18px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="font-weight:500">${texte(evenement.libelle)}</span>
          <span class="tag tag-neutral" style="font-size:10px;padding:1px 7px">${texte(evenement.type)}</span>
        </div>
        ${evenement.detail ? `<div style="font-size:13px;color:var(--color-neutral-700);margin-top:2px">${texte(evenement.detail)}</div>` : ""}
      </div>
    </div>`;
}

function lignePiece(piece) {
  const desaccord = piece.categorie_detectee && piece.categorie_detectee !== piece.categorie_source;
  return `<tr data-cliquable data-piece="${piece.id}">
      <td style="font-variant-numeric:tabular-nums;color:var(--color-neutral-700)">${piece.id}</td>
      <td style="font-weight:500">${texte(piece.titre)}</td>
      <td>${piece.categorie_detectee ? `<span class="tag tag-accent">${texte(piece.categorie_detectee)}</span>` : `<span style="font-size:13px;color:var(--color-neutral-700)">non analysée</span>`}</td>
      <td style="font-size:13px;color:${desaccord ? "var(--color-accent-800)" : "var(--color-neutral-800)"}">${texte(piece.categorie_source || "—")}${desaccord ? ' <span class="tag tag-outline" style="margin-left:4px">à vérifier</span>' : ""}</td>
      <td style="font-size:13px;font-variant-numeric:tabular-nums">${texte(dateLongue(piece.date_document))}</td>
      <td style="font-size:12px;color:var(--color-neutral-700)">${piece.lu_par_ocr ? "OCR" : "texte direct"}</td>
    </tr>`;
}

/** Comme `ligneEchange`, mais sans rappeler le dossier : on y est déjà. */
function ligneEchangeDossier(echange) {
  const entrant = echange.sens === "reçu";
  return `<div style="display:grid;grid-template-columns:92px 20px minmax(0,1fr);gap:10px;padding:12px 14px;border-bottom:1px solid var(--color-divider);align-items:start">
      <span style="font-size:13px;font-variant-numeric:tabular-nums;color:var(--color-neutral-800)">${texte(dateLongue(echange.date))}</span>
      <span style="font-size:14px;color:var(--color-accent-700)" title="${entrant ? "reçu" : "envoyé"}">${entrant ? "↓" : "↑"}</span>
      <div style="min-width:0">
        <div style="font-size:14px;font-weight:500">${texte(echange.objet || "sans objet")}</div>
        <div style="font-size:12px;color:var(--color-neutral-700);margin-top:1px">${texte(echange.canal)} · ${texte(echange.interlocuteur || "—")}</div>
        ${echange.extrait ? `<div style="font-size:13px;color:var(--color-neutral-800);margin-top:5px">${texte(echange.extrait)}</div>` : ""}
      </div>
    </div>`;
}

async function verifierConflitsDuDossier(reference) {
  const zone = $("#corps-onglet");
  const conflits = await api(`/conformite/dossiers/${encodeURIComponent(reference)}`);
  if (!conflits.length) {
    zone.innerHTML = `<div class="blueprint" style="padding:18px 20px;display:flex;gap:14px;align-items:flex-start">
        <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
        <svg width="20" height="20" viewBox="0 0 24 24" style="flex:none;fill:none;stroke:var(--color-accent);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round"><path d="M20 6 9 17l-5-5"></path></svg>
        <div>
          <div style="font-weight:500">Aucune partie adverse de ce dossier ne porte le nom d'un client du cabinet.</div>
          <div style="font-size:13px;color:var(--color-neutral-700);margin-top:4px">
            Une liste vide dit ce qui a été cherché, pas que tout va bien. Le contrôle est inscrit au journal.
          </div>
        </div>
      </div>`;
    return;
  }
  zone.innerHTML = `<div style="display:flex;flex-direction:column;gap:12px">${conflits.map(carteConflit).join("")}</div>`;
}

const SUGGESTIONS = ["Résume ce dossier", "Donne-moi la chronologie", "Quel est le montant réclamé ?"];

function formulaireAssistant(fiche) {
  return `<div style="display:flex;gap:8px;align-items:stretch;flex-wrap:wrap">
      <input id="champ-assistant" class="input" style="flex:1;min-width:240px"
             placeholder="Résume ce dossier" value="${texte(etat.demandeDossier || "")}">
      <button id="bouton-assistant" class="btn btn-primary blueprint" style="white-space:nowrap;flex:none">
        <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Demander
      </button>
    </div>
    <div style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap">
      ${SUGGESTIONS.map((phrase) => `<button data-suggestion="${texte(phrase)}" class="tag tag-outline" style="background:transparent;cursor:pointer;font:inherit;font-size:12px">${texte(phrase)}</button>`).join("")}
    </div>
    <p style="margin:10px 0 0;font-size:12px;color:var(--color-neutral-700)">
      L'agent lit ${fiche.nombre_documents} pièce(s) sous vos droits. Un modèle local tourne sur le
      processeur : compter 20 à 100 secondes. Une chronologie, elle, revient instantanément.
    </p>
    <div id="reponse-assistant" style="margin-top:20px"></div>`;
}

async function interrogerDossier(reference) {
  const demande = $("#champ-assistant").value.trim() || "Résume ce dossier";
  etat.demandeDossier = demande;
  const zone = $("#reponse-assistant");
  const bouton = $("#bouton-assistant");
  bouton.disabled = true;
  zone.innerHTML = attente("L'agent lit le dossier sous vos droits…");
  try {
    const reponse = await api(`/dossiers/${encodeURIComponent(reference)}/assistant`, {
      method: "POST",
      body: JSON.stringify({ demande }),
    });
    zone.innerHTML = `<div class="blueprint" style="padding:20px 22px;display:flex;flex-direction:column;gap:12px">
        <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
        <div style="display:flex;gap:8px;align-items:center;font-size:12px;color:var(--color-neutral-700);flex-wrap:wrap">
          <span class="${reponse.abstention ? "tag tag-outline" : "tag tag-accent"}">intention : ${texte(reponse.intention)}</span>
          <span>${reponse.secondes.toFixed(0)} s · ${reponse.abstention ? "abstention" : `${reponse.citations.length} source(s) citée(s)`}</span>
        </div>
        <p style="margin:0;font-size:15px;line-height:1.6;white-space:pre-wrap;text-wrap:pretty">${texte(reponse.texte)}</p>
        ${
          reponse.citations.length
            ? `<div style="border-top:1px solid var(--color-divider);padding-top:10px;display:flex;flex-direction:column;gap:4px;font-size:13px">
                ${reponse.citations.map((citation) => `<div><span style="color:var(--color-accent-700)">[${citation.numero}]</span> ${texte(citation.reference)}</div>`).join("")}
              </div>`
            : ""
        }
      </div>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  } finally {
    bouton.disabled = false;
  }
}

// --------------------------------------------------------------------------- échéancier

const FENETRES = [7, 30, 90];

async function ecranEcheances() {
  const jours = etat.fenetreEcheances || 30;
  etat.fenetreEcheances = jours;
  patienter("Lecture des délais en cours…");
  const points = await api(`/dossiers/echeances?jours=${jours}`);
  const hautes = points.filter((point) => point.gravite === "haute").length;

  $("#ecran").innerHTML = `
    ${enTete(
      "Suivi des échéances",
      "Ce qui tombe bientôt",
      "Les dates sont reconstituées depuis les actes extraits — relus ou non : délais d'opposition, de paiement, de mise en demeure. Mieux vaut une alerte à vérifier qu'un délai manqué, car un délai ne se rate pas faute de l'avoir compris, mais faute d'avoir rouvert le dossier à temps.",
    )}

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));border:1px solid var(--color-divider)">
      ${indicateur("Échéances dans la fenêtre", points.length)}
      ${indicateur("Dont urgentes", hautes, false, hautes === 0)}
      ${indicateur("Dossiers concernés", new Set(points.map((point) => point.dossier)).size, true)}
    </div>

    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <div style="display:flex;border:1px solid var(--color-divider)">
        ${FENETRES.map((valeur) => {
          const actif = valeur === jours;
          return `<button data-fenetre="${valeur}" style="border:0;border-right:1px solid var(--color-divider);padding:6px 12px;font:inherit;font-size:13px;cursor:pointer;background:${actif ? "var(--color-accent)" : "transparent"};color:${actif ? "var(--color-bg)" : "inherit"}">${valeur} jours</button>`;
        }).join("")}
      </div>
      <span style="font-size:12px;color:var(--color-neutral-700)">Seuls vos dossiers en cours sont balayés.</span>
    </div>

    <div style="display:flex;flex-direction:column;gap:10px">
      ${
        points.length
          ? points.map(carteEcheance).join("")
          : `<div class="blueprint" style="padding:18px 20px">
              <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
              <div style="font-weight:500">Aucun délai n'échoit dans les ${jours} prochains jours.</div>
              <div style="font-size:13px;color:var(--color-neutral-700);margin-top:4px">
                Cela veut dire qu'aucune date n'a été trouvée, pas qu'il n'y en a aucune : un délai
                absent des pièces lues est un délai que JurisMind ne connaît pas.
              </div>
            </div>`
      }
    </div>`;

  $$("[data-fenetre]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      etat.fenetreEcheances = Number(bouton.dataset.fenetre);
      ecranEcheances().catch(montrerErreur);
    }),
  );
  $$("[data-ouvrir]").forEach((bouton) =>
    bouton.addEventListener("click", () => ouvrirDossier(bouton.dataset.ouvrir)),
  );
}

/** Comme `cartePoint`, mais la référence du dossier devient un bouton : on va y travailler. */
function carteEcheance(point) {
  const style = GRAVITES[point.gravite] || GRAVITES.moyenne;
  return `<div class="blueprint" style="padding:14px 16px;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:start">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <span style="width:8px;height:8px;margin-top:7px;background:${style.fond};border:1.5px solid var(--color-accent-800)"></span>
      <div>
        <div style="font-weight:500">${texte(point.libelle)}</div>
        <div style="font-size:13px;color:var(--color-neutral-700);margin-top:2px">${texte(point.detail)}</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">
        <span class="${style.etiquette}">${texte(point.gravite)}</span>
        ${point.dossier ? `<button data-ouvrir="${texte(point.dossier)}" class="btn btn-ghost" style="font-family:var(--font-heading);font-weight:600;font-size:12px;color:var(--color-accent-700);padding:2px 6px">${texte(point.dossier)}</button>` : ""}
      </div>
    </div>`;
}
