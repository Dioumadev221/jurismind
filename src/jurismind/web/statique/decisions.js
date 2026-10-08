"use strict";

/**
 * Les écrans où l'on décide : le tri du courrier, et les conflits d'intérêts.
 *
 * Ce sont les seuls endroits de l'interface qui déclenchent un effet. Ils affichent donc
 * toujours **sur quoi la machine se fonde**, et n'agissent qu'après un clic : l'agent
 * propose, l'avocat tranche, et la décision reste inscrite en base avec son nom.
 */

// --------------------------------------------------------------------------- courrier

const CONFIANCES = { haute: "tag tag-accent", moyenne: "tag tag-outline", faible: "tag tag-neutral" };
const TYPES = {
  rattachement: "Rattachement",
  brouillon: "Brouillon de réponse",
  tache_crm: "Tâche CRM",
};

async function ecranCourrier() {
  patienter("Chargement du courrier…");
  const [aTrier, propositions] = await Promise.all([
    api("/courrier/a-trier"),
    api("/propositions"),
  ]);

  $("#ecran").innerHTML = `
    ${enTete("Tri du courrier entrant", "Le courrier", "L'agent propose ; vous décidez. Rien ne se produit avant un clic sur « Valider », et la décision reste inscrite en base avec votre nom. JurisMind n'envoie aucun email.")}
    <div style="display:grid;grid-template-columns:340px minmax(0,1fr);gap:24px;align-items:start">
      <section style="display:flex;flex-direction:column;border:1px solid var(--color-divider)">
        <div style="display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--color-divider)">
          <div style="flex:1">
            <div style="font-weight:500">À trier</div>
            <div style="font-size:12px;color:var(--color-neutral-700)">${aTrier.length} échange(s) qu'aucun dossier ne réclame</div>
          </div>
          <button id="bouton-trier" class="btn btn-secondary" style="white-space:nowrap;flex:none;font-size:13px"${aTrier.length ? "" : " disabled"}>Trier le courrier</button>
        </div>
        ${aTrier.map(ligneCourrier).join("") || `<p style="padding:14px;margin:0;font-size:13px;color:var(--color-neutral-700)">Tout le courrier est rattaché.</p>`}
      </section>

      <section style="display:flex;flex-direction:column;gap:16px;min-width:0">
        <div style="display:flex;align-items:baseline;gap:10px">
          <h3 style="font-size:22px;margin:0">${propositions.length} décision(s) à prendre</h3>
          <span style="font-size:12px;color:var(--color-neutral-700)">les plus sûres d'abord</span>
        </div>
        <div id="liste-propositions" style="display:flex;flex-direction:column;gap:16px">
          ${propositions.map(carteProposition).join("") || `<p style="margin:0;font-size:14px">Rien n'attend de décision.</p>`}
        </div>
      </section>
    </div>`;

  const trier = $("#bouton-trier");
  if (trier) trier.addEventListener("click", trierCourrier);
  brancherDecisions();
}

function ligneCourrier(echange) {
  return `<div style="padding:10px 14px;border-bottom:1px solid var(--color-divider);display:flex;flex-direction:column;gap:2px">
      <div style="display:flex;justify-content:space-between;gap:8px">
        <span style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${texte(echange.objet || "sans objet")}</span>
        <span style="font-size:11px;color:var(--color-neutral-700);flex:none">${texte(dateCourte(echange.date))}</span>
      </div>
      <span style="font-size:12px;color:var(--color-neutral-700);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${texte(echange.expediteur || "expéditeur inconnu")}</span>
    </div>`;
}

function carteProposition(proposition) {
  const donnees = proposition.donnees || {};
  return `<div class="blueprint" data-proposition="${proposition.id}" style="padding:16px 18px;display:flex;flex-direction:column;gap:10px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <span class="tag tag-neutral" style="font-size:10px;letter-spacing:.06em;text-transform:uppercase">${texte(TYPES[proposition.type] || proposition.type)}</span>
        <span class="${CONFIANCES[proposition.confiance] || "tag tag-neutral"}">confiance ${texte(proposition.confiance)}</span>
        <span style="flex:1"></span>
        <span style="font-size:12px;color:var(--color-neutral-700)">#${proposition.id}</span>
      </div>
      <div style="font-family:var(--font-heading);font-weight:600;font-size:18px;line-height:1.25">${texte(proposition.titre)}</div>
      <div style="font-size:13px;color:var(--color-neutral-800)">
        <span style="color:var(--color-neutral-700)">Fondement :</span> ${texte(proposition.justification)}
      </div>
      ${proposition.contenu ? `<pre style="margin:0;padding:12px 14px;border:1px solid var(--color-divider);background:var(--color-surface);font-family:var(--font-body);font-size:13px;line-height:1.55;white-space:pre-wrap">${texte(proposition.contenu)}</pre>` : ""}
      ${donnees.priorite ? `<div style="font-size:12px;color:var(--color-neutral-700)">Priorité <strong style="color:var(--color-text)">${texte(donnees.priorite)}</strong> — ${texte(donnees.priorite_pourquoi || "")}</div>` : ""}
      <div class="zone-decision" style="display:flex;gap:8px;padding-top:4px">
        <button data-valider="${proposition.id}" class="btn btn-primary blueprint" style="white-space:nowrap;flex:none">
          <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Valider
        </button>
        <button data-rejeter="${proposition.id}" class="btn btn-secondary" style="white-space:nowrap;flex:none">Rejeter</button>
      </div>
    </div>`;
}

function brancherDecisions() {
  $$("[data-valider]").forEach((bouton) =>
    bouton.addEventListener("click", () => trancher(bouton.dataset.valider, "validation")),
  );
  $$("[data-rejeter]").forEach((bouton) =>
    bouton.addEventListener("click", () => trancher(bouton.dataset.rejeter, "rejet")),
  );
}

/** Le seul endroit de l'interface qui produit un effet hors du cabinet. */
async function trancher(identifiant, action) {
  const carte = document.querySelector(`[data-proposition="${identifiant}"]`);
  const zone = carte.querySelector(".zone-decision");
  zone.innerHTML = attente(action === "validation" ? "Application en cours…" : "Enregistrement du refus…");
  try {
    const corps = action === "rejet" ? { motif: "rejetée depuis l'interface" } : {};
    const tranchee = await api(`/propositions/${identifiant}/${action}`, {
      method: "POST",
      body: JSON.stringify(corps),
    });
    const etiquetteStatut = tranchee.statut === "appliquee" ? "tag tag-accent" : "tag tag-outline";
    carte.style.opacity = "0.75";
    zone.outerHTML = `<div style="display:flex;align-items:center;gap:8px;font-size:13px;padding-top:6px;border-top:1px solid var(--color-divider);flex-wrap:wrap">
        <span class="${etiquetteStatut}">${texte(tranchee.statut)}</span>
        <span style="color:var(--color-neutral-700)">décidée par vous, inscrite en base</span>
        ${tranchee.erreur ? `<span style="color:var(--color-accent-900)">— ${texte(tranchee.erreur)}</span>` : ""}
        ${tranchee.donnees && tranchee.donnees.crm_task_id ? `<span style="color:var(--color-neutral-700)">— tâche CRM ${texte(tranchee.donnees.crm_task_id)}</span>` : ""}
      </div>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}

async function trierCourrier() {
  const bouton = $("#bouton-trier");
  bouton.disabled = true;
  bouton.textContent = "Tri en cours…";
  $("#liste-propositions").innerHTML = attente(
    "L'agent examine chaque email : rattachement et priorité par des règles, résumé et brouillon par le modèle. Environ 25 secondes par email.",
  );
  try {
    await api("/courrier/tri", { method: "POST", body: JSON.stringify({ limite: 20 }) });
    await ecranCourrier();
  } catch (echec) {
    $("#liste-propositions").innerHTML = encadreErreur(echec);
    bouton.disabled = false;
    bouton.textContent = "Trier le courrier";
  }
}

// --------------------------------------------------------------------------- conflits

async function ecranConflits() {
  $("#ecran").innerHTML = `
    ${enTete("Conformité", "Conflits d'intérêts", "Ce contrôle regarde tout le cabinet, y compris les dossiers qui vous sont fermés — sans cela il manquerait justement les conflits qu'il cherche. Il ne vous nomme que les dossiers auxquels vous avez accès, et chaque vérification est inscrite au journal.")}
    <div style="display:flex;gap:4px;border-bottom:1px solid var(--color-divider)">
      <button data-conflit="avant" style="border:0;background:transparent;font:inherit;font-size:14px;padding:9px 12px;cursor:pointer;margin-bottom:-1px;border-bottom:2px solid var(--color-accent)">Avant d'accepter une affaire</button>
      <button data-conflit="cabinet" style="border:0;background:transparent;font:inherit;font-size:14px;padding:9px 12px;cursor:pointer;margin-bottom:-1px;border-bottom:2px solid transparent;color:var(--color-neutral-700)">Tout le cabinet</button>
    </div>

    <div id="conflit-avant">
      <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;max-width:760px">
        <label style="flex:1;min-width:260px">
          <span style="display:block;font-size:12px;color:var(--color-neutral-700);margin-bottom:5px">Dénomination de la partie adverse</span>
          <input id="champ-conflit" class="input" style="width:100%;box-sizing:border-box" value="Sine Services SARL">
        </label>
        <button id="bouton-conflit" class="btn btn-primary blueprint" style="white-space:nowrap;flex:none">
          <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Vérifier
        </button>
      </div>
      <div id="resultat-conflit" style="margin-top:16px"></div>
    </div>

    <div id="conflit-cabinet" hidden>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <p style="margin:0;font-size:13px;color:var(--color-neutral-700);flex:1">
          Toutes les parties adverses du cabinet, confrontées à sa liste de clients.
        </p>
        <button id="bouton-balayage" class="btn btn-secondary" style="white-space:nowrap;flex:none">Lancer le balayage</button>
      </div>
      <div id="resultat-balayage" style="margin-top:16px"></div>
    </div>`;

  $$("[data-conflit]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      const cible = bouton.dataset.conflit;
      $$("[data-conflit]").forEach((autre) => {
        const actif = autre.dataset.conflit === cible;
        autre.style.borderBottomColor = actif ? "var(--color-accent)" : "transparent";
        autre.style.color = actif ? "var(--color-text)" : "var(--color-neutral-700)";
      });
      $("#conflit-avant").hidden = cible !== "avant";
      $("#conflit-cabinet").hidden = cible !== "cabinet";
    }),
  );
  $("#bouton-conflit").addEventListener("click", verifierConflit);
  $("#champ-conflit").addEventListener("keydown", (e) => e.key === "Enter" && verifierConflit());
  $("#bouton-balayage").addEventListener("click", balayerCabinet);
}

async function verifierConflit() {
  const zone = $("#resultat-conflit");
  const nom = $("#champ-conflit").value.trim();
  if (!nom) return;
  zone.innerHTML = attente("Confrontation à la liste des clients du cabinet…");
  try {
    const conflits = await api("/conformite/verification", {
      method: "POST",
      body: JSON.stringify({ nom }),
    });
    zone.innerHTML = conflits.length
      ? `<div style="display:flex;flex-direction:column;gap:10px;max-width:880px">
          <div style="font-size:12px;color:var(--color-neutral-700)">${conflits.length} collision(s) · vérification inscrite au journal</div>
          ${conflits.map(carteConflit).join("")}
          <p style="margin:0;font-size:12px;color:var(--color-neutral-700)">
            Le contrôle repose sur les noms : il ne voit ni changement de dénomination, ni filiale, ni dirigeant commun.
          </p>
        </div>`
      : `<div style="max-width:880px">
          <p style="margin:0;font-size:14px">Rien trouvé au nom de « ${texte(nom)} » dans les données du cabinet.</p>
          <p style="margin:6px 0 0;font-size:12px;color:var(--color-neutral-700)">
            Une liste vide dit ce qui a été cherché, pas que tout va bien.
          </p>
        </div>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}

function carteConflit(conflit) {
  const certain = conflit.niveau === "certain";
  return `<div class="blueprint" style="padding:18px 20px;display:flex;flex-direction:column;gap:10px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <span class="${certain ? "tag tag-accent" : "tag tag-outline"}">${certain ? "Certain" : "À vérifier"}</span>
        <span class="tag tag-neutral">${texte(conflit.relation)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;font-family:var(--font-heading);font-weight:600;font-size:22px">
        <span>${texte(conflit.partie)}</span>
        <span style="color:var(--color-accent);font-weight:400">≈</span>
        <span>${texte(conflit.client)}</span>
      </div>
      <div style="font-size:13px;color:var(--color-neutral-800)">${texte(conflit.explication)}</div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;font-size:13px;border-top:1px solid var(--color-divider);padding-top:10px">
        <div>
          <div style="font-size:11px;color:var(--color-neutral-700)">Dossiers concernés que vous pouvez consulter</div>
          <span style="font-family:var(--font-heading);font-weight:600;color:var(--color-accent-700)">${texte(conflit.dossiers_visibles.join(", ") || "aucun")}</span>
        </div>
        ${
          conflit.autres_dossiers
            ? `<div>
                <div style="font-size:11px;color:var(--color-neutral-700)">Autres dossiers du cabinet</div>
                <span>${conflit.autres_dossiers} — comptés, pas nommés</span>
              </div>`
            : ""
        }
      </div>
    </div>`;
}

async function balayerCabinet() {
  const zone = $("#resultat-balayage");
  zone.innerHTML = attente("Confrontation de toutes les parties adverses à la liste des clients…");
  try {
    const resultats = await api("/conformite/balayage");
    zone.innerHTML = resultats.length
      ? `<table class="table">
          <thead><tr><th>Dossier</th><th>Partie adverse</th><th>Client du cabinet</th><th>Relation</th><th>Niveau</th></tr></thead>
          <tbody>
            ${resultats
              .map(({ dossier, conflit }) => {
                const certain = conflit.niveau === "certain";
                return `<tr>
                    <td style="font-family:var(--font-heading);font-weight:600;color:var(--color-accent-700)">${texte(dossier)}</td>
                    <td>${texte(conflit.partie)}</td>
                    <td>${texte(conflit.client)}</td>
                    <td>${texte(conflit.relation)}</td>
                    <td><span class="${certain ? "tag tag-accent" : "tag tag-outline"}">${certain ? "Certain" : "À vérifier"}</span></td>
                  </tr>`;
              })
              .join("")}
          </tbody>
        </table>`
      : `<p style="margin:0;font-size:14px">Aucune collision dans le cabinet.</p>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}
