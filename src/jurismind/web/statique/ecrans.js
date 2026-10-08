"use strict";

/**
 * Les écrans de JurisMind, un par usage.
 *
 * Chacun lit l'API et rend du HTML ; le socle (`app.js`) porte l'authentification, le
 * routage et les aides communes. Rien ici ne décide de ce que l'utilisateur a le droit
 * de voir : c'est PostgreSQL qui l'a déjà tranché avant que la réponse arrive.
 */

// --------------------------------------------------------------------------- clients

const GRAVITES = {
  haute: { fond: "var(--color-accent)", etiquette: "tag tag-accent" },
  moyenne: { fond: "var(--color-accent-300)", etiquette: "tag tag-outline" },
};

async function ecranClients() {
  const nom = etat.clientRecherche;
  $("#ecran").innerHTML = `
    ${enTete("Intelligence client", "Un client", "Identité, dossiers, échanges, et ce qui mérite votre attention.")}
    <div class="blueprint" style="padding:18px;display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <label style="flex:1;min-width:260px">
        <span style="display:block;font-size:12px;color:var(--color-neutral-700);margin-bottom:5px">Nom du client</span>
        <input id="champ-client" class="input" style="width:100%;box-sizing:border-box" value="${texte(nom)}" placeholder="Sine Services SA">
      </label>
      <button id="bouton-client" class="btn btn-primary blueprint" style="flex:none">
        <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Ouvrir la fiche
      </button>
    </div>
    <div id="fiche-client"></div>`;

  const lancer = () => {
    etat.clientRecherche = $("#champ-client").value.trim();
    chargerClient().catch((e) => ($("#fiche-client").innerHTML = encadreErreur(e)));
  };
  $("#bouton-client").addEventListener("click", lancer);
  $("#champ-client").addEventListener("keydown", (e) => e.key === "Enter" && lancer());
  if (nom) await chargerClient();
}

async function chargerClient() {
  const zone = $("#fiche-client");
  zone.innerHTML = attente("Recherche du client…");

  const fiche = await api(`/clients/recherche?nom=${encodeURIComponent(etat.clientRecherche)}`);
  const identifiant = fiche.client_id;
  const [attention, dossiers, echanges] = await Promise.all([
    api(`/clients/${identifiant}/attention`),
    api(`/clients/${identifiant}/dossiers`),
    api(`/clients/${identifiant}/echanges`),
  ]);
  etat.clientCourant = identifiant;
  $("#fil-ariane").textContent = `Clients · ${fiche.nom}`;

  const contacts = (fiche.contacts || [])
    .map((c) => [c.nom, c.fonction].filter(Boolean).join(", "))
    .join(" · ");

  zone.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:24px">
      <div style="display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap">
        <div style="flex:1;min-width:260px">
          <div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:4px">
            Client · ${texte(fiche.type === "societe" ? "personne morale" : "particulier")}${fiche.ville ? " · " + texte(fiche.ville) : ""}
          </div>
          <h2 style="font-family:var(--font-heading);font-size:30px;margin:0">${texte(fiche.nom)}</h2>
          ${contacts ? `<p style="margin:6px 0 0;font-size:13px;color:var(--color-neutral-700)">${texte(contacts)}</p>` : ""}
        </div>
        <button id="bouton-synthese" class="btn btn-primary blueprint" style="white-space:nowrap;flex:none">
          <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Faire le point
        </button>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));border:1px solid var(--color-divider)">
        ${indicateur("Dossiers visibles", fiche.dossiers_visibles)}
        ${indicateur("En cours", fiche.dossiers_en_cours)}
        ${indicateur("Enjeu cumulé (FCFA)", montant(fiche.enjeu_total_fcfa))}
        ${indicateur("Points d'attention", attention.length, true, false)}
      </div>
      <p style="margin:-12px 0 0;font-size:12px;color:var(--color-neutral-700)">
        « Visibles » : la fiche ne compte que les dossiers ouverts à votre compte.
      </p>

      <div id="zone-synthese"></div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:24px;align-items:start">
        <section style="display:flex;flex-direction:column;gap:12px">
          <h3 style="font-size:20px;margin:0">Points d'attention</h3>
          <p style="margin:0;font-size:12px;color:var(--color-neutral-700)">
            Déduits des données par des règles, jamais demandés à un modèle. Chacun remonte à la
            date, au montant ou au statut qui l'a déclenché.
          </p>
          ${attention.map(cartePoint).join("") || `<p style="margin:0;font-size:14px">Rien à signaler. Une liste vide est une information.</p>`}

          <h3 style="font-size:20px;margin:14px 0 0">Dossiers</h3>
          <div style="border-top:1px solid var(--color-divider)">
            ${dossiers.map(ligneDossierClient).join("")}
          </div>
        </section>

        <section style="display:flex;flex-direction:column;gap:12px">
          <h3 style="font-size:20px;margin:0">Derniers échanges</h3>
          <div style="border-top:1px solid var(--color-divider)">
            ${echanges.map(ligneEchange).join("") || `<p style="font-size:14px">Aucun échange enregistré.</p>`}
          </div>
        </section>
      </div>
    </div>`;

  $("#bouton-synthese").addEventListener("click", () => faireLePoint(identifiant));
}

function cartePoint(point) {
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
        ${point.dossier ? `<span style="font-size:12px;font-family:var(--font-heading);font-weight:600;color:var(--color-accent-700)">${texte(point.dossier)}</span>` : ""}
      </div>
    </div>`;
}

function ligneDossierClient(dossier) {
  return `<div style="display:grid;grid-template-columns:96px minmax(0,1fr) auto;gap:12px;padding:10px 4px;border-bottom:1px solid var(--color-divider);align-items:center">
      <span style="font-family:var(--font-heading);font-weight:600;color:var(--color-accent-700)">${texte(dossier.reference)}</span>
      <span style="font-size:14px">${texte(dossier.intitule)}</span>
      <span style="font-size:13px;font-variant-numeric:tabular-nums;color:var(--color-neutral-800)">${texte(montant(dossier.enjeu_fcfa))}</span>
    </div>`;
}

function ligneEchange(echange) {
  const entrant = echange.sens === "reçu";
  return `<div style="display:grid;grid-template-columns:88px 20px minmax(0,1fr);gap:10px;padding:10px 4px;border-bottom:1px solid var(--color-divider);align-items:start">
      <span style="font-size:13px;font-variant-numeric:tabular-nums;color:var(--color-neutral-800)">${texte(dateCourte(echange.date))}</span>
      <span style="font-size:14px;color:var(--color-accent-700)" title="${entrant ? "reçu" : "envoyé"}">${entrant ? "↓" : "↑"}</span>
      <div>
        <div style="font-size:14px;font-weight:500">${texte(echange.objet || "sans objet")}</div>
        <div style="font-size:12px;color:var(--color-neutral-700)">${texte(echange.dossier)} · ${texte(echange.interlocuteur || "—")}</div>
      </div>
    </div>`;
}

async function faireLePoint(identifiant) {
  const zone = $("#zone-synthese");
  zone.innerHTML = `<div class="blueprint" style="padding:18px 20px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--color-neutral-700)">
        <span class="tag tag-accent">Synthèse</span><span>L'agent rédige… le modèle tourne sur le processeur, comptez 20 à 60 secondes.</span>
      </div>
    </div>`;
  try {
    const reponse = await api(`/clients/${identifiant}/assistant`, {
      method: "POST",
      body: JSON.stringify({ demande: "fais le point" }),
    });
    const corps = reponse.abstention
      ? `<p style="margin:0;font-size:14px;line-height:1.6">${texte(reponse.texte)}</p>
         <p style="margin:0;font-size:12px;color:var(--color-neutral-700)">L'abstention est un résultat : les données ne permettaient pas de conclure sans risque.</p>`
      : `<p style="margin:0;font-size:14px;line-height:1.6;white-space:pre-wrap">${texte(reponse.texte)}</p>`;
    zone.innerHTML = `<div class="blueprint" style="padding:18px 20px;display:flex;flex-direction:column;gap:10px">
        <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
        <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--color-neutral-700)">
          <span class="${reponse.abstention ? "tag tag-outline" : "tag tag-accent"}">${reponse.abstention ? "Abstention" : "Synthèse"}</span>
          <span>${reponse.secondes.toFixed(0)} s · intention « ${texte(reponse.intention)} »</span>
        </div>
        ${corps}
      </div>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}

// --------------------------------------------------------------------------- questions

const EXEMPLES = [
  "Quel délai le débiteur a-t-il pour former opposition ?",
  "Quel est le montant total réclamé au débiteur ?",
  "Y a-t-il une convention d'honoraires avec ce client ?",
];

async function ecranQuestions() {
  const dossiers = etat.dossiers.length ? etat.dossiers : await api("/dossiers");
  etat.dossiers = dossiers;

  $("#ecran").innerHTML = `
    ${enTete("Réponses citées", "Une question sur les pièces", "La réponse ne vient que des pièces, avec ses sources — ou bien l'agent s'abstient. La recherche est bornée à vos dossiers par PostgreSQL, avant même d'avoir lieu.")}
    <div class="blueprint" style="padding:18px;display:flex;flex-direction:column;gap:12px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <textarea id="champ-question" class="input" style="min-height:64px;font-size:16px;width:100%;box-sizing:border-box">${texte(etat.question || EXEMPLES[0])}</textarea>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <span style="font-size:12px;color:var(--color-neutral-700)">Restreindre à</span>
        <select id="champ-dossier" class="input" style="width:auto;min-width:260px;max-width:420px">
          <option value="">Tous mes dossiers (${dossiers.length})</option>
          ${dossiers.map((d) => `<option value="${d.id}">${texte(d.reference)} — ${texte(d.intitule.slice(0, 54))}</option>`).join("")}
        </select>
        <div style="flex:1"></div>
        <button id="bouton-chercher" class="btn btn-secondary" style="flex:none">Chercher seulement</button>
        <button id="bouton-repondre" class="btn btn-primary blueprint" style="flex:none">
          <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Répondre
        </button>
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <span style="font-size:12px;color:var(--color-neutral-700)">Exemples :</span>
        ${EXEMPLES.map((q) => `<button data-exemple="${texte(q)}" class="tag tag-outline" style="background:transparent;cursor:pointer;font:inherit;font-size:12px">${texte(q.slice(0, 44))}…</button>`).join("")}
      </div>
    </div>
    <div id="resultat-question"></div>`;

  $$("[data-exemple]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      $("#champ-question").value = bouton.dataset.exemple;
    }),
  );
  $("#bouton-repondre").addEventListener("click", repondreQuestion);
  $("#bouton-chercher").addEventListener("click", chercherSeulement);
}

function filtresChoisis() {
  const dossier = $("#champ-dossier").value;
  return dossier ? { dossier_id: Number(dossier) } : {};
}

async function chercherSeulement() {
  const zone = $("#resultat-question");
  const question = $("#champ-question").value.trim();
  zone.innerHTML = attente("Recherche hybride…");
  try {
    const resultats = await api("/recherche", {
      method: "POST",
      body: JSON.stringify({ texte: question, filtres: filtresChoisis(), limite: 6 }),
    });
    zone.innerHTML = resultats.length
      ? `<div style="display:flex;flex-direction:column;border:1px solid var(--color-divider)">
          <div style="padding:10px 14px;border-bottom:1px solid var(--color-divider);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-neutral-700)">
            ${resultats.length} extrait(s) — la recherche seule, sans modèle
          </div>
          ${resultats.map(ligneExtrait).join("")}
        </div>`
      : `<p style="font-size:14px">Aucun extrait ne correspond, dans les dossiers qui vous sont ouverts.</p>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}

function ligneExtrait(resultat) {
  return `<div style="padding:12px 14px;border-bottom:1px solid var(--color-divider)">
      <div style="display:flex;gap:10px;align-items:baseline;justify-content:space-between">
        <span style="font-weight:500">${texte(resultat.reference)}</span>
        <span class="tag tag-neutral">${texte(resultat.trouve_par)}</span>
      </div>
      <div style="font-size:13px;color:var(--color-neutral-800);margin-top:6px;line-height:1.5">${texte(resultat.contenu.slice(0, 340))}${resultat.contenu.length > 340 ? "…" : ""}</div>
    </div>`;
}

async function repondreQuestion() {
  const zone = $("#resultat-question");
  etat.question = $("#champ-question").value.trim();
  zone.innerHTML = attente("Recherche hybride, puis rédaction et vérification… 20 à 60 secondes sur processeur.");
  try {
    const reponse = await api("/questions", {
      method: "POST",
      body: JSON.stringify({ question: etat.question, filtres: filtresChoisis() }),
    });
    zone.innerHTML = `
      <div style="display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:24px;align-items:start">
        ${reponse.abstention ? blocAbstention(reponse) : blocReponse(reponse)}
        ${blocControles(reponse)}
      </div>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}

function blocReponse(reponse) {
  return `<div style="display:flex;flex-direction:column;gap:16px;min-width:0">
      <div class="blueprint" style="padding:22px 24px;display:flex;flex-direction:column;gap:12px">
        <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
        <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--color-neutral-700)">
          <span class="tag tag-accent">Réponse vérifiée</span>
          <span>${reponse.sources_examinees} extrait(s) examiné(s) · ${reponse.secondes.toFixed(0)} s</span>
        </div>
        <p style="margin:0;font-size:18px;line-height:1.55;text-wrap:pretty">${texte(reponse.texte)}</p>
      </div>
      ${
        reponse.citations.length
          ? `<div style="display:flex;flex-direction:column;border:1px solid var(--color-divider)">
              <div style="padding:10px 14px;border-bottom:1px solid var(--color-divider);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-neutral-700)">Sources citées</div>
              ${reponse.citations.map(ligneCitation).join("")}
            </div>`
          : ""
      }
    </div>`;
}

function ligneCitation(citation) {
  return `<div style="padding:12px 14px;border-bottom:1px solid var(--color-divider);display:grid;grid-template-columns:28px minmax(0,1fr) auto;gap:10px;align-items:start">
      <span style="color:var(--color-accent-700);font-weight:500">[${citation.numero}]</span>
      <div style="font-weight:500">${texte(citation.reference)}</div>
      ${citation.similarite !== null && citation.similarite !== undefined ? `<span class="tag tag-neutral">proximité ${(citation.similarite * 100).toFixed(0)} %</span>` : ""}
    </div>`;
}

function blocAbstention(reponse) {
  return `<div class="blueprint" style="padding:22px 24px;display:flex;flex-direction:column;gap:10px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--color-neutral-700)">
        <span class="tag tag-outline">Abstention</span>
        <span>${reponse.sources_examinees} extrait(s) examiné(s) · ${reponse.secondes.toFixed(0)} s</span>
      </div>
      <p style="margin:0;font-size:18px;line-height:1.55">${texte(reponse.texte)}</p>
      <p style="margin:0;font-size:13px;color:var(--color-neutral-700)">
        L'abstention est un résultat. Une réponse inventée coûterait plus cher que pas de réponse.
      </p>
    </div>`;
}

function blocControles(reponse) {
  if (!reponse.controles.length) {
    return `<div class="blueprint" style="padding:16px 18px">
        <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
        <div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:10px">Contrôles avant affichage</div>
        <p style="margin:0;font-size:13px;color:var(--color-neutral-700)">
          Aucun contrôle n'a eu à s'exercer : aucun extrait n'a été trouvé dans vos dossiers.
        </p>
      </div>`;
  }
  const coche = `<svg width="16" height="16" viewBox="0 0 24 24" style="fill:none;stroke:var(--color-accent);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;margin-top:2px"><path d="M20 6 9 17l-5-5"></path></svg>`;
  const croix = `<svg width="16" height="16" viewBox="0 0 24 24" style="fill:none;stroke:var(--color-neutral-800);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;margin-top:2px"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>`;
  return `<div class="blueprint" style="padding:16px 18px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:12px">Contrôles avant affichage</div>
      ${reponse.controles
        .map(
          (c) => `<div style="display:grid;grid-template-columns:20px minmax(0,1fr);gap:8px;padding:7px 0;border-bottom:1px solid var(--color-divider);font-size:13px;color:${c.reussi ? "inherit" : "var(--color-neutral-700)"}">
            ${c.reussi ? coche : croix}<span>${texte(c.libelle)}</span>
          </div>`,
        )
        .join("")}
      <p style="margin:10px 0 0;font-size:11px;color:var(--color-neutral-700)">
        Un seul contrôle en échec suffit pour que JurisMind s'abstienne.
      </p>
    </div>`;
}

// --------------------------------------------------------------------------- pièces

async function ecranPieces() {
  const dossiers = etat.dossiers.length ? etat.dossiers : await api("/dossiers");
  etat.dossiers = dossiers;
  if (!dossiers.length) {
    $("#ecran").innerHTML = enTete("Pièces", "Une pièce", "Aucun dossier n'est ouvert à votre compte.");
    return;
  }
  const reference = etat.dossierPiece || dossiers[0].reference;
  etat.dossierPiece = reference;
  const pieces = await api(`/dossiers/${encodeURIComponent(reference)}/documents`);

  $("#ecran").innerHTML = `
    ${enTete("Traitement documentaire", "Une pièce", "Le type reconnu appartient à une liste fermée de 28 catégories ; chaque point relevé est accompagné de la phrase du document qui le porte.")}
    <div class="blueprint" style="padding:18px;display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <label style="flex:1;min-width:240px">
        <span style="display:block;font-size:12px;color:var(--color-neutral-700);margin-bottom:5px">Dossier</span>
        <select id="choix-dossier-piece" class="input" style="width:100%;box-sizing:border-box">
          ${dossiers.map((d) => `<option value="${texte(d.reference)}"${d.reference === reference ? " selected" : ""}>${texte(d.reference)} — ${texte(d.intitule.slice(0, 48))}</option>`).join("")}
        </select>
      </label>
      <label style="flex:2;min-width:260px">
        <span style="display:block;font-size:12px;color:var(--color-neutral-700);margin-bottom:5px">Pièce</span>
        <select id="choix-piece" class="input" style="width:100%;box-sizing:border-box">
          ${pieces.map((p) => `<option value="${p.id}">${p.id} · ${texte(p.titre)}</option>`).join("") || "<option value=''>aucune pièce lue</option>"}
        </select>
      </label>
    </div>
    <div id="fiche-piece"></div>`;

  $("#choix-dossier-piece").addEventListener("change", (e) => {
    etat.dossierPiece = e.target.value;
    etat.piece = null;
    ecranPieces().catch(montrerErreur);
  });
  $("#choix-piece").addEventListener("change", (e) => {
    etat.piece = Number(e.target.value);
    chargerPiece().catch((echec) => ($("#fiche-piece").innerHTML = encadreErreur(echec)));
  });

  if (pieces.length) {
    etat.piece = pieces.some((p) => p.id === etat.piece) ? etat.piece : pieces[0].id;
    $("#choix-piece").value = String(etat.piece);
    await chargerPiece();
  }
}

async function chargerPiece() {
  const zone = $("#fiche-piece");
  zone.innerHTML = attente("Chargement de la pièce…");
  const identifiant = etat.piece;

  const [fiche, lecture] = await Promise.all([
    api(`/documents/${identifiant}`),
    api(`/documents/${identifiant}/texte`),
  ]);
  let extraction = null;
  try {
    extraction = await api(`/documents/${identifiant}/extraction`);
  } catch {
    /* une pièce sans extraction reste consultable */
  }
  $("#fil-ariane").textContent = `Pièces · ${fiche.titre}`;

  zone.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:24px">
      <div style="display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap">
        <div style="flex:1;min-width:260px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:13px">
            <span style="font-family:var(--font-heading);font-weight:600;font-size:15px;color:var(--color-accent-700)">${texte(fiche.dossier)}</span>
            <span style="color:var(--color-neutral-600)">/</span><span style="color:var(--color-neutral-700)">Pièce ${fiche.id}</span>
          </div>
          <h2 style="font-family:var(--font-heading);font-size:28px;margin:0">${texte(fiche.titre)}</h2>
          <p style="margin:6px 0 0;font-size:13px;color:var(--color-neutral-700)">
            ${texte(dateLongue(fiche.date_document))} · ${texte((fiche.format || "").toUpperCase())} · ${lecture.caracteres.toLocaleString("fr-FR")} caractères
          </p>
        </div>
        <button id="bouton-analyse" class="btn btn-primary blueprint" style="white-space:nowrap;flex:none">
          <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Analyser la pièce
        </button>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));border:1px solid var(--color-divider)">
        ${etiquette("Saisi par le cabinet", fiche.categorie_source || "—")}
        ${etiquette("Reconnu par JurisMind", fiche.categorie_detectee || "non analysé", fiche.categorie_detectee && fiche.categorie_detectee !== fiche.categorie_source)}
        ${etiquette("Lecture", fiche.lu_par_ocr ? "OCR · français" : "texte direct")}
        ${etiquette("Extraction", extraction ? (extraction.relue ? "relue et validée" : "proposée · non relue") : "aucune", false, true)}
      </div>

      <div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px;align-items:start">
        <div style="display:flex;flex-direction:column;gap:12px;min-width:0">
          <div style="display:flex;gap:4px;border-bottom:1px solid var(--color-divider)">
            <button data-onglet="extraction" style="border:0;background:transparent;font:inherit;font-size:14px;padding:9px 12px;cursor:pointer;margin-bottom:-1px;border-bottom:2px solid var(--color-accent)">Valeurs extraites</button>
            <button data-onglet="analyse" style="border:0;background:transparent;font:inherit;font-size:14px;padding:9px 12px;cursor:pointer;margin-bottom:-1px;border-bottom:2px solid transparent;color:var(--color-neutral-700)">Analyse</button>
          </div>
          <div id="onglet-extraction">${blocExtraction(extraction)}</div>
          <div id="onglet-analyse" hidden>
            <p style="margin:0;font-size:13px;color:var(--color-neutral-700)">
              L'agent reconnaît le type de l'acte, le résume, et relève ce qui engage. Compter 30 à 90 secondes.
            </p>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:8px;min-width:0">
          <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--color-neutral-700)">
            <span>Texte lu${lecture.lu_par_ocr ? " · par OCR" : ""}</span>
            <span>${lecture.caracteres.toLocaleString("fr-FR")} caractères</span>
          </div>
          <div class="blueprint" style="padding:22px 26px;font-family:Georgia,serif;font-size:13px;line-height:1.7;color:var(--color-neutral-900);max-height:460px;overflow:auto;white-space:pre-wrap">
            <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>${texte(lecture.texte || "Cette pièce n'a pas encore été lue.")}
          </div>
        </div>
      </div>
    </div>`;

  $$("[data-onglet]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      const cible = bouton.dataset.onglet;
      $$("[data-onglet]").forEach((autre) => {
        const actif = autre.dataset.onglet === cible;
        autre.style.borderBottomColor = actif ? "var(--color-accent)" : "transparent";
        autre.style.color = actif ? "var(--color-text)" : "var(--color-neutral-700)";
      });
      $("#onglet-extraction").hidden = cible !== "extraction";
      $("#onglet-analyse").hidden = cible !== "analyse";
    }),
  );
  $("#bouton-analyse").addEventListener("click", () => analyserPiece(identifiant));
  const validation = $("#bouton-valider-extraction");
  if (validation) validation.addEventListener("click", () => validerExtraction(identifiant));
}

function etiquette(libelle, valeur, alerte = false, accent = false) {
  return `<div style="padding:12px 16px;border-right:1px solid var(--color-divider)">
      <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-neutral-700)">${texte(libelle)}</div>
      <div style="margin-top:3px;font-weight:500;${accent ? "color:var(--color-accent-700);" : ""}">${texte(valeur)}${alerte ? ' <span class="tag tag-outline" style="margin-left:6px">à vérifier</span>' : ""}</div>
    </div>`;
}

function blocExtraction(extraction) {
  if (!extraction) {
    return `<p style="margin:0;font-size:14px;color:var(--color-neutral-700)">
        Aucune valeur n'a encore été extraite de cette pièce.
        Lancer <code>python -m jurismind.extraction</code> pour en proposer.
      </p>`;
  }
  const champs = Object.entries(extraction.donnees);
  const douteux = new Set(extraction.champs_douteux);
  return `
    <div style="font-size:12px;color:var(--color-neutral-700)">
      Schéma <strong style="color:var(--color-text)">${texte(extraction.schema)}</strong> ·
      ${champs.length} champ(s) · ${douteux.size} à relire
    </div>
    <div style="border:1px solid var(--color-divider);margin-top:10px">
      ${champs
        .map(([champ, valeur]) => {
          const aRelire = douteux.has(champ);
          return `<div style="display:grid;grid-template-columns:170px minmax(0,1fr) auto;gap:12px;padding:10px 14px;border-bottom:1px solid var(--color-divider);align-items:center;${aRelire ? "background:var(--color-accent-100);" : ""}">
              <span style="font-size:12px;color:var(--color-neutral-700);font-family:ui-monospace,monospace">${texte(champ)}</span>
              <span style="font-size:14px;font-weight:500">${texte(valeur)}</span>
              <span class="${aRelire ? "tag tag-outline" : "tag tag-neutral"}">${aRelire ? "à relire" : "retrouvé"}</span>
            </div>`;
        })
        .join("")}
    </div>
    ${
      douteux.size
        ? `<div class="blueprint" style="padding:12px 14px;font-size:13px;margin-top:10px">
            <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
            <strong>${texte([...douteux].join(", "))}</strong> ne se retrouve pas tel quel dans le document. À relire avant tout usage.
          </div>`
        : ""
    }
    ${
      extraction.relue
        ? `<p style="margin:10px 0 0;font-size:13px"><span class="tag tag-accent">Validée</span> Cette version fait foi : une nouvelle campagne d'extraction ne l'écrasera pas.</p>`
        : `<div style="display:flex;gap:8px;margin-top:12px">
            <button id="bouton-valider-extraction" class="btn btn-primary blueprint" style="flex:none">
              <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Valider l'extraction
            </button>
          </div>`
    }`;
}

async function validerExtraction(identifiant) {
  try {
    await api(`/documents/${identifiant}/extraction/validation`, {
      method: "POST",
      body: JSON.stringify({ corrections: {} }),
    });
    await chargerPiece();
  } catch (echec) {
    $("#onglet-extraction").innerHTML = encadreErreur(echec);
  }
}

async function analyserPiece(identifiant) {
  const zone = $("#onglet-analyse");
  $$("[data-onglet]").forEach((b) => {
    const actif = b.dataset.onglet === "analyse";
    b.style.borderBottomColor = actif ? "var(--color-accent)" : "transparent";
    b.style.color = actif ? "var(--color-text)" : "var(--color-neutral-700)";
  });
  $("#onglet-extraction").hidden = true;
  zone.hidden = false;
  zone.innerHTML = attente("L'agent lit la pièce… 30 à 90 secondes sur processeur.");
  try {
    const reponse = await api(`/documents/${identifiant}/analyse`, {
      method: "POST",
      body: JSON.stringify({ demande: "" }),
    });
    const points = reponse.donnees.points_cles || [];
    zone.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--color-neutral-700);flex-wrap:wrap">
          <span class="tag tag-accent">${texte(reponse.donnees.categorie_detectee || "non déterminé")}</span>
          ${reponse.donnees.desaccord_categorie ? `<span class="tag tag-outline">désaccord avec la saisie du cabinet</span>` : ""}
          <span>${reponse.secondes.toFixed(0)} s</span>
        </div>
        ${reponse.donnees.resume ? `<p style="margin:0;font-size:14px;line-height:1.6">${texte(reponse.donnees.resume)}</p>` : `<p style="margin:0;font-size:13px;color:var(--color-neutral-700)">Le résumé a été écarté par les vérifications : il avançait un chiffre absent du document.</p>`}
        <div>
          <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:6px">Ce qui engage</div>
          ${
            points.length
              ? points
                  .map(
                    (p) => `<div style="border-left:2px solid var(--color-accent);padding:8px 12px;font-size:13px;background:var(--color-accent-100);margin-bottom:8px">
                      <div style="font-weight:500;margin-bottom:3px">${texte(p.titre)}</div>
                      « ${texte(p.citation)} »
                    </div>`,
                  )
                  .join("")
              : `<p style="margin:0;font-size:13px;color:var(--color-neutral-700)">Rien de relevé — et c'est une information : aucune phrase du document n'a pu être citée.</p>`
          }
        </div>
      </div>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}
