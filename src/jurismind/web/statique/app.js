"use strict";

/**
 * Interface de JurisMind.
 *
 * Elle ne parle qu'à l'API, avec le jeton de l'utilisateur connecté — jamais à la base.
 * C'est ce qui rend l'isolation démontrable : deux avocats ouvrent la même page et voient
 * des listes différentes, parce que c'est PostgreSQL qui tranche, pas ce fichier.
 *
 * Volontairement sans cadriciel ni étape de compilation : le projet reste un projet Python,
 * et l'interface tient dans trois fichiers qu'on peut lire d'un bout à l'autre.
 */

const CLE_JETON = "jurismind.jeton";
const CLE_COMPTE = "jurismind.compte";

const etat = {
  jeton: sessionStorage.getItem(CLE_JETON),
  compte: JSON.parse(sessionStorage.getItem(CLE_COMPTE) || "null"),
  dossiers: [],
  ecran: "dossiers",
  filtre: "Tous",
};

// --------------------------------------------------------------------------- outils

const $ = (selecteur) => document.querySelector(selecteur);
const $$ = (selecteur) => Array.from(document.querySelectorAll(selecteur));

/** Échappe le texte : les intitulés viennent de la base, jamais de la confiance. */
function texte(valeur) {
  return String(valeur ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

/** 13750000 → « 13 750 000 », comme l'écrit un acte. */
function montant(valeur) {
  if (valeur === null || valeur === undefined) return "—";
  return Number(valeur).toLocaleString("fr-FR").replace(/ | /g, " ");
}

class ApiErreur extends Error {
  constructor(code, detail) {
    super(detail);
    this.code = code;
    this.detail = detail;
  }
}

/** Appel à l'API. Un 401 renvoie à l'écran de connexion : le jeton a expiré. */
async function api(chemin, options = {}) {
  const entetes = { "Content-Type": "application/json" };
  if (etat.jeton) entetes.Authorization = `Bearer ${etat.jeton}`;

  const reponse = await fetch(chemin, { ...options, headers: { ...entetes, ...options.headers } });
  if (reponse.status === 401 && etat.jeton) {
    deconnecter();
    throw new ApiErreur(401, "Session expirée, reconnectez-vous.");
  }
  if (!reponse.ok) {
    let detail = `Erreur ${reponse.status}`;
    try {
      detail = (await reponse.json()).detail ?? detail;
    } catch {
      /* une réponse sans JSON ne doit pas masquer le code */
    }
    throw new ApiErreur(reponse.status, detail);
  }
  return reponse.status === 204 ? null : reponse.json();
}

// --------------------------------------------------------------------------- session

async function connecter(email, motDePasse) {
  const reponse = await api("/connexion", {
    method: "POST",
    body: JSON.stringify({ email, mot_de_passe: motDePasse }),
  });
  etat.jeton = reponse.jeton;
  etat.compte = reponse.utilisateur;
  sessionStorage.setItem(CLE_JETON, etat.jeton);
  sessionStorage.setItem(CLE_COMPTE, JSON.stringify(etat.compte));
}

function deconnecter() {
  etat.jeton = null;
  etat.compte = null;
  sessionStorage.removeItem(CLE_JETON);
  sessionStorage.removeItem(CLE_COMPTE);
  $("#application").hidden = true;
  $("#connexion").hidden = false;
  $("#champ-mot-de-passe").value = "";
}

function initiales(nomComplet) {
  return (nomComplet || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(-2)
    .map((mot) => mot[0])
    .join("")
    .toUpperCase();
}

// --------------------------------------------------------------------------- écrans

const ECRANS = {
  dossiers: { titre: "Dossiers", rendre: ecranDossiers },
  clients: { titre: "Clients", rendre: aVenir("Clients") },
  questions: { titre: "Questions", rendre: aVenir("Questions") },
  pieces: { titre: "Pièces", rendre: aVenir("Pièces") },
  courrier: { titre: "Courrier", rendre: aVenir("Courrier") },
  conflits: { titre: "Conflits d'intérêts", rendre: aVenir("Conflits d'intérêts") },
};

/** Placeholder honnête : l'écran existe dans le menu, pas encore dans le code. */
function aVenir(nom) {
  return () => {
    $("#ecran").innerHTML = `
      <div>
        <div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:4px">En construction</div>
        <h1 style="font-size:34px;margin:0">${texte(nom)}</h1>
        <p style="margin:10px 0 0;font-size:14px;color:var(--color-neutral-700);max-width:60ch">
          Cet écran n'est pas encore câblé sur l'API. La fonctionnalité existe et se pilote
          en ligne de commande ; seule l'interface reste à construire.
        </p>
      </div>`;
  };
}

function patienter(message) {
  $("#ecran").innerHTML =
    `<p style="font-size:14px;color:var(--color-neutral-700)">${texte(message)}</p>`;
}

function montrerErreur(erreur) {
  $("#ecran").innerHTML = `
    <div class="card" style="padding:18px;border-color:var(--color-accent-300);background:var(--color-accent-100)">
      <div style="font-family:var(--font-heading);font-weight:600;font-size:17px;margin-bottom:4px">Impossible d'afficher cet écran</div>
      <div style="font-size:13px;color:var(--color-accent-900)">${texte(erreur.detail || erreur.message)}</div>
    </div>`;
}

const MATIERES = {
  RECOUV: "Recouvrement",
  COMM: "Commercial",
  BAIL: "Bail",
  CONTRAT: "Contrat",
  SOC: "Société",
};

async function ecranDossiers() {
  patienter("Chargement de vos dossiers…");
  etat.dossiers = await api("/dossiers");

  const enCours = etat.dossiers.filter((d) => d.statut === "en_cours");
  const enjeu = enCours.reduce((total, d) => total + (d.enjeu_fcfa || 0), 0);
  let decisions = 0;
  try {
    decisions = (await api("/propositions")).length;
  } catch {
    /* la file de décisions n'est pas essentielle à cet écran */
  }

  const familles = ["Tous", ...new Set(enCours.map((d) => MATIERES[d.matiere] || d.matiere))];
  const visibles =
    etat.filtre === "Tous"
      ? enCours
      : enCours.filter((d) => (MATIERES[d.matiere] || d.matiere) === etat.filtre);

  $("#compte-dossiers").textContent = etat.dossiers.length;
  const badge = $("#compte-decisions");
  badge.hidden = decisions === 0;
  badge.textContent = decisions;
  $("#texte-perimetre").textContent = `Périmètre : ${etat.dossiers.length} dossiers`;

  $("#ecran").innerHTML = `
    <div style="display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap">
      <div style="flex:1;min-width:260px">
        <div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:4px">Portefeuille</div>
        <h1 style="font-size:34px;margin:0">Mes dossiers</h1>
        <p style="margin:6px 0 0;font-size:13px;color:var(--color-neutral-700)">
          Liste produite par PostgreSQL sous votre identité : elle ne contient que les dossiers ouverts à votre compte.
        </p>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));border:1px solid var(--color-divider)">
      ${indicateur("Dossiers visibles", etat.dossiers.length)}
      ${indicateur("En cours", enCours.length)}
      ${indicateur("Enjeu en cours (FCFA)", montant(enjeu))}
      ${indicateur("Décisions en attente", decisions, true, false)}
    </div>

    <div style="display:flex;flex-direction:column;border:1px solid var(--color-divider)">
      <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;border-bottom:1px solid var(--color-divider);flex-wrap:wrap">
        <div style="display:flex;border:1px solid var(--color-divider)">
          ${familles
            .map((nom) => {
              const actif = nom === etat.filtre;
              return `<button data-filtre="${texte(nom)}" style="border:0;border-right:1px solid var(--color-divider);padding:6px 12px;font:inherit;font-size:13px;cursor:pointer;background:${actif ? "var(--color-accent)" : "transparent"};color:${actif ? "var(--color-bg)" : "inherit"}">${texte(nom)}</button>`;
            })
            .join("")}
        </div>
        <div style="flex:1"></div>
        <span style="font-size:12px;color:var(--color-neutral-700)">${visibles.length} dossier(s) · statut en cours</span>
      </div>
      <div style="overflow-x:auto">
        <table class="table" style="min-width:860px">
          <thead><tr><th style="padding-left:14px">Référence</th><th>Intitulé</th><th>Matière</th><th>Juridiction</th><th style="text-align:right">Enjeu (FCFA)</th><th>Statut</th></tr></thead>
          <tbody>
            ${visibles.map(ligneDossier).join("") || `<tr><td colspan="6" style="padding:18px;color:var(--color-neutral-700)">Aucun dossier dans cette matière.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>`;

  $$("[data-filtre]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      etat.filtre = bouton.dataset.filtre;
      ecranDossiers().catch(montrerErreur);
    }),
  );
}

function indicateur(libelle, valeur, dernier = false, neutre = true) {
  const bordure = dernier ? "" : "border-right:1px solid var(--color-divider);";
  const couleur = neutre ? "" : "color:var(--color-accent-700);";
  return `<div style="padding:16px 18px;${bordure}">
      <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-neutral-700)">${texte(libelle)}</div>
      <div style="font-family:var(--font-heading);font-weight:600;font-size:30px;line-height:1.1;margin-top:4px;${couleur}">${texte(valeur)}</div>
    </div>`;
}

function ligneDossier(dossier) {
  return `<tr data-cliquable data-reference="${texte(dossier.reference)}">
      <td style="padding-left:14px;font-family:var(--font-heading);font-weight:600;font-size:15px;white-space:nowrap;color:var(--color-accent-700)">${texte(dossier.reference)}</td>
      <td style="max-width:420px">${texte(dossier.intitule)}</td>
      <td><span class="tag tag-neutral">${texte(MATIERES[dossier.matiere] || dossier.matiere)}</span></td>
      <td style="font-size:13px;color:var(--color-neutral-800)">${texte(dossier.juridiction || "—")}</td>
      <td style="text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap">${texte(montant(dossier.enjeu_fcfa))}</td>
      <td><span class="tag tag-accent">En cours</span></td>
    </tr>`;
}

// --------------------------------------------------------------------------- routage

function aller(nom) {
  etat.ecran = nom;
  $$("[data-ecran]").forEach((bouton) =>
    bouton.classList.toggle("menu-actif", bouton.dataset.ecran === nom),
  );
  $("#fil-ariane").textContent = ECRANS[nom].titre;
  Promise.resolve(ECRANS[nom].rendre()).catch(montrerErreur);
}

async function montrerApplication() {
  $("#connexion").hidden = true;
  $("#application").hidden = false;
  $("#nom-utilisateur").textContent = etat.compte.nom_complet;
  $("#role-utilisateur").textContent = etat.compte.role;
  $("#initiales").textContent = initiales(etat.compte.nom_complet);
  aller(etat.ecran);
  sante();
}

/** Les deux voyants du bas du menu : ce qui répond, et ce qui ne répond pas. */
async function sante() {
  try {
    const etatService = await api("/sante");
    $("#voyant-base").style.background = etatService.base ? "var(--color-accent)" : "var(--color-neutral-500)";
    $("#etat-base").textContent = `Base PostgreSQL · ${etatService.base ? "répond" : "injoignable"}`;
    $("#voyant-modeles").style.background = "var(--color-accent)";
    $("#etat-modeles").textContent = `Modèles · ${etatService.modeles}`;
  } catch {
    $("#etat-base").textContent = "Base PostgreSQL · inconnue";
  }
}

// --------------------------------------------------------------------------- démarrage

$("#formulaire-connexion").addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  const erreur = $("#erreur-connexion");
  const bouton = $("#bouton-connexion");
  erreur.hidden = true;
  bouton.disabled = true;
  bouton.textContent = "Connexion…";
  try {
    await connecter($("#champ-email").value.trim(), $("#champ-mot-de-passe").value);
    await montrerApplication();
  } catch (echec) {
    erreur.textContent = echec.detail || "Le service ne répond pas.";
    erreur.hidden = false;
  } finally {
    bouton.disabled = false;
    bouton.textContent = "Se connecter";
  }
});

$("#bouton-deconnexion").addEventListener("click", deconnecter);
$$("[data-ecran]").forEach((bouton) =>
  bouton.addEventListener("click", () => aller(bouton.dataset.ecran)),
);

// Un jeton encore valide en session évite de redemander le mot de passe à chaque rechargement.
if (etat.jeton && etat.compte) {
  montrerApplication();
}
