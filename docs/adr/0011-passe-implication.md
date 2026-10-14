# ADR 0011 — Une citation qui existe n'est pas une citation qui prouve

- **Statut** : accepté
- **Date** : 2026-10-14
- **Concerne** : F11 (réponses fiables) ; indicateurs « taux de réponses correctes » et
  « taux d'hallucination » du cahier des charges

## Contexte

L'ADR 0010 laissait un trou ouvert, et il était mesurable : **abstention correcte à 75 %**.
Un seul motif d'échec, mais présent deux fois dans le jeu de 40 questions. À « quelle est la
capitale du Sénégal ? », le système répond « Dakar » avec les quatre contrôles au vert.

Ce n'est pas une défaillance du modèle. Il a fait ce qu'on lui demandait : il a recopié une
phrase authentique d'un document réel, et `citation_verifiee()` l'a retrouvée mot pour mot.
`chiffres_ancres()` ne pouvait rien opposer — une phrase sans chiffre n'est pas ancrable par
ce moyen, la fonction renvoie `False`, et l'ancrage passe par l'autre branche.

Les quatre contrôles vérifient qu'une citation **existe**. Aucun ne vérifie qu'elle
**soutient** ce qui est affirmé. Entre les deux il y a le sens, et le sens ne se contrôle pas
avec une expression régulière.

## Décision

**Un cinquième contrôle, qui lit.** On pose au modèle une question fermée : *cette source
dit-elle explicitement ce qu'affirme cette phrase ?* La règle qui compte est la troisième de
l'invite — « une affirmation vraie dans la réalité mais absente de la source vaut false ».
C'est elle qui rattrape « Dakar ».

**Il ne s'exerce pas toujours**, et c'est le cœur de la décision. Deux conditions :

1. Les quatre premiers contrôles ont passé. Payer un verdict sur une réponse déjà écartée
   n'apporte rien.
2. Les chiffres de la réponse ne l'ancrent pas déjà dans sa source. Un montant, un délai,
   une date qui concordent lient la réponse à la pièce bien plus solidement qu'un jugement
   de modèle de trois milliards de paramètres — et c'est l'essentiel du trafic d'un cabinet.

Mesuré : **9 réponses sur 40** ont été soumises au juge, et le temps moyen par question passe
de 46,2 s à 50,7 s. Le surcoût est de 10 %, pas de 100 %.

**Le doute compte contre la réponse.** Un verdict illisible, un verdict contradictoire, un
service de modèle injoignable : tous renvoient « non soutenue », donc une abstention. Le coût
d'un silence injustifié est une recherche manuelle ; celui d'une invention affirmée est un
acte mal rédigé. Ces deux coûts ne sont pas du même ordre.

## Conséquences

Sur le jeu de 40 questions (graine 11), avant et après :

| Indicateur | Sans le juge | Avec |
|---|---|---|
| Abstention correcte | 75,0 % | **100 %** |
| Réponses inventées | 2 | **1** |
| Justesse des réponses | 90,6 % | **87,5 %** |
| … sur texte lisible | 92,6 % | 92,6 % |
| Temps moyen | 46,2 s | 50,7 s |

Le juge a tranché neuf fois et eu raison huit fois : deux « Dakar » écartés, une ordonnance
dont le montant n'avait pas survécu à l'OCR écartée à juste titre, cinq réponses légitimes
confirmées. **La neuvième est le prix** : le montant de la facture FA-2025-143 était bien
dans la pièce lue, et le juge l'a fait taire.

**Ce prix est assumé, pas dissimulé.** La justesse brute passe sous la cible de 90 % annoncée
au cahier des charges, et il faut le dire ainsi plutôt que de ne publier que la justesse sur
texte lisible, qui reste à 92,6 %. Le gain est d'une invention en moins et d'un trou
d'abstention fermé. En droit, un montant inventé dans des conclusions coûte plus cher qu'un
« je ne trouve pas » : l'arbitrage est tranché dans ce sens, et il resterait à retrancher si
le produit servait un autre métier.

**Ce qui n'a pas été fait, délibérément.** On ne règle pas le juge sur ce jeu de questions.
Trente-deux questions répondables, c'est 3,1 points par question : ajuster l'invite jusqu'à
récupérer FA-2025-143 reviendrait à ajuster sur le jeu de test, et les deux chiffres ne
vaudraient plus rien. La voie honnête pour remonter la justesse est ailleurs — les cinq
réponses perdues à l'OCR sont un défaut de la chaîne de lecture, pas du RAG.
