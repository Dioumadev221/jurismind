# ADR 0004 — Extraction structurée : JSON guidé plutôt que génération contrainte

- **Statut** : accepté
- **Date** : 2026-09-29
- **Concerne** : F5 (extraction de données structurées), F8 (agent d'analyse de documents)

## Contexte

Le cabinet veut tirer des actes ce qui sert au quotidien : montants, délais, parties,
dates, clauses. Ces valeurs alimenteront ensuite les fiches client et les chronologies.
Une erreur sur un montant ou un délai ne se rattrape pas : elle se retrouve dans un acte
de procédure.

La bibliothèque LangChain propose `with_structured_output`, qui contraint la génération à
un schéma JSON — l'approche recommandée par défaut.

## Décision

1. **JSON guidé, validation par notre code.** La liste des champs et leurs descriptions
   (tirées du schéma Pydantic) sont mises dans la consigne ; le modèle répond en JSON
   libre ; notre code convertit puis valide avec Pydantic.

   *Pourquoi* : mesuré sur les documents du cabinet, `with_structured_output` fait **perdre
   des champs** au modèle local `qwen2.5:7b` — notamment les montants. Le même modèle, avec
   la même invite mais en JSON libre, passe de 4 à 6 champs remplis sur 6 pour une facture.
2. **Conversion tolérante, jamais inventive.** « 13 750 000 FCFA », « 13.750.000 » et
   `13750000` donnent le même entier ; « 09/08/2025 » et « 2025-08-09 » la même date ; une
   valeur illisible devient `null` plutôt qu'une approximation.
3. **Contrôle des chiffres.** Tout montant, délai ou date qui ne se retrouve pas dans le
   texte du document est marqué **champ douteux** : l'avocat sait où regarder.
4. **L'avocat tranche.** Une extraction est une *proposition*. Quand un avocat l'a validée
   (éventuellement corrigée), une nouvelle campagne d'extraction **ne l'écrase pas**.
5. **Modèle « qualité » en tâche de fond.** L'extraction prend ~70 s par acte sur CPU :
   elle ne bloque personne, contrairement au chat.

## Mesures (30 actes, 98 champs, `qwen2.5:7b`, machine sans GPU)

| Source | Taux de remplissage | Justesse |
|---|---|---|
| Documents lus directement (63 champs) | 98,4 % | **100 %** |
| Scans passés par l'OCR (35 champs) | 85,7 % | **100 %** |
| **Ensemble** | **93,9 %** | **100 %** |

Lecture : sur les scans, le modèle **laisse des champs vides** plutôt que de deviner — ce
qui est le comportement voulu. Le coût de l'OCR se voit donc sur le remplissage (−13 points)
et non sur la justesse.

## Conséquences

- Les valeurs extraites peuvent alimenter les agents (fiche client, chronologie) avec un
  niveau de confiance connu et mesuré.
- Le choix de JSON guidé sera à revérifier avec un modèle plus gros ou une autre version
  d'Ollama : c'est une observation, pas une loi. La mesure est rejouable en une commande.
- Piste suivante : classer le document par l'IA (`categorie_detectee`) plutôt que se fier à
  la catégorie saisie par le cabinet, qui vaut parfois « DIVERS ».
