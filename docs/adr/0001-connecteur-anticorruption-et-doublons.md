# ADR 0001 — Connecteur anticorruption et fusion prudente des doublons

- **Statut** : accepté
- **Date** : 2026-09-28
- **Concerne** : F1 (connecter l'IA à la base clients/dossiers), F12 (isolation)

## Contexte

Le logiciel du cabinet (base `legacy`) a ses propres conventions : codes `PM`/`PP`,
`EC`/`CL`/`AR`, `CTX`/`CSL`, téléphones saisis de quatre façons, champs vides, catégories
de documents fausses ou « DIVERS », pièces jointes entassées dans une case texte
(`180;181;182`), et plusieurs fiches pour un même client (créées à des années d'écart).

La base n'a **pas** de colonne de dernière modification : aucune synchronisation
incrémentale n'est possible côté source.

## Décision

1. **Couche anticorruption.** Les conventions de `legacy` s'arrêtent à
   `src/jurismind/connectors/legacy.py`. Le reste du produit ne connaît que le modèle
   JurisMind (`TypeClient.SOCIETE`, `StatutDossier.EN_COURS`…). Changer de logiciel source
   revient à réécrire ce seul fichier.
2. **Un code inconnu arrête la synchronisation** (`DonneeIllisible`) au lieu d'être ignoré
   en silence : une donnée mal traduite est pire qu'une synchronisation en échec.
3. **Synchronisation complète et idempotente**, faute d'horodatage à la source :
   rapprochement par `external_id`, et mise à jour des seules colonnes que le connecteur
   renseigne. Les colonnes remplies ensuite par l'ingestion ou par l'IA (`texte`,
   `empreinte_sha256`, `categorie_detectee`, `embedding`…) ne sont jamais écrasées.
4. **Fusion prudente des doublons clients** :
   - même RCCM (identifiant officiel) → même société ;
   - sans RCCM, une société est reconnue par sa dénomination complète **et** sa ville ;
   - un particulier n'est rapproché que si son nom **et** un moyen de contact coïncident.
   Les fiches d'origine restent rattachées au client retenu dans `alias_clients`, pour que
   la synchronisation demeure rejouable.

## Conséquences

- Le connecteur préfère **deux fiches d'un même client** (corrigeable) à **deux clients
  différents fusionnés** : une fusion abusive donnerait accès aux dossiers d'un tiers, donc
  une violation du secret professionnel.
- Une première version, fondée sur le seul nom, fusionnait trois clients « Cissé »
  distincts : la règle a été durcie et un test (`test_deux_homonymes_ne_sont_jamais_fusionnes`)
  verrouille ce comportement.
- Le tri des emails non classés reste possible : les communications sans dossier sont
  importées telles quelles (agent F9).
- Coût : chaque synchronisation relit toute la base source (~1 500 lignes, 3 secondes).
  Avec une vraie base disposant d'un horodatage, seules les lignes modifiées seraient lues.
