# ADR 0009 — Conflits d'intérêts : signaler trop plutôt que trop peu, et franchir l'isolation à découvert

- **Statut** : accepté
- **Date** : 2026-10-06
- **Concerne** : bonus §12, F12 (isolation)

## Contexte

Un avocat ne peut pas agir contre son propre client, ni contre un ancien client dans une
affaire liée. Ce n'est pas une bonne pratique, c'est une obligation déontologique : la
sanction est disciplinaire, et le cabinet peut être écarté de l'affaire — après avoir
travaillé dessus.

Un cabinet de cette taille le vérifie de tête. À soixante-neuf dossiers et quarante clients,
de tête ne suffit plus : le conflit se trouve rarement dans ses propres dossiers, il se trouve
dans ceux du confrère d'à côté.

## Décision

1. **On préfère l'excès de signalement.** C'est l'inverse de tout le reste du projet. Pour la
   déduplication des clients (ADR 0001) ou le rattachement d'un email (ADR 0008), un faux
   positif est le danger : on fusionne deux sociétés distinctes, on expose un dossier au
   mauvais avocat. Ici le danger est le **faux négatif** — un conflit manqué est une faute,
   un conflit signalé à tort est une minute de vérification. Le contrôle est donc large, et
   **classe** ce qu'il trouve au lieu de trancher.

2. **Deux axes, et ils sont indépendants.**

   | Axe | Valeurs | Ce qu'il dit |
   |---|---|---|
   | Niveau | `certain` / `a_verifier` | la **certitude de l'identité** |
   | Relation | client actuel / ancien client | la **gravité** du conflit |

   Un nom identique forme juridique comprise, ou une coordonnée partagée, donnent `certain`.
   Une dénomination identique mais une forme différente — « Sahel BTP **SAS** » face au client
   « Sahel BTP **SA** » — donne `a_verifier` : deux sociétés distinctes, ou une saisie
   négligée ? Aucune règle ne peut le dire. Un humain, en ouvrant le RCCM, le peut.

3. **Le contrôle franchit l'isolation, et le dit.** Ces routes sont les seules du projet qui ne
   prennent pas la session soumise au RLS. Si Me Dieng n'interrogeait que ses dossiers, il ne
   verrait pas que le cabinet défend déjà la partie qu'il s'apprête à attaquer — c'est-à-dire
   exactement le cas que le contrôle existe pour trouver. La règle de l'ordre va dans le même
   sens : un cabinet tient un registre des conflits consultable par tous ses avocats.

4. **En contrepartie, il révèle le minimum.** Le résultat nomme le client en cause et dit s'il
   est actuel ou ancien — l'information sans laquelle le contrôle ne sert à rien. Les
   références de dossiers ne sont nommées que si le demandeur y a **déjà** accès ; les autres
   sont **comptées**, pas détaillées : « +2 dossier(s) non visibles ». Rien du contenu ne
   remonte. Et chaque vérification est inscrite au journal d'audit avec son demandeur.

5. **Les mots génériques ne valent rien**, comme ailleurs dans le projet. La comparaison
   retire la forme juridique (`nom_comparable`, ADR 0002) mais exige que le **reste** du nom
   corresponde entièrement. « Dakar Immobilier » ne signale pas « Atlantique Immobilier ».

6. **Une coordonnée partagée vaut mieux qu'un nom.** Deux sociétés peuvent s'appeler pareil ;
   elles partagent rarement une adresse électronique ou un numéro. Un email commun entre une
   partie adverse et un client — ou l'un de ses contacts — donne donc `certain`, même si les
   dénominations diffèrent.

7. **Un administrateur ne lance pas le contrôle.** C'est un acte professionnel d'avocat, et
   l'administrateur n'a aucun dossier dans ce projet.

## Mesures (corpus du cabinet)

| Observation | Valeur |
|---|---|
| Parties adverses examinées | 49 |
| Signalements | **3** |
| … dont `certain` | 0 |
| … dont `a_verifier` | 3 |
| Collisions par coordonnée partagée | 0 |

Les trois signalements se ressemblent : même dénomination, forme juridique différente.

| Dossier | Partie adverse | Client du cabinet | Relation |
|---|---|---|---|
| D2024-0007 | Sahel BTP SAS | Sahel BTP SA | ancien client |
| D2025-0004 | Sahel Agro SUARL | Sahel Agro SAS | ancien client |
| D2026-0012 | Sine Services SARL | SINE SERVICES SA | **client actuel** |

Le troisième est celui qui compte : dans `D2026-0012`, le cabinet agit pour Casamance
Distribution SA **contre** Sine Services SARL, alors que SINE SERVICES SA est un client avec
trois dossiers ouverts. Si c'est la même société, le cabinet est en faute et ne le sait pas.
Le contrôle ne le décide pas — il pose la question au bon moment, avec ce qu'il faut pour y
répondre en deux minutes.

Zéro collision par coordonnée : la règle ne trouve rien sur ce corpus, où les parties adverses
n'ont pas d'email renseigné. Elle est conservée parce que sur des données réelles c'est le
signal le plus fiable, et elle est couverte par les tests.

## Conséquences

- 26 tests, dont les deux qui portent la décision : le contrôle **voit** un dossier fermé au
  demandeur, et il ne le **nomme pas**. Également testés : un confrère ou un huissier portant
  le nom d'un client n'est pas un conflit, et le client du dossier n'est pas en conflit avec
  lui-même.
- Le contrôle est exposé par l'API (`/conformite/*`) et par la démonstration, avec un onglet
  sur chaque dossier et un écran « avant d'accepter une affaire ».
- **Une liste vide n'est pas un quitus.** Elle dit ce qui a été cherché dans les données du
  cabinet, rien de plus. C'est écrit dans l'API et affiché dans la démo.
- Limites assumées, et elles sont réelles : un contrôle fondé sur le nom manque une société
  qui a changé de dénomination, une filiale, une holding, ou une personne physique dirigeant
  deux sociétés. Un registre sérieux demanderait le **RCCM sur les parties** — la table
  `parties` ne le porte pas — et la notion de groupe. À proposer au cabinet.
- Piste suivante : déclencher le contrôle à l'ouverture d'un dossier et à l'ajout d'une partie,
  plutôt qu'à la demande, et refuser l'enregistrement tant qu'un `certain` n'a pas été levé.
