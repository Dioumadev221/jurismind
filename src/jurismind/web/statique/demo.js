"use strict";

/**
 * La démonstration publique, vue de l'interface.
 *
 * Rien ici ne s'active hors démonstration : `GET /demo` répond 404 sur une installation
 * réelle, et l'interface reste celle d'un cabinet. En démonstration, trois ajouts :
 *
 * - l'entrée sans mot de passe sur les comptes du scénario — le jeton reçu est un jeton
 *   ordinaire, et PostgreSQL applique ses droits comme à n'importe qui ;
 * - le bandeau « cabinet simulé », qui dit le jour où le cabinet a été figé ;
 * - les demandes préparées : celles dont la réponse du modèle a été enregistrée. Les autres
 *   reçoivent une phrase qui l'explique, jamais une réponse inventée.
 */

etat.demo = null;

async function chargerDemo() {
  try {
    etat.demo = await api("/demo");
  } catch {
    etat.demo = null; // installation réelle : pas de démonstration
  }
  return etat.demo;
}

/** Les demandes préparées pour le compte connecté, d'une nature donnée. */
function demandesDemo(nature) {
  if (!etat.demo || !etat.compte) return [];
  return etat.demo.demandes.filter((d) => d.nature === nature && d.compte === etat.compte.email);
}

function estPreparee(nature, cible) {
  return demandesDemo(nature).some((d) => String(d.cible) === String(cible));
}

function dateCabinet() {
  const valeur = etat.demo && etat.demo.date_du_cabinet;
  return valeur ? new Date(`${valeur}T12:00:00`).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "";
}

/**
 * La note sous un bouton d'agent : préparé ici, ou bien où aller pour voir l'agent répondre.
 * Hors démonstration, rien.
 */
function noteDemo(nature, cible) {
  if (!etat.demo) return "";
  if (estPreparee(nature, cible)) {
    return `<p class="note-demo">Démonstration : la réponse du modèle à cette demande a été enregistrée. Recherche, contrôles et droits s'exécutent maintenant, pour de vrai.</p>`;
  }
  const ailleurs = demandesDemo(nature)
    .map((d) => d.contexte ? `${d.cible} (${d.contexte.slice(0, 40)})` : d.cible)
    .slice(0, 3)
    .join(", ");
  return `<p class="note-demo">Démonstration publique : ce serveur ne fait pas tourner de modèle. ${
    ailleurs ? `L'agent a été préparé sur ${texte(ailleurs)}.` : ""
  } Tout ce qui ne demande pas de modèle (chronologie, points d'attention, échéances, conflits) fonctionne partout.</p>`;
}

/**
 * La durée d'une réponse. Rejouée, elle est instantanée : afficher « 0 s » laisserait croire que
 * le modèle répond ainsi sur processeur. On dit donc qu'elle est rejouée.
 */
function duree(secondes) {
  return etat.demo ? "réponse rejouée" : `${secondes.toFixed(0)} s`;
}

// --------------------------------------------------------------------- écran d'entrée

function rendreEntreeDemo() {
  const zone = $("#entree-demo");
  if (!etat.demo || !zone) return;
  zone.hidden = false;
  zone.innerHTML = `
    <div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--color-accent-700);margin-bottom:8px">Démonstration · cabinet simulé</div>
    <p style="margin:0 0 14px;font-size:13px;line-height:1.5;color:var(--color-neutral-800)">
      Un cabinet d'avocats de Dakar inventé de toutes pièces, figé au ${texte(dateCabinet())} : 433 pièces, dont 135 scans lus par OCR.
      Aucune donnée réelle. Choisissez un compte :
    </p>
    <div style="display:flex;flex-direction:column;gap:8px">
      ${etat.demo.comptes
        .map(
          (c) => `<button type="button" class="compte-demo" data-email="${texte(c.email)}">
            <span style="font-weight:600">${texte(c.nom)}</span>
            <span style="font-size:12px;color:var(--color-neutral-700)">${texte(c.presentation)}</span>
          </button>`,
        )
        .join("")}
    </div>
    <div style="display:flex;align-items:center;gap:10px;margin:20px 0 4px;font-size:11px;color:var(--color-neutral-600)">
      <span style="flex:1;border-top:1px solid var(--color-divider)"></span>ou avec un mot de passe<span style="flex:1;border-top:1px solid var(--color-divider)"></span>
    </div>`;
  $$(".compte-demo").forEach((bouton) =>
    bouton.addEventListener("click", async () => {
      bouton.disabled = true;
      try {
        const reponse = await api("/demo/connexion", { method: "POST", body: JSON.stringify({ email: bouton.dataset.email }) });
        etat.jeton = reponse.jeton;
        etat.compte = reponse.utilisateur;
        sessionStorage.setItem(CLE_JETON, etat.jeton);
        sessionStorage.setItem(CLE_COMPTE, JSON.stringify(etat.compte));
        await montrerApplication();
      } catch (echec) {
        const erreur = $("#erreur-connexion");
        erreur.textContent = echec.detail || "Le service ne répond pas.";
        erreur.hidden = false;
      } finally {
        bouton.disabled = false;
      }
    }),
  );
}

/** Le bandeau de l'en-tête, sur chaque écran. */
function rendreBandeauDemo() {
  const bandeau = $("#bandeau-demo");
  if (!bandeau) return;
  bandeau.hidden = !etat.demo;
  if (etat.demo) bandeau.textContent = `Cabinet simulé · au ${dateCabinet()}`;
}

chargerDemo().then(() => {
  rendreEntreeDemo();
  rendreBandeauDemo();
  // L'application a pu s'ouvrir avant la réponse (jeton gardé en session) : on redessine
  // l'écran courant, pour qu'il montre ses demandes préparées.
  if (etat.demo && etat.jeton && !$("#application").hidden) aller(etat.ecran);
});
