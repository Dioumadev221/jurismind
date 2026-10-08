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
