# ADR 0002 — Rapprochement des comptes CRM et résistance de l'API

- **Statut** : accepté
- **Date** : 2026-09-28
- **Concerne** : F1 (connecter l'IA au CRM), F6 (agent intelligence client)

## Contexte

Le CRM est un système **séparé**, rempli à la main par les associés. Il n'a ni les mêmes
identifiants ni la même écriture des noms que le logiciel de gestion : « Sahel Pêche » d'un
côté, « SAHEL PÊCHE SA » de l'autre. Il contient aussi des **prospects**, qui ne sont pas
clients du cabinet.

Son API se comporte comme un vrai service : clé d'API, pagination, et erreurs 429 ou 503
aléatoires.

## Décision

1. **Rapprochement par indices classés par fiabilité** : NINEA (identifiant fiscal) >
   téléphone normalisé > domaine du site ou de l'email > dénomination **et** ville.
   Une clé qui désigne plusieurs clients est écartée.
2. **Un compte par client, un client par compte.** Quand deux comptes visent le même client,
   l'indice le plus fiable l'emporte ; à égalité, **aucun** n'est retenu.
3. **Les comptes non rapprochés sont ignorés**, avec une trace dans les journaux. Un prospect
   n'a pas de place dans JurisMind, où tout est rattaché à un client existant.
4. **Reprise sur erreur** : les codes 429, 500, 502, 503 et 504 sont réessayés (quatre
   tentatives, attente exponentielle avec part d'aléatoire, en respectant `Retry-After`).
   Les codes définitifs (401, 404) échouent immédiatement.
5. **Le CRM est un complément** : s'il reste injoignable, la synchronisation du logiciel de
   gestion reste valide et l'échec est signalé sans bloquer le reste.
6. Les éléments importés (opportunités, comptes rendus de rendez-vous, tâches) sont stockés
   dans `elements_crm`, visibles uniquement si leur client l'est (Row-Level Security).

## Conséquences

- Sur les données du cabinet simulé : **35 comptes rapprochés sur 39**, les 4 restants étant
  exactement les 4 prospects.
- Une première version rapprochait par la seule dénomination, forme juridique retirée : le
  prospect « Casamance Services SARL » écrasait alors le client « Casamance Services SA ».
  D'où l'ajout de la ville et la résolution des conflits ; deux tests verrouillent ces deux
  comportements.
- Le rapprochement reste **conservateur** : un client non enrichi est préférable à un client
  enrichi avec les informations d'un autre, qui serait une fuite de données.
- Piste ultérieure : proposer les comptes non rapprochés à un humain plutôt que les ignorer.
