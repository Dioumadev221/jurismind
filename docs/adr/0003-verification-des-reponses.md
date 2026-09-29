# ADR 0003 — Vérifier les réponses plutôt que faire confiance au modèle

- **Statut** : accepté
- **Date** : 2026-09-29
- **Concerne** : F2 (RAG), F11 (réponses fiables, minimum d'hallucinations)

## Contexte

Le modèle disponible sur la machine de développement est un `qwen2.5:3b` : 3 milliards de
paramètres, sur processeur, sans carte graphique. Une consigne bien écrite ne suffit pas à
le rendre fiable. Les défauts constatés sur le premier jeu d'évaluation (20 questions) :

| Défaut observé | Exemple |
|---|---|
| Réponse issue de la culture générale, avec une citation de façade | « La capitale du Sénégal est Dakar. » [1] |
| Aveu d'ignorance non reconnu comme tel | « … n'est pas répondu par les documents fournis » |
| Réponse tirée du mauvais document | Montant d'une autre facture que celle demandée |
| Citations oubliées | Bonne réponse, aucune source indiquée |

## Décision

**Le code vérifie, le modèle propose.** Quatre contrôles, appliqués avant d'afficher quoi
que ce soit à un avocat :

1. **Format imposé.** Ollama contraint la sortie en JSON :
   `{"reponse": …, "sources": [1], "citation": "phrase recopiée"}`. Un petit modèle oublie
   les crochets d'une citation libre, mais respecte un schéma.
2. **Numéros de sources vérifiés.** Un numéro qui ne désigne aucune source fournie est
   écarté ; sans source valide restante, la réponse est refusée.
3. **Références croisées.** Si la question porte sur une référence précise (`FA-2023-702`,
   `1703/2022`), cette référence doit figurer dans la source citée. Sinon, le modèle a
   répondu à partir d'un autre document.
4. **Citation littérale.** Le modèle doit recopier la phrase justifiant sa réponse ; on
   vérifie qu'elle se retrouve dans la source citée (à 70 % des mots, pour tolérer une
   reformulation légère). C'est le rempart contre les réponses venues de sa mémoire.

En cas d'échec d'un contrôle, la réponse devient une **abstention** : « Je ne trouve pas
cette information dans les pièces du dossier. »

## Mesures (20 questions, `qwen2.5:3b`, machine sans GPU)

| Indicateur | Avant vérifications | Après |
|---|---|---|
| Rappel de la recherche | 81,2 % | **93,8 %** |
| Justesse des réponses | 81,2 % | 68,8 % |
| Abstention correcte | **0 %** | **100 %** |
| Réponses inventées | 1 | **1** |
| Silences alors que la source était là | 0 | 4 |
| Temps moyen | 40,9 s | 13-31 s |

La justesse baisse parce que le système refuse désormais de répondre quand il ne peut pas
prouver. Le gain de rappel vient d'une troisième piste de recherche, ajoutée après analyse
des échecs : la **référence exacte** (`FA-2025-978`, `1703/2022`), cherchée dans le texte
**et dans le titre** du document — sur un scan, l'OCR détruit parfois le numéro dans le
corps (« FACTURE N4 ») alors que le logiciel du cabinet le conserve.

## Limites assumées

- **Citation d'une pièce voisine** : si le modèle répond juste mais cite la mise en demeure
  au lieu de la facture demandée, la réponse est refusée. Une pièce voisine n'est pas une
  preuve.
- **Scans trop dégradés** : quand l'OCR a détruit le montant lui-même, l'abstention est le
  seul comportement acceptable (constaté sur la facture FA-2023-702).
- Ces deux cas expliquent les silences résiduels. Ils se corrigeront surtout côté OCR et
  avec un modèle plus grand, pas en relâchant les contrôles.

## Conséquences

- Une réponse affichée est **toujours** rattachée à une source qui contient réellement ce
  qu'elle affirme. Un avocat peut cliquer et vérifier.
- Le risque se déplace vers les **silences injustifiés** (le système se tait alors que la
  réponse existait). C'est un compromis assumé en droit : une erreur affirmée coûte plus
  cher qu'une absence de réponse. L'indicateur « silences alors que la source était là »
  suit ce risque.
- Les quatre défauts ci-dessus sont figés par des tests (`tests/test_rag.py`), y compris le
  cas « capitale du Sénégal » et celui de la facture voisine.
- Ces contrôles sont **indépendants du modèle** : ils protègent aussi bien un modèle local
  qu'un modèle OpenAI, et resteront valables quand le matériel permettra un modèle plus gros.
