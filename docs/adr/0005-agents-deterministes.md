# ADR 0005 — Agents : graphe déterministe plutôt que choix libre des outils

- **Statut** : accepté
- **Date** : 2026-10-02
- **Concerne** : F6 (intelligence client), F7 (assistance dossier), F9 (workflows)

## Contexte

L'offre demande des « AI Agents ». L'approche la plus répandue est l'agent *ReAct* : on donne
au modèle une liste d'outils et il décide seul lesquels appeler, dans quel ordre, et quand
s'arrêter.

Deux contraintes du projet pèsent contre cette liberté :

1. **La machine du cabinet n'a pas de GPU.** Le modèle de routage est `qwen2.5:3b`. Chaque
   tour de boucle coûte 10 à 30 secondes ; un agent qui tâtonne sur cinq tours met trois
   minutes à dire ce qu'une requête SQL donne instantanément.
2. **Une date ou un montant faux ne se rattrape pas.** Si c'est le modèle qui *résume* une
   chronologie, il peut décaler une date d'audience. Si c'est le code qui la construit à
   partir des dates en base, il ne peut pas.

## Décision

1. **Le graphe fixe les étapes, pas le modèle.** `comprendre → collecter → {question |
   resume | chronologie} → journaliser`. Le nombre d'appels au modèle est connu d'avance :
   un pour l'aiguillage (parfois zéro), un pour la rédaction.
2. **Le modèle ne sert qu'à comprendre et à rédiger.** Les faits — parties, dates, statut,
   montants, pièces — sont lus en base par les outils de `agents/outils.py`.
3. **Les mots-clés passent avant le modèle.** « résume », « chronologie », « où en est » :
   l'aiguillage est décidé par le code, sans appel réseau. Le modèle n'est sollicité que
   pour les demandes réellement ambiguës. Mesuré : une chronologie sort en **moins d'une
   seconde** au lieu de ~15 s.
4. **La chronologie est produite par le code.** Les documents et les échanges datés sont
   triés et mis en forme en Python. Le modèle ne la voit que s'il doit rédiger une synthèse.
5. **Les droits sont portés par la session, pas par l'agent.** Chaque outil reçoit la session
   ouverte au nom de l'utilisateur ; l'isolation est appliquée par PostgreSQL (RLS). Un
   dossier invisible fait répondre « Dossier introuvable » **avant** toute recherche : on ne
   révèle ni son existence, ni son contenu.
6. **La synthèse subit les mêmes contrôles qu'une réponse citée.** Tout chiffre qui ne se
   retrouve pas dans les matériaux fournis au modèle fait abandonner la synthèse (`chiffres_ancres`,
   ADR 0003). Mieux vaut pas de résumé qu'un résumé avec un mauvais montant.
7. **Chaque passage est journalisé** : utilisateur, dossier, intention, abstention, nombre de
   citations.

## Mesures (dossier D2026-0024, `qwen2.5:3b`, machine sans GPU)

| Demande | Appels au modèle | Durée | Résultat |
|---|---|---|---|
| « chronologie du dossier » | 0 | **< 1 s** | 11 événements datés, tirés de la base |
| « Quel est le montant total réclamé ? » | 2 (aiguillage + réponse) | 83 s | 13 750 000 FCFA, 1 citation — exact |
| synthèse (demande vide) | 1 | 78 s | 3 phrases, 6 pièces citées, montant et délai ancrés |

## Conséquences

- L'agent est **prévisible** : on peut dire à l'avance combien d'appels au modèle une demande
  coûte, ce qui rend la latence annonçable au cabinet.
- Le prix de ce choix est la souplesse : une demande qui ne tombe dans aucune des trois
  intentions est traitée comme une question. Ajouter un service suppose d'ajouter un nœud —
  c'est volontaire, et c'est ce qui rend le comportement testable.
- Les 13 tests de `tests/test_agent_dossier.py` simulent le modèle : ils vérifient le graphe,
  pas la qualité d'Ollama. Deux d'entre eux branchent un modèle qui **échoue si on l'appelle**,
  pour prouver qu'une chronologie et un refus d'accès ne le sollicitent jamais.
- Avec un modèle plus gros, le choix de l'aiguillage par mots-clés resterait pertinent (c'est
  du temps gagné), mais la boucle libre deviendrait envisageable pour les workflows de F9.
