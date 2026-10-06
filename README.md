# JurisMind

**Système d'automatisation IA pour un cabinet d'avocats** — recherche sémantique, réponses
citées et quatre agents, branchés sur les données que le cabinet possède déjà : sa base
clients, ses dossiers, ses documents, ses échanges et son CRM.

Contexte : droit sénégalais et OHADA, contentieux commercial et droit des affaires. Tout
tourne sur une machine **sans GPU**, avec des modèles locaux (Ollama) ; OpenAI se branche en
changeant une variable d'environnement.

[![Qualité](https://github.com/Dioumadev221/jurismind/actions/workflows/qualite.yml/badge.svg)](https://github.com/Dioumadev221/jurismind/actions/workflows/qualite.yml)

---

## Le problème

Un cabinet a vingt ans d'archives et ne les lit plus. Les questions auxquelles il faut
répondre vite — *« quel délai le débiteur a-t-il pour former opposition ? »*, *« où en est ce
client ? »*, *« ce courrier concerne quel dossier ? »* — ont leur réponse dans les pièces,
mais la retrouver coûte une demi-heure.

Un assistant IA naïf répondrait à ces questions. Il répondrait aussi, avec le même aplomb,
quand la réponse n'est pas dans les pièces. En droit, **une réponse inventée coûte plus cher
que pas de réponse du tout** : un délai faux fait perdre un recours, un montant faux se
retrouve dans un acte de procédure.

Tout ce projet découle de là.

## Trois décisions qui structurent le code

**1. Le code calcule, le modèle rédige.** Une chronologie, un délai qui échoit, un
rattachement d'email : ce sont des faits qu'on déduit de la base par des règles écrites en
Python. Le modèle ne sert qu'à deux choses — comprendre une demande et mettre en forme. Une
date lue en base ne peut pas être inventée.

**2. Rien n'est affiché sans être vérifié.** Une réponse cite ses sources, et le code
vérifie que les sources citées existent, que les chiffres avancés figurent dans les pièces,
que la phrase recopiée s'y retrouve vraiment. Quand une vérification échoue, l'agent
s'abstient — et l'abstention est présentée comme un résultat, pas comme une panne.

**3. Les droits sont appliqués par la base, pas par le code.** L'isolation repose sur le
Row-Level Security de PostgreSQL. L'application se connecte avec un rôle sans privilèges, et
chaque requête s'exécute au nom de l'utilisateur. Un endpoint mal écrit **ne peut pas** faire
fuiter le dossier d'un autre client : la base refuse.

---

## Ce que ça donne

Un courrier mal rangé, que le cabinet avait saisi « DIVERS » :

```
$ uv run python -m jurismind.agents document 48

Mise en demeure adressée à Atlantique Immobilier GIE
Type reconnu : MISE_EN_DEMEURE
  Le cabinet avait saisi : DIVERS — à vérifier.

Cabinet Téranga Avocats met en demeure Atlantique Immobilier GIE de régler une dette
de 91 500 000 FCFA à Baobab Distribution SARL dans un délai de 15 jours.

Ce qui engage :
  - délai — « dans un délai de 15 jours à compter de la réception de la présente. »
  - montant — « de la somme de 91 500 000 FCFA »
```

Chaque point relevé porte **la phrase du document qui le fonde**. Un point dont la citation
ne se retrouve pas dans l'acte est supprimé : c'est ce qui sépare un relevé d'une paraphrase.

Le point sur un client, calculé sans appeler aucun modèle, en moins d'une seconde :

```
$ uv run python -m jurismind.agents client "Sine Services SA" "points d'attention"

Points d'attention :
  [!] Délai de la mise en demeure de 30 jours [D2026-0028] — échoit le 15/10/2026, dans 13 jours
  [!] Dernier échange resté sans réponse [D2026-0024] — reçu il y a 28 jours
  [.] Mandat en cours de négociation — « Recouvrement de portefeuille » (proposition, 13 500 000 FCFA)
```

Chaque alerte remonte à la date, au montant ou au statut qui l'a déclenchée. L'avocat peut
contredire la règle ; il n'a pas à se demander d'où elle sort.

---

## Résultats mesurés

Toutes ces mesures se rejouent en une commande, sur un corpus de 433 documents et 397
échanges. Modèle `qwen2.5:3b`, machine sans GPU.

| Ce qu'on mesure | Résultat | Commande |
|---|---|---|
| Rappel de la recherche (20 questions) | **93,8 %** | `python -m jurismind.evaluation` |
| Abstention correcte quand la réponse n'existe pas | **100 %** | idem |
| Extraction structurée — justesse (98 champs, 30 actes) | **100 %** | `python -m jurismind.evaluation.extraction` |
| … dont scans passés par l'OCR | **100 %** (remplissage 85,7 %) | idem |
| Classement des actes — accord avec la saisie du cabinet | **75,5 %** | `python -m jurismind.evaluation.classement` |
| … réponses hors de la liste des 28 types connus | **0 sur 55** | idem |
| Tests | **323** | `pytest` |

**Ce que ces chiffres ne disent pas.** La justesse des réponses rédigées est de 68,8 % sur
les 20 questions du jeu : le petit modèle se trompe encore dans la formulation. Ce qui est à
100 %, c'est l'abstention — il ne répond pas quand il ne sait pas. Et sur le classement, 4
des 13 désaccords portent sur une distinction qui **n'existe pas dans le document** (qui l'a
produit, pas ce qu'il est) : restent 7 erreurs franches sur 53. Les écarts sont détaillés
dans les ADR.

---

## Les fonctionnalités

| | Demandé | Où c'est |
|---|---|---|
| F1 | Connexion à la base clients et au CRM | `connectors/` — synchronisation idempotente, rapprochement par indices |
| F2 | Pipeline RAG sécurisé | `rag/` — réponses citées, droits appliqués avant la recherche |
| F3 | Recherche sémantique | `retrieval/` — hybride : vecteurs + plein texte français + référence exacte, fusion RRF |
| F4 | Traitement documentaire | `ingestion/` — PDF, DOCX, **OCR français** des scans, découpage par structure |
| F5 | Extraction de données structurées | `extraction/` — 8 schémas Pydantic, validation par un avocat |
| F6 | Agent intelligence client | `agents/client.py` |
| F7 | Agent assistance dossier | `agents/dossier.py` |
| F8 | Agent analyse de documents | `agents/analyse.py` |
| F9 | Agent automatisation de workflows | `agents/tri.py` + `agents/propositions.py` |
| F10 | API REST documentée + démo | `api/` (OpenAPI) et `demo/` (Streamlit) |
| F11 | Fiabilité, minimum d'hallucinations | vérifications et jeux de mesure, voir ci-dessus |
| F12 | Isolation des données | Row-Level Security PostgreSQL, journal d'audit |

En plus de l'offre : **vérification des conflits d'intérêts** (`conformite/`) — un avocat ne peut pas agir contre son propre client, et le conflit se trouve rarement dans ses propres dossiers.

---

## Démarrage

Prérequis : Docker, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com), et
Tesseract avec le pack français pour l'OCR des scans.

```bash
# 1. Base de données et dépendances
docker compose up -d
uv sync
cp .env.example .env

# 2. Modèles locaux
ollama pull qwen2.5:3b && ollama pull qwen2.5 && ollama pull bge-m3

# 3. Le « système existant » du cabinet, reproductible à la graine près
uv run python -m simulation --taille small --seed 42
uv run uvicorn simulation.crm.app:app --port 8100 &

# 4. JurisMind : schéma, reprise des données, lecture des documents
uv run alembic upgrade head
uv run python -m jurismind.connectors
uv run python -m jurismind.ingestion

# 5. Comptes de démonstration (mots de passe écrits dans data/, hors du dépôt)
uv run python -m jurismind.api.comptes --demo

# 6. L'API et la démonstration
uv run uvicorn jurismind.api.main:app --port 8000     # http://localhost:8000/docs
uv run streamlit run src/jurismind/demo/app.py        # http://localhost:8501
```

En ligne de commande, sans interface :

```bash
uv run python -m jurismind.agents dossier D2026-0024 "chronologie"
uv run python -m jurismind.agents client "Sine Services SA"
uv run python -m jurismind.agents document D2026-0024        # liste les pièces
uv run python -m jurismind.agents.courrier trier
uv run python -m jurismind.conformite balayer
```

---

## Architecture

```
Vieux logiciel ─┐
CRM (API)      ─┼─► connectors ─► PostgreSQL + pgvector ◄─ ingestion ◄─ documents (PDF, scans)
Documents      ─┘                   │  RLS : chaque requête au nom d'un utilisateur
                                    ▼
                    retrieval (hybride) ─► rag (citations vérifiées)
                                    │
                                    ▼
                  agents : dossier · client · document · courrier
                                    │
                                    ▼
                    api (FastAPI) ─► demo (Streamlit)
```

Python 3.13, PostgreSQL 16 + pgvector (HNSW, cosinus), SQLAlchemy 2, Alembic, LangGraph,
FastAPI, Streamlit, Ollama ou OpenAI.

Le détail est dans **[docs/conception.md](docs/conception.md)** : acteurs, matrice des
droits, modèle de données, et le plan en dix étapes.

## Décisions d'ingénierie

Chaque décision non évidente a son ADR, avec ce qui a été mesuré et ce qui a été écarté.

| | Décision | Ce qu'elle a réglé |
|---|---|---|
| [0001](docs/adr/0001-connecteur-anticorruption-et-doublons.md) | Connecteur anticorruption, fusion prudente des doublons | trois sociétés « Cissé » différentes fusionnées à tort |
| [0002](docs/adr/0002-rapprochement-crm.md) | Rapprochement CRM par indices ordonnés | un prospect écrasait un client au nom voisin |
| [0003](docs/adr/0003-verification-des-reponses.md) | Vérifier plutôt que faire confiance | le modèle répondait depuis sa culture générale |
| [0004](docs/adr/0004-extraction-structuree.md) | JSON guidé plutôt que génération contrainte | `with_structured_output` perdait les montants |
| [0005](docs/adr/0005-agents-deterministes.md) | Graphes déterministes | une chronologie en < 1 s au lieu de 15 s, et sans invention |
| [0006](docs/adr/0006-points-attention-regles.md) | Points d'attention calculés par des règles | un modèle à qui l'on demande de s'inquiéter s'inquiète toujours |
| [0007](docs/adr/0007-classement-et-releve-des-clauses.md) | Type fermé, clauses citées | 40 documents saisis « DIVERS », et des clauses paraphrasées |
| [0008](docs/adr/0008-validation-humaine-en-base.md) | Validation humaine en base, pas `interrupt()` | la validation arrive le lendemain, par quelqu'un d'autre |
| [0009](docs/adr/0009-conflits-interets.md) | Conflits d'intérêts : signaler trop plutôt que trop peu | le cabinet agit contre une société portant le nom d'un client actuel |

## Ce qui n'est pas fait

Dit franchement, parce qu'un projet de démonstration qui prétend être complet ment :

- **Les appels aux agents sont synchrones** et prennent 20 à 100 s sur CPU. En production ils
  passeraient par la file `taches`, déjà présente dans le modèle de données.
- **JurisMind n'envoie aucun email.** Un brouillon validé est *approuvé pour envoi* ; c'est
  un humain qui l'envoie. C'est une décision, pas un oubli.
- **Le corpus est simulé**, mais il imite un vrai système : identifiants techniques, doublons,
  catégories fausses, scans de mauvaise qualité. Aucune donnée réelle n'est dans le dépôt.
- **Les formules d'appel ne nomment pas l'interlocuteur** : la table `contacts` ne porte pas
  de civilité, et la déduire d'un prénom se trompe une fois sur deux.

## Licence

MIT — voir [LICENSE](LICENSE).
