# ADR 0008 — Validation humaine : une table, pas un `interrupt()`

- **Statut** : accepté
- **Date** : 2026-10-06
- **Concerne** : F9 (automatisation de workflows), F1 (connecteur CRM), F10 (API)

## Contexte

L'offre demande d'automatiser des gestes qui **sortent du cabinet** : rattacher un email à un
dossier, préparer une relance, créer une tâche dans le CRM — « après validation humaine ».

Ces gestes ne se reprennent pas de la même façon qu'une réponse mal formulée. Un email
rattaché au mauvais dossier le rend visible à l'équipe d'un autre client : c'est une fuite,
pas une imprécision. Une relance envoyée à un client qui a déjà payé est partie. Une tâche
créée deux fois fait du CRM une source fausse.

LangGraph propose `interrupt()` : le graphe s'arrête à un point de reprise et attend la
réponse pour continuer. C'est l'outil que la conception prévoyait au départ.

## Décision

1. **Une proposition est une ligne en base, pas une exécution suspendue.** Table
   `propositions` : type, cible, contenu, **justification**, force de l'indice, statut, qui a
   tranché et quand.

   *Pourquoi pas `interrupt()`* : il suppose que la confirmation arrive dans la seconde, au
   sein de la même session, au même processus. Dans un cabinet elle arrive le lendemain, elle
   est donnée par **quelqu'un d'autre** que celui qui a lancé le tri, et elle doit être
   relisible des mois plus tard quand on demandera qui a autorisé quoi. Une ligne en base
   répond aux trois ; un point de reprise en mémoire à aucun. `interrupt()` reste le bon
   outil pour une confirmation immédiate dans une même conversation — ce n'est pas ce cas.

   C'est aussi la cohérence du projet : une extraction est déjà *une proposition qu'un avocat
   valide* (ADR 0004). Les gestes suivent la même forme.

2. **Toute proposition porte sa raison.** `justification` ne peut pas être vide : « l'expéditeur
   est une partie du dossier D2026-0020 », « l'adversaire du dossier D2026-0028 est nommé dans
   l'échange ». Celui qui valide doit pouvoir contredire la machine, donc savoir ce qu'elle a vu.

3. **`validée` et `appliquée` sont deux états distincts.** Créer une tâche dans le CRM passe
   par le réseau. Une décision humaine ne doit pas être perdue parce que le CRM était éteint :
   la proposition devient `échouée`, garde son autorisation, et se rejoue sans redemander un oui.

4. **On ne tranche pas deux fois.** Valider une proposition déjà tranchée lève une erreur au
   lieu de produire l'effet une seconde fois. Le tri lui-même est rejouable sans rien dupliquer :
   une proposition déjà en attente n'est pas redéposée.

5. **Une écriture CRM n'est rejouée que sur 429.** Une lecture rejouée ne coûte rien ; une
   écriture rejouée peut créer deux fois la même tâche. Sur 429 le CRM dit explicitement qu'il
   n'a pas traité la demande, donc rejouer est sûr. Sur 500 ou sur une coupure, on ne sait pas
   si l'écriture a eu lieu : on s'arrête et on le dit. C'est le contraire de la politique de
   lecture de l'ADR 0001, et c'est volontaire.

6. **Le rattachement et la priorité sont calculés, jamais demandés au modèle.** Cinq indices
   nommés, du plus fiable au moins fiable, et **rien** quand deux indices de même force
   désignent des dossiers différents. Le modèle ne fait que résumer et rédiger.

7. **JurisMind n'envoie rien.** Un brouillon validé est *approuvé pour envoi* ; c'est un humain
   qui l'envoie, depuis sa messagerie. Aucun code d'envoi n'existe dans le projet, et c'est une
   décision, pas un oubli.

## Mesures (boîte réelle du cabinet, `qwen2.5:3b`, sans GPU)

6 échanges n'étaient rattachés à aucun dossier sur les 397 repris.

| Échange | Indice retenu | Rattachement | Priorité |
|---|---|---|---|
| Courrier d'un confrère citant une opposition | `partie_au_dossier` | **D2026-0020** | haute |
| Client signalant des loyers impayés | `contact_et_adverse` | **D2026-0028** | moyenne |
| 4 demandes de rendez-vous de prospects | aucun | **aucun** (tâche CRM) | basse |

- **12 propositions** déposées pour 6 emails, ~25 s par email (deux appels au modèle).
- Validation vérifiée de bout en bout : l'échange rattaché a bien changé de dossier **et ses
  extraits avec lui** (sans quoi la recherche ne le retrouverait pas), et la tâche
  `TSK-00015` existe réellement dans le CRM, au nom de l'avocat qui a validé.
- Une seconde validation de la même proposition est refusée.

### Un faux rattachement attrapé par la mesure

Le courrier « Loyers impayés – Baobab Immobilier SARL » désignait d'abord **deux** dossiers du
même client : l'adversaire de l'un est « Cap-Vert Immobilier SARL », celui de l'autre « Baobab
Immobilier SARL », et le mot *Immobilier* leur est commun. La règle corrigée ne retient qu'un
mot **propre à un seul dossier** : « Baobab » tranche, « Immobilier » ne vaut rien. C'est la
même leçon que la déduplication des clients (ADR 0001) : un mot générique ne porte pas
d'identité.

## Conséquences

- 35 tests, dont ceux qui comptent : le mot partagé ne rattache rien, une proposition visant le
  dossier d'autrui est invisible, un CRM muet laisse la proposition rejouable, un compte CRM
  introuvable le dit clairement, et valider un brouillon **ne crée aucun échange sortant**.
- La table des propositions est ce que l'API REST (F10) exposera : une file de décisions à
  prendre, et non des actions déjà faites. Les fonctions rendent un enregistrement détaché
  (`Decision`) et non la ligne ORM, pour qu'une lecture après la fermeture de la session ne
  lève pas `DetachedInstanceError`.
- Limite assumée : les formules d'appel ne nomment pas l'interlocuteur. Nommer quelqu'un en
  français suppose une civilité, et la table `contacts` n'en porte pas — la déduire du prénom
  se trompe une fois sur deux (« Monsieur Diallo » pour Ndeye Diallo). À proposer au cabinet :
  saisir la civilité, et l'appel pourra être nominatif.
- Piste suivante : déclencher le tri à l'arrivée du courrier plutôt qu'à la demande, et
  alimenter les propositions depuis les points d'attention de F6 (une relance proposée pour un
  courrier resté sans réponse).
