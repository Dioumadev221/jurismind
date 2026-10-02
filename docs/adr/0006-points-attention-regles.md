# ADR 0006 — Points d'attention : des règles, pas un jugement du modèle

- **Statut** : accepté
- **Date** : 2026-10-02
- **Concerne** : F6 (intelligence client), F9 (workflows)

## Contexte

L'offre demande un agent d'« intelligence client » capable de dégager les *points
d'attention* d'un client. C'est la fonction la plus tentante à confier au modèle : il suffit
de lui donner la fiche et de demander « qu'est-ce qui devrait inquiéter l'avocat ? ».

Essayé, et écarté. Un modèle à qui l'on demande de s'inquiéter s'inquiète toujours : il
produit des formules vraisemblables (« le dossier semble bloqué », « un délai pourrait
courir ») qui ne correspondent à aucune donnée, et qu'aucun avocat ne peut vérifier. Pire,
il passe à côté de ce qui compte réellement, parce que cela demande un calcul — comparer une
date d'acte, un nombre de jours et la date du jour.

## Décision

1. **Chaque point d'attention sort d'une règle appliquée aux données**, écrite en Python
   dans `agents/outils.py`. Aucun n'est produit par un modèle. Cinq règles :

   | Règle | Déclencheur | Gravité |
   |---|---|---|
   | Délai en cours | acte + délai extrait ⇒ échéance dans les 15 jours | haute |
   | Délai échu récemment | échéance dépassée depuis moins de 30 jours | moyenne |
   | Échange sans réponse | dernier échange du dossier entrant depuis ≥ 7 jours | moyenne, haute à 14 |
   | Dossier en sommeil | dossier en cours sans mouvement depuis > 60 jours | moyenne |
   | Valeurs à relire | extraction non validée portant des champs douteux | moyenne |
   | Suivi commercial | opportunité CRM en négociation, relance ouverte | moyenne |

2. **Tout point est remontable à sa cause.** Le libellé porte la date, le montant ou le
   nombre de jours qui l'a déclenché : « Délai de la mise en demeure de 15 jours [D2026-0028]
   — échoit le 05/10/2026, dans 3 jours ». L'avocat peut contredire la règle ; il ne peut pas
   se demander d'où elle sort.
3. **Le silence est une information.** Si aucune règle ne se déclenche, la liste est vide et
   l'agent le dit. On ne la remplit pas pour faire riche. Un délai échu depuis plus de trente
   jours disparaît : une liste encombrée de délais morts n'est plus lue.
4. **Les délais sont reconstitués, pas stockés.** Un acte donne une date et un nombre de
   jours (« sous huitaine », « quinze jours à compter de la signification ») ; l'échéance est
   calculée à la demande à partir de l'extraction de l'étape 6. Elle hérite donc de la
   fiabilité mesurée de cette extraction, et un champ marqué douteux apparaît *aussi* comme
   point d'attention à relire.
5. **La date du jour est un paramètre.** `points_attention(..., aujourdhui=…)`. Une règle qui
   dépend du calendrier doit pouvoir être rejouée à l'identique dans six mois, sinon ses tests
   cassent tout seuls. C'est aussi ce qui permet de se demander « où en était ce client au
   25/08 ? ».
6. **Le modèle ne reçoit pas les points et ne cite aucun chiffre.** Il rédige une prose
   qui situe le client ; le code affiche sous elle la liste des dossiers avec leurs
   enjeux exacts, puis les points d'attention. La prose situe, le code énonce.

## Mesures (corpus du cabinet, 02/10/2026, `qwen2.5:3b`, machine sans GPU)

| Observation | Valeur |
|---|---|
| Délais reconstitués depuis les extractions | 26 |
| Délais dans la fenêtre d'alerte au 02/10/2026 | **1** |
| Points d'attention sur Sine Services SA (3 dossiers, 90,75 M FCFA cumulés) | 4 |
| Fiche complète, aucun appel au modèle | **< 1 s** |
| Synthèse rédigée | 22 à 42 s |
| Synthèses acceptées — modèle chargé des chiffres | 1 sur 3 |
| Synthèses acceptées — chiffres rendus au code | **4 sur 4** |

Lecture : sur 26 délais retrouvés dans les actes, un seul mérite une alerte aujourd'hui
(mise en demeure du 15/09/2026, délai de 30 jours, échoit le 15/10). La règle est
silencieuse la plupart du temps, et c'est ce qui rend son signal crédible.

## Ce que les essais ont appris

Deux défauts observés en faisant rédiger les points par le modèle, et ce qu'on en a fait :

1. **Il rattachait un délai au mauvais dossier** tout en citant le bon nombre de jours.
   Le chiffre passait donc la vérification d'ancrage alors que la phrase était fausse :
   un contrôle sur les chiffres ne contrôle pas une attribution. D'où la séparation.
2. **Il recopiait mal les montants à neuf chiffres** (13 875 000 pour 13 750 000). Le
   contrôle le rattrapait — deux abstentions sur trois — mais une fonction qui s'abstient
   deux fois sur trois n'est pas une fonction. Les chiffres sont revenus au code.

Un troisième écart tenait à la forme et non au fond : à qui l'on demande
`{"synthese": …}`, le modèle répond volontiers `{"synthèse": …}`. Les clés sont désormais
comparées sans accents (`texte_attendu`). On tolère la forme, jamais le fond.

## Conséquences

- Les points d'attention sont **testables** : 14 tests fixent une date, vérifient qu'une
  règle se déclenche, puis qu'elle se tait quand la condition disparaît (une réponse
  envoyée éteint l'alerte d'échange sans réponse, une extraction validée éteint celle de
  relecture, un dossier clos n'est jamais « en sommeil »).
- Les seuils (15, 30, 7, 60 jours) sont des constantes nommées en haut du module : ils
  relèvent de l'organisation du cabinet, pas du code, et se discutent avec lui.
- `chiffres_ancres` répondait « non ancré » à un texte sans aucun chiffre, ce qui est juste
  pour une réponse citée mais faux pour une prose à qui l'on interdit les chiffres. D'où
  `chiffres_douteux`, qui n'exige un ancrage que s'il y a quelque chose à ancrer.
- Limite assumée : une règle ne voit que ce qui est en base. Un délai mentionné dans un
  acte jamais extrait n'apparaît pas — d'où la règle « valeurs à relire », et d'où la
  campagne d'extraction relançable par dossier
  (`python -m jurismind.extraction --dossier D2026-0028`).
- Piste suivante : laisser le cabinet régler ses seuils, et faire de ces points le
  déclencheur des workflows de F9 (une relance proposée pour un courrier sans réponse).
