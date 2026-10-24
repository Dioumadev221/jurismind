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
  rattachement: "Link to matter",
  brouillon: "Draft reply",
  tache_crm: "CRM task",
};
/** Les valeurs de la base, telles qu'un lecteur anglophone les attend. */
const NIVEAUX = { haute: "high", moyenne: "medium", faible: "low", basse: "low" };
const STATUTS_PROPOSITION = { proposee: "proposed", validee: "approved", appliquee: "applied", rejetee: "rejected", echouee: "failed" };
const RELATIONS = { "client actuel": "current client", "ancien client": "former client" };

async function ecranCourrier() {
  patienter("Loading the inbox…");
  const [aTrier, propositions] = await Promise.all([
    api("/courrier/a-trier"),
    api("/propositions"),
  ]);

  $("#ecran").innerHTML = `
    ${enTete("Incoming mail triage", "Inbox", "The agent proposes; you decide. Nothing happens before you click “Approve”, and the decision is recorded in the database with your name. JurisMind never sends an email.")}
    <div style="display:grid;grid-template-columns:340px minmax(0,1fr);gap:24px;align-items:start">
      <section style="display:flex;flex-direction:column;border:1px solid var(--color-divider)">
        <div style="display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--color-divider)">
          <div style="flex:1">
            <div style="font-weight:500">To triage</div>
            <div style="font-size:12px;color:var(--color-neutral-700)">${aTrier.length} message(s) not linked to any matter</div>
          </div>
          <button id="bouton-trier" class="btn btn-secondary" style="white-space:nowrap;flex:none;font-size:13px"${aTrier.length ? "" : " disabled"}>Triage mail</button>
        </div>
        ${aTrier.map(ligneCourrier).join("") || `<p style="padding:14px;margin:0;font-size:13px;color:var(--color-neutral-700)">All mail is linked to a matter.</p>`}
      </section>

      <section style="display:flex;flex-direction:column;gap:16px;min-width:0">
        <div style="display:flex;align-items:baseline;gap:10px">
          <h3 style="font-size:22px;margin:0">${propositions.length} decision(s) to make</h3>
          <span style="font-size:12px;color:var(--color-neutral-700)">most confident first</span>
        </div>
        <div id="liste-propositions" style="display:flex;flex-direction:column;gap:16px">
          ${propositions.map(carteProposition).join("") || `<p style="margin:0;font-size:14px">Nothing is waiting for a decision.</p>`}
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
        <span style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${texte(echange.objet || "no subject")}</span>
        <span style="font-size:11px;color:var(--color-neutral-700);flex:none">${texte(dateCourte(echange.date))}</span>
      </div>
      <span style="font-size:12px;color:var(--color-neutral-700);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${texte(echange.expediteur || "unknown sender")}</span>
    </div>`;
}

function carteProposition(proposition) {
  const donnees = proposition.donnees || {};
  return `<div class="blueprint" data-proposition="${proposition.id}" style="padding:16px 18px;display:flex;flex-direction:column;gap:10px">
      <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
      <div style="display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <span class="tag tag-neutral" style="font-size:10px;letter-spacing:.06em;text-transform:uppercase">${texte(TYPES[proposition.type] || proposition.type)}</span>
        <span class="${CONFIANCES[proposition.confiance] || "tag tag-neutral"}">${texte(NIVEAUX[proposition.confiance] || proposition.confiance)} confidence</span>
        <span style="flex:1"></span>
        <span style="font-size:12px;color:var(--color-neutral-700)">#${proposition.id}</span>
      </div>
      <div style="font-family:var(--font-heading);font-weight:600;font-size:18px;line-height:1.25">${texte(proposition.titre)}</div>
      <div style="font-size:13px;color:var(--color-neutral-800)">
        <span style="color:var(--color-neutral-700)">Grounds:</span> ${texte(proposition.justification)}
      </div>
      ${proposition.contenu ? `<pre style="margin:0;padding:12px 14px;border:1px solid var(--color-divider);background:var(--color-surface);font-family:var(--font-body);font-size:13px;line-height:1.55;white-space:pre-wrap">${texte(proposition.contenu)}</pre>` : ""}
      ${donnees.priorite ? `<div style="font-size:12px;color:var(--color-neutral-700)">Priority <strong style="color:var(--color-text)">${texte(NIVEAUX[donnees.priorite] || donnees.priorite)}</strong> · ${texte(donnees.priorite_pourquoi || "")}</div>` : ""}
      <div class="zone-decision" style="display:flex;gap:8px;padding-top:4px">
        <button data-valider="${proposition.id}" class="btn btn-primary blueprint" style="white-space:nowrap;flex:none">
          <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Approve
        </button>
        <button data-rejeter="${proposition.id}" class="btn btn-secondary" style="white-space:nowrap;flex:none">Reject</button>
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
  zone.innerHTML = attente(action === "validation" ? "Applying…" : "Recording the rejection…");
  try {
    const corps = action === "rejet" ? { motif: "rejected from the interface" } : {};
    const tranchee = await api(`/propositions/${identifiant}/${action}`, {
      method: "POST",
      body: JSON.stringify(corps),
    });
    const etiquetteStatut = tranchee.statut === "appliquee" ? "tag tag-accent" : "tag tag-outline";
    carte.style.opacity = "0.75";
    zone.outerHTML = `<div style="display:flex;align-items:center;gap:8px;font-size:13px;padding-top:6px;border-top:1px solid var(--color-divider);flex-wrap:wrap">
        <span class="${etiquetteStatut}">${texte(STATUTS_PROPOSITION[tranchee.statut] || tranchee.statut)}</span>
        <span style="color:var(--color-neutral-700)">decided by you, recorded in the database</span>
        ${tranchee.erreur ? `<span style="color:var(--color-accent-900)">— ${texte(tranchee.erreur)}</span>` : ""}
        ${tranchee.donnees && tranchee.donnees.crm_task_id ? `<span style="color:var(--color-neutral-700)">· CRM task ${texte(tranchee.donnees.crm_task_id)}</span>` : ""}
      </div>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}

async function trierCourrier() {
  const bouton = $("#bouton-trier");
  bouton.disabled = true;
  bouton.textContent = "Triaging…";
  $("#liste-propositions").innerHTML = attente(
    etat.demo ? "The agent reviews each email: matter and priority by rules, summary and draft by the model." : "The agent reviews each email: matter and priority by rules, summary and draft by the model. About 25 seconds per email on CPU.",
  );
  try {
    await api("/courrier/tri", { method: "POST", body: JSON.stringify({ limite: 20 }) });
    await ecranCourrier();
  } catch (echec) {
    $("#liste-propositions").innerHTML = encadreErreur(echec);
    bouton.disabled = false;
    bouton.textContent = "Triage mail";
  }
}

// --------------------------------------------------------------------------- conflits

async function ecranConflits() {
  $("#ecran").innerHTML = `
    ${enTete("Compliance", "Conflict check", "This check looks at the whole firm, including matters closed to you: otherwise it would miss the very conflicts it looks for. It only names the matters you can access, and every check is written to the audit log.")}
    <div style="display:flex;gap:4px;border-bottom:1px solid var(--color-divider)">
      <button data-conflit="avant" style="border:0;background:transparent;font:inherit;font-size:14px;padding:9px 12px;cursor:pointer;margin-bottom:-1px;border-bottom:2px solid var(--color-accent)">Before taking a new matter</button>
      <button data-conflit="cabinet" style="border:0;background:transparent;font:inherit;font-size:14px;padding:9px 12px;cursor:pointer;margin-bottom:-1px;border-bottom:2px solid transparent;color:var(--color-neutral-700)">Whole firm</button>
    </div>

    <div id="conflit-avant">
      <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;max-width:760px">
        <label style="flex:1;min-width:260px">
          <span style="display:block;font-size:12px;color:var(--color-neutral-700);margin-bottom:5px">Opposing party name</span>
          <input id="champ-conflit" class="input" style="width:100%;box-sizing:border-box" value="Sine Services SARL">
        </label>
        <button id="bouton-conflit" class="btn btn-primary blueprint" style="white-space:nowrap;flex:none">
          <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>Check
        </button>
      </div>
      <div id="resultat-conflit" style="margin-top:16px"></div>
    </div>

    <div id="conflit-cabinet" hidden>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <p style="margin:0;font-size:13px;color:var(--color-neutral-700);flex:1">
          Every opposing party in the firm, checked against its client list.
        </p>
        <button id="bouton-balayage" class="btn btn-secondary" style="white-space:nowrap;flex:none">Run firm-wide scan</button>
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
  zone.innerHTML = attente("Checking against the firm's client list…");
  try {
    const conflits = await api("/conformite/verification", {
      method: "POST",
      body: JSON.stringify({ nom }),
    });
    zone.innerHTML = conflits.length
      ? `<div style="display:flex;flex-direction:column;gap:10px;max-width:880px">
          <div style="font-size:12px;color:var(--color-neutral-700)">${conflits.length} match(es) · check written to the audit log</div>
          ${conflits.map(carteConflit).join("")}
          <p style="margin:0;font-size:12px;color:var(--color-neutral-700)">
            The check relies on names: it cannot see a renamed company, a subsidiary or a shared director.
          </p>
        </div>`
      : `<div style="max-width:880px">
          <p style="margin:0;font-size:14px">Nothing found under “${texte(nom)}” in the firm's data.</p>
          <p style="margin:6px 0 0;font-size:12px;color:var(--color-neutral-700)">
            An empty list says what was searched, not that all is well.
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
        <span class="${certain ? "tag tag-accent" : "tag tag-outline"}">${certain ? "Certain" : "To verify"}</span>
        <span class="tag tag-neutral">${texte(RELATIONS[conflit.relation] || conflit.relation)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;font-family:var(--font-heading);font-weight:600;font-size:22px">
        <span>${texte(conflit.partie)}</span>
        <span style="color:var(--color-accent);font-weight:400">≈</span>
        <span>${texte(conflit.client)}</span>
      </div>
      <div style="font-size:13px;color:var(--color-neutral-800)">${texte(conflit.explication)}</div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;font-size:13px;border-top:1px solid var(--color-divider);padding-top:10px">
        <div>
          <div style="font-size:11px;color:var(--color-neutral-700)">Matters involved that you can open</div>
          <span style="font-family:var(--font-heading);font-weight:600;color:var(--color-accent-700)">${texte(conflit.dossiers_visibles.join(", ") || "none")}</span>
        </div>
        ${
          conflit.autres_dossiers
            ? `<div>
                <div style="font-size:11px;color:var(--color-neutral-700)">Other matters in the firm</div>
                <span>${conflit.autres_dossiers}, counted but not named</span>
              </div>`
            : ""
        }
      </div>
    </div>`;
}

async function balayerCabinet() {
  const zone = $("#resultat-balayage");
  zone.innerHTML = attente("Checking every opposing party against the client list…");
  try {
    const resultats = await api("/conformite/balayage");
    zone.innerHTML = resultats.length
      ? `<table class="table">
          <thead><tr><th>Matter</th><th>Opposing party</th><th>Firm client</th><th>Relationship</th><th>Level</th></tr></thead>
          <tbody>
            ${resultats
              .map(({ dossier, conflit }) => {
                const certain = conflit.niveau === "certain";
                return `<tr>
                    <td style="font-family:var(--font-heading);font-weight:600;color:var(--color-accent-700)">${texte(dossier)}</td>
                    <td>${texte(conflit.partie)}</td>
                    <td>${texte(conflit.client)}</td>
                    <td>${texte(RELATIONS[conflit.relation] || conflit.relation)}</td>
                    <td><span class="${certain ? "tag tag-accent" : "tag tag-outline"}">${certain ? "Certain" : "To verify"}</span></td>
                  </tr>`;
              })
              .join("")}
          </tbody>
        </table>`
      : `<p style="margin:0;font-size:14px">No match in the firm.</p>`;
  } catch (echec) {
    zone.innerHTML = encadreErreur(echec);
  }
}
