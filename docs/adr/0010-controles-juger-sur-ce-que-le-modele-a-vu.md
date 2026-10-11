# ADR 0010 — Un contrôle doit juger sur ce que le modèle a vu, et la mesure doit dire pourquoi elle échoue

- **Statut** : accepté
- **Date** : 2026-10-11
- **Concerne** : F11 (réponses fiables), et les indicateurs « taux de réponses correctes » et
  « taux d'hallucination » du cahier des charges

## Contexte

La justesse des réponses stagnait à **68,8 %** pour une cible annoncée à 90 %. Le réflexe
était d'ajouter un *reranker* : c'est ce que recommande l'architecture type, et le cahier des
charges le liste. Ce réflexe était faux, et la mesure le disait déjà.

Le rappel de la recherche est à **93,8 %** : la bonne pièce est retrouvée. Dépenser du temps
de processeur à mieux classer des extraits déjà corrects n'aurait rien donné. En ouvrant le
détail des cinq échecs, on trouve autre chose : **quatre sont des abstentions**, et trois ont
exactement le même verdict.

```
{'sources': True, 'ignorance': True, 'references': False, 'ancrage': True}
```

Le contrôle `references` vérifie que la référence nommée dans la question figure dans la
source citée. Il existe pour une bonne raison, constatée : sans lui, le modèle répond avec le
montant d'une facture voisine. Mais il ne lisait que **le corps** de l'extrait.

Or l'OCR d'un scan abîme d'abord les en-têtes. Dans le corpus, `FACTURE N° FA-2025-994` est
ressorti en `FACTURE N4`. Le numéro ne survit que dans l'intitulé du document — que le modèle
reçoit, puisque `construire_sources()` préfixe chaque extrait de sa référence, mais que le
contrôle ignorait. **Le garde-fou anti-hallucination faisait taire des réponses justes, avec
le montant sous les yeux du modèle.** À lui seul, il causait 19 % d'échec sur les questions
répondables.

Un second défaut s'est révélé en cours de route. Le harnais classait ces cas en « silences
coupables » d'après `source_trouvee` — *le bon document a-t-il été retrouvé ?* Ce n'est pas la
bonne question. Sur 172 documents porteurs d'un montant, **4 ont perdu ce montant à l'OCR**
(4 sur 44 scans ; 0 sur 128 en texte direct). Pour ceux-là, se taire est le comportement
correct, et l'imputer au modèle envoie chercher un défaut de rédaction là où le défaut est
dans la lecture.

Enfin, le harnais n'enregistrait pas **quel** contrôle avait bloqué. Diagnostiquer les trois
cas ci-dessus a demandé d'écrire un script jetable pour une information que la mesure aurait
dû porter.

## Décision

1. **Le contrôle des références juge sur l'intitulé de la pièce autant que sur son corps.**
   C'est exactement la matière fournie au modèle. La protection n'est pas desserrée : une
   facture voisine ne porte pas plus le numéro demandé dans son titre que dans son texte. Les
   deux sens sont verrouillés par un test — le scan abîmé passe, la pièce étrangère est
   toujours refusée — et le test du scan tombe quand on annule le correctif.

   `citation_verifiee()` et `chiffres_ancres()` continuent de ne voir que le corps : un
   chiffre figurant dans un titre ne doit jamais pouvoir ancrer une réponse.

2. **Un refus non reconnu est une faute aussi grave qu'une invention.** La mesure a montré un
   modèle répondant « la question ne peut être répondue avec les informations fournies » —
   un refus parfaitement correct, présenté à l'avocat comme une réponse affirmative faute
   d'être reconnu par `avoue_ignorance()`. Le motif s'accroche désormais au verbe *répondre*,
   jamais au modal seul : « le bail ne peut être résilié » reste une réponse de fond.

3. **La mesure enregistre le verdict de chaque contrôle**, et distingue deux choses que
   `source_trouvee` confondait :

   | Champ | Question posée |
   |---|---|
   | `source_trouvee` | le bon document a-t-il été retrouvé ? |
   | `texte_porteur` | la valeur attendue était-elle **lisible** dans ce qui a été lu ? |

   `silences_coupables` exige maintenant `texte_porteur`.

4. **Deux taux de justesse sont publiés côte à côte, jamais l'un à la place de l'autre.**
   `justesse` reste brute et sévère : c'est ce que vit l'utilisateur, y compris quand l'OCR a
   mangé la réponse. `justesse_sur_texte_lisible` écarte ces cas et le dit. Un chiffre qui
   retire les cas gênants sans l'annoncer n'est pas une mesure, c'est une plaidoirie.

## Conséquences

Sur le jeu de 20 questions, graine 7 : justesse **68,8 % → 87,5 %**, silences coupables
**4 → 1**, citation du bon document **75 % → 80 %**, abstention correcte maintenue à **100 %**.

Deux échecs subsistent, et aucun ne se corrige sans tricher :

- une facture dont le montant n'a pas survécu à l'OCR, où le contrôle `ancrage` refuse ;
- un préavis de résiliation donné à 30 jours au lieu de 90, les quatre contrôles passés. Le
  modèle a confondu le délai de paiement avec le préavis, en citant une source qui contient
  réellement « 30 jours ». C'est la classe la plus difficile : un chiffre faux et pourtant
  ancré. Aucun contrôle syntaxique ne l'attrapera ; il faudrait comparer la nature du délai
  demandé à celle du délai trouvé.

**Ce qu'on ne fait pas.** On ne règle pas le code sur ces deux cas. Seize questions
répondables, c'est 6,25 points par question : ajuster jusqu'à franchir 90 % reviendrait à
ajuster sur le jeu de test, et le chiffre ne vaudrait plus rien. L'écart à la cible se comble
en élargissant le jeu et en traitant les causes, pas les symptômes.

Sur un jeu élargi à 40 questions (graine 11), pour une mesure moins sensible au tirage :
justesse **90,6 %**, justesse sur texte lisible **92,6 %**, rappel 90,6 %, 5 réponses perdues
à l'OCR, 1 silence coupable, 2 inventions.

## Ce que le jeu élargi a révélé, et qu'on ne corrige pas tout de suite

L'abstention correcte tombe à **75 %**. Un seul motif d'échec, présent deux fois : à la
question « Quelle est la capitale du Sénégal ? », le système répond « Dakar », **les quatre
contrôles au vert**.

`chiffres_ancres()` n'y peut rien : une phrase sans chiffre n'est pas ancrable par ce moyen,
et la fonction renvoie `False`. L'ancrage est donc passé par `citation_verifiee()` — le modèle
a bel et bien recopié une phrase existante d'un document réel. Cette phrase ne soutient
simplement pas son affirmation.

**Une citation qui existe n'est pas une citation qui prouve.** Aucun contrôle syntaxique ne
ferme cet écart. Le fermer demande une vérification d'implication — « cette source
soutient-elle cette phrase ? » — donc un second appel au modèle, et un doublement du temps de
réponse sur un poste sans carte graphique. C'est un arbitrage à poser explicitement, pas une
rustine à écrire dans la foulée d'une mesure.

Le jeu de 20 questions donnait 100 % d'abstention correcte. Ce n'était pas un meilleur
système, c'était un tirage plus clément : le trou existait déjà. Publier ce 100 % plutôt que
ce 75 % reviendrait à choisir son échantillon après avoir vu le résultat.

**Ce qui reste ouvert.** Les montants perdus à l'OCR sont un défaut de la chaîne de lecture,
distinct de celui-ci : les tableaux des factures scannées ne survivent pas à Tesseract en mode
texte. C'est un sujet d'ingestion, pas de RAG.
