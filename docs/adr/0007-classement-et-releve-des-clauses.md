# ADR 0007 — Analyse d'un document : un type fermé, des clauses citées

- **Statut** : accepté
- **Date** : 2026-10-06
- **Concerne** : F8 (analyse de documents), F5 (extraction), F9 (workflows)

## Contexte

Le cabinet reçoit des pièces dont la nature est saisie à la main dans son vieux logiciel.
Sur les 433 documents repris, **40 sont classés « DIVERS »** et d'autres sont mal rangés :
une facture saisie `DIVERS` dans le dossier vitrine, un procès-verbal de signification
saisi `DIVERS` dans un autre. Or cette catégorie décide du schéma d'extraction (ADR 0004) :
mal rangée, la pièce n'est pas exploitée.

L'offre demande en outre de dégager les « points clés / clauses importantes » d'un document.
C'est la demande la plus dangereuse du lot : une clause pénale ou une clause de juridiction
*résumée* par un modèle n'est plus une clause, c'est une impression.

## Décision

1. **Le type appartient à une liste fermée.** Les 28 types que le cabinet manipule sont
   décrits dans `agents/analyse.py`, chacun avec de quoi le reconnaître. Une réponse hors
   de cette liste est **écartée** et le document reste non classé : le modèle ne crée pas
   de vocabulaire que le reste du système ne saurait pas lire.
2. **La saisie du cabinet n'est jamais écrasée.** Le type reconnu va dans
   `categorie_detectee`, à côté de `categorie_source`. Un désaccord est **signalé** à
   l'avocat (« le cabinet avait saisi : DIVERS — à vérifier »), pas corrigé en silence. Le
   cabinet garde la main sur ses propres données.
3. **Une clause n'est affichée que si elle est dans le document.** Le modèle doit recopier
   la phrase qui porte le point ; `citation_verifiee` (ADR 0003) la confronte au texte, et
   une phrase introuvable fait disparaître le point. C'est ce qui sépare un **relevé** d'une
   paraphrase : ce que l'avocat lit, il peut le retrouver dans l'acte.
4. **Une citation vide n'est pas un rejet.** Le modèle énumère volontiers les natures de
   points qu'on lui a listées en mettant `null` sur celles qu'il ne trouve pas. C'est lui
   qui dit « absent », et il a raison de le dire. Seule une citation *affirmée* mais
   introuvable compte comme un rejet — c'est ce ratio qu'on mesure.
5. **Le résumé ne peut pas avancer un chiffre absent du document** (`chiffres_douteux`).
   S'il est écarté, le reste de l'analyse subsiste : le type et les clauses vérifiées
   restent affichés. Une vérification qui échoue retire une phrase, pas la pièce.
6. **Le classement nourrit l'extraction.** `categorie_detectee` est ce que `schema_pour`
   consulte en premier : la boucle ouverte par l'ADR 0004 (« se fier à la catégorie saisie,
   qui vaut parfois DIVERS ») est refermée.

## Mesures (55 documents, `qwen2.5:3b`, machine sans GPU)

Échantillon de deux documents par catégorie saisie, soit 53 confrontés à la saisie du
cabinet et 2 saisis « DIVERS » (`python -m jurismind.evaluation.classement --par-type 2`).

| Observation | Valeur |
|---|---|
| Accord avec la saisie du cabinet | **40 / 53 (75,5 %)** |
| dont scans passés par l'OCR | 17 / 20 (85,0 %) |
| Réponses hors de la liste des 28 types | **0** |
| Documents « DIVERS » ayant reçu un type exploitable | 2 / 2 |
| Durée par document (en-tête seul) | ~16 s |

**Zéro réponse hors liste sur 55** : la liste fermée tient, et le garde-fou du code n'a
jamais eu à s'exercer. Les scans s'en sortent *mieux* que la moyenne (85 %) — l'OCR dégrade
le corps du texte, pas l'en-tête en capitales qui annonce l'acte.

### Lecture des 13 désaccords

| Saisi → reconnu | Nb | Ce que c'est |
|---|---|---|
| `CONCLUSIONS_ADV` → `CONCLUSIONS` | 2 | **pas une erreur** : « ADV » dit *qui* a déposé |
| `OBSERVATIONS` → `NOTE` | 2 | même cas : la distinction est l'auteur, pas l'acte |
| `ASSIGNATION_REFERE` → `ASSIGNATION` | 2 | bonne famille, sous-type manqué |
| `OPPOSITION` → `ATTESTATION_RCCM` | 2 | erreur franche, sur deux scans courts |
| `NOTE` → `MISE_EN_DEMEURE` | 2 | erreur franche |
| `JUGEMENT` → `ORDONNANCE_IP` | 1 | erreur franche |
| `STATUTS` → `CONTRAT` | 1 | erreur franche |
| `ACTE_CESSION` → `CONCLUSIONS` | 1 | erreur franche |

Quatre désaccords sur treize portent sur une distinction **qui n'est pas dans le
document** : `CONCLUSIONS_ADV` et `OBSERVATIONS` disent qui a produit la pièce, pas ce
qu'elle est. Aucun classement fondé sur le contenu ne peut les trancher — c'est le
`sens` du document et la partie qui le dépose qui le disent. Deux autres manquent un
sous-type en voyant juste la famille. Restent **7 erreurs franches sur 53 (13 %)**.

C'est pour cela que la décision 2 existe : la saisie du cabinet n'est pas écrasée, et
un désaccord est présenté à l'avocat au lieu d'être tranché par la machine.

## Conséquences

- 20 tests fixent les trois garanties, dont deux qui branchent un modèle **qui échoue si on
  l'appelle** : une question sur la pièce ne passe pas par le classement, et une pièce
  invisible n'interroge rien.
- Le relevé est volontairement avare : on préfère deux clauses sûres à six vraisemblables.
  Un acte dont rien ne ressort affiche « rien de relevé », ce qui est une information.
- Limite assumée : le taux d'accord se mesure contre la saisie du cabinet, qui n'est pas une
  vérité. Un désaccord se lit pièce par pièce ; il ne se compte pas automatiquement comme
  une erreur du modèle — c'est même souvent le contraire qui est intéressant.
- Le classement ne lit que les **1 500 premiers caractères** : un acte s'annonce dans son
  en-tête. Une première campagne donnait au modèle jusqu'à 6 000 caractères et mettait
  ~43 s par document (contre ~16 s) ; elle a été interrompue avant la fin, son taux d'accord
  n'a donc pas été mesuré. Le choix de l'en-tête repose sur le raisonnement et sur le gain
  de temps, pas sur une comparaison des deux taux — à faire si le classement devait être
  généralisé à l'ingestion.
- La taxonomie du cabinet mêle deux questions — *quel acte est-ce ?* et *qui l'a produit ?*
  Les types `CONCLUSIONS_ADV` et `OBSERVATIONS` relèvent de la seconde et resteront hors
  de portée d'un classement par le contenu. À proposer au cabinet : les déduire du `sens`
  du document et de la partie déposante, que la base connaît déjà.
- Piste suivante : faire du classement une étape de l'ingestion, pour que toute pièce entrante
  arrive déjà typée, et déclencher l'extraction du bon schéma dans la foulée (F9).
