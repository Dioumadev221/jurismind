# JurisMind — Dossier de conception

> Statut : **v0.5 — périmètre recentré strictement sur l'offre d'emploi**
> Règle : on développe **ce que l'offre demande, rien de plus**. Tout le reste est en §12 (bonus, plus tard ou jamais).

---

## 0. Décisions prises

| # | Sujet | Décision |
|---|-------|----------|
| D1 | Contexte | Projet phare de portfolio répondant à une offre d'emploi ; cabinet **simulé** |
| D2 | Base clients/dossiers | Base « existante » **simulée** et réaliste (base `legacy`) |
| D3 | CRM | **Simulé** (API REST factice) |
| D4 | LLM | **Ollama** (dev, gratuit, local) **et OpenAI** (cité dans l'offre) — on change de fournisseur par un seul paramètre de configuration |
| D5 | Interface | **API REST** (livrable principal) ; petit écran **Streamlit** uniquement pour la démo |
| D6 | Cadre des données simulées | Cabinet sénégalais, droit OHADA, contentieux + droit des affaires |
| D7 | Machine de dev | CPU seul, 16 Go RAM, Docker installé → petits modèles (voir §8) |

---

## 1. L'offre (source de vérité)

> Un système d'automatisation par IA pour une activité juridique qui a déjà une base de données de clients, dossiers, documents et communications.
> - Utiliser **RAG, LLMs et AI Agents** pour exploiter les données existantes.
> - But : **retrouver l'info pertinente, comprendre le contexte d'un dossier, automatiser des tâches juridiques répétitives.**
> - Connecter l'IA à la **base clients/dossiers + CRM**.
> - Construire un **pipeline RAG sécurisé** pour les documents juridiques et l'historique.
> - Développer des **agents IA** : intelligence client, assistance sur les dossiers, analyse de documents, automatisation de workflows.
> - **Recherche sémantique, traitement documentaire, extraction de données structurées, intégration API.**
> - Exigences : **réponses fiables, isolation des données, minimum d'hallucinations.**
> - Stack : **Python, OpenAI/LLMs, RAG, LangChain/LangGraph, PostgreSQL/pgvector, Vector Search, OCR, REST APIs.**

---

## 2. Ce que fait le projet

Le cabinet possède déjà ses clients, dossiers, documents, communications et un CRM. JurisMind branche une IA sur ces données pour :

1. **retrouver** l'information pertinente ;
2. **comprendre** le contexte d'un dossier ;
3. **automatiser** les tâches juridiques répétitives ;

avec des réponses **fiables**, des données **isolées** et un **minimum d'hallucinations**.

---

## 3. Les acteurs

| Acteur | Ce qu'il fait avec JurisMind |
|--------|------------------------------|
| **Avocat / juriste** | Interroge ses dossiers, fait analyser des documents, consulte la synthèse d'un client, valide ce que l'IA produit |
| **Assistant(e) juridique** | Laisse l'IA trier et rattacher les emails/documents entrants, fait préparer des tâches répétitives (relances, courriers), les valide |
| **Administrateur** | Gère les utilisateurs et leurs droits, lance la synchronisation des sources (base, CRM, documents) |

Règle d'or : **l'IA ne voit que ce que l'utilisateur qui l'interroge a le droit de voir**, et **toute action qui sort du système est validée par un humain**.

---

## 4. Fonctionnalités (= l'offre, point par point)

| # | Demandé dans l'offre | Ce qu'on développe |
|---|----------------------|--------------------|
| **F1** | Connecter l'IA à la base clients/dossiers + CRM | Connecteurs en lecture vers la base existante et l'API du CRM ; synchronisation incrémentale vers JurisMind |
| **F2** | Pipeline RAG sécurisé (documents + historique) | Ingestion des documents **et** des communications ; indexation ; réponses **citées** ; filtrage par droits **avant** la recherche |
| **F3** | Recherche sémantique | Recherche hybride (vecteurs pgvector + plein texte) avec filtres client / dossier / type / date |
| **F4** | Traitement documentaire | Lecture PDF, DOCX, emails, **OCR** des scans ; nettoyage ; découpage ; classification du type de document |
| **F5** | Extraction de données structurées | Parties, dates, montants, juridiction, références, objet, obligations… en JSON validé (Pydantic), chaque valeur avec sa source |
| **F6** | Agent **intelligence client** | Synthèse d'un client : identité, dossiers, historique des échanges, points d'attention (données de la base + CRM + documents) |
| **F7** | Agent **assistance dossier** | Questions-réponses sur un dossier, résumé, chronologie — tout sourcé |
| **F8** | Agent **analyse de documents** | Classification, résumé, extraction (F5), points clés / clauses importantes d'un document |
| **F9** | Agent **automatisation de workflows** | Tri des emails entrants (rattachement au dossier, priorité, résumé), brouillons de réponses/relances, création de tâches dans le CRM — **après validation humaine** |
| **F10** | Intégration API | API REST FastAPI documentée (OpenAPI) exposant F3 à F9 |
| **F11** | Réponses fiables, minimum d'hallucinations | Citations obligatoires et vérifiées, abstention (« je ne trouve pas »), jeu d'évaluation avec métriques publiées |
| **F12** | Isolation des données | Authentification, droits par rôle et par dossier, Row-Level Security PostgreSQL, journal d'audit, tests d'isolation |

Un **routeur** reçoit une demande en langage naturel et l'envoie vers le bon agent (F6 à F9).

---

## 5. Cas d'utilisation principaux

1. **Question sur un dossier** (avocat) — « Le débiteur a-t-il fait opposition ? » → droits vérifiés → recherche dans ce dossier seulement → réponse avec citations, ou « je ne trouve pas ».
2. **Synthèse client** (avocat) — « Fais-moi le point sur Sénégal Distribution » → dossiers, derniers échanges, éléments CRM, points d'attention, tout sourcé.
3. **Analyse d'un document** (avocat, assistant) — dépôt d'un PDF/scan → OCR → type détecté → extraction JSON affichée avec la source de chaque valeur → validation.
4. **Tri d'un email** (assistant) — email entrant → dossier proposé + priorité + résumé + brouillon de réponse → validation ou correction.
5. **Tâche automatique** (assistant, avocat) — l'agent propose « créer une relance dans le CRM » → validation → création via l'API du CRM.

---

## 6. Architecture

```
  Utilisateur ── Streamlit (démo) ──┐
  Autres systèmes ──────────────────┤ HTTP
                        ┌───────────▼─────────────┐
                        │  API REST (FastAPI)     │  auth, droits, audit
                        └───────────┬─────────────┘
                 ┌──────────────────┼──────────────────┐
         ┌───────▼────────┐ ┌───────▼───────┐ ┌────────▼────────┐
         │ Agents         │ │ RAG           │ │ LLMProvider     │
         │ (LangGraph)    │─► recherche +   │─► Ollama | OpenAI │
         │ routeur + 4    │ │ citations     │ └─────────────────┘
         └────────────────┘ └───────┬───────┘
                        ┌───────────▼─────────────┐
                        │ PostgreSQL + pgvector   │  base `jurismind`
                        └───────────▲─────────────┘
                                    │ ingestion : connecteurs → OCR →
                                    │ découpage → embeddings
           ┌────────────────────────┼────────────────────────┐
   Base existante (legacy)     CRM (API)          Documents + emails
```

### 6.1 Stack

| Couche | Choix |
|--------|-------|
| Langage | Python 3.13, `uv` |
| API | FastAPI + Pydantic v2 |
| Agents | LangGraph ; briques LangChain (loaders, splitters, intégrations LLM) |
| LLM | Interface `LLMProvider` : **Ollama** (`langchain-ollama`) et **OpenAI** (`langchain-openai`) |
| Embeddings | Ollama `bge-m3` (1024 dim.) ou OpenAI `text-embedding-3-small` réglé sur 1024 dim. — même colonne `vector(1024)` ; changer de fournisseur impose une ré-indexation |
| Base | PostgreSQL 16 + pgvector (HNSW) + plein texte `french` |
| ORM / migrations | SQLAlchemy 2 + Alembic |
| OCR / PDF | Tesseract (`fra`) + pypdfium2 (licence Apache/BSD, compatible MIT — PyMuPDF est AGPL) |
| Tâches longues | File de tâches dans PostgreSQL (`SELECT … FOR UPDATE SKIP LOCKED`) + worker |
| Démo | Streamlit (appelle l'API, jamais la base) |
| Qualité | ruff, mypy, pytest, GitHub Actions |
| Infra dev | Docker Compose (PostgreSQL) ; Ollama natif Windows |

### 6.2 Structure du projet

```
src/jurismind/
├── api/            # routes FastAPI, authentification
├── core/           # configuration, sécurité, logs
├── db/             # modèles, sessions, RLS, migrations
├── connectors/     # base legacy, CRM, fichiers, emails        (F1)
├── ingestion/      # OCR, nettoyage, découpage, embeddings      (F4)
├── retrieval/      # recherche hybride + filtres de droits      (F3)
├── rag/            # génération citée, vérification, abstention (F2, F11)
├── extraction/     # schémas Pydantic + extraction              (F5)
├── agents/         # routeur + 4 agents LangGraph               (F6-F9)
├── llm/            # LLMProvider : Ollama, OpenAI
├── evaluation/     # jeu de tests + métriques                   (F11)
└── workers/        # worker de la file de tâches
simulation/         # base legacy, CRM factice, générateur de documents
demo/               # application Streamlit
tests/
docs/
```

### 6.3 Pipeline RAG

```
Question + utilisateur + périmètre (client / dossier)
  1. Droits → liste des dossiers autorisés
  2. Recherche vectorielle + plein texte, filtrées par ces dossiers (+ RLS)
  3. Fusion RRF → 4-5 meilleurs extraits
  4. Pertinence insuffisante → abstention
  5. Génération : température 0, sources numérotées, « réponds uniquement
     à partir des sources et cite [n] »
  6. Vérification par le code : chaque citation existe dans les extraits
     récupérés, sinon régénération ou abstention
  7. Réponse + citations → journal d'audit
```

### 6.4 Agents (LangGraph)

- **Outils de lecture** : `search`, `get_client`, `get_matter`, `list_communications`, `get_document`, `extract_structured`, `get_crm_client`.
- **Outils d'écriture** (validation humaine via `interrupt()`) : `create_crm_task`, `save_draft`, `attach_to_matter`.
- Chaque outil reçoit l'utilisateur courant et applique ses droits : l'agent ne peut pas les contourner.
- Graphes **majoritairement déterministes** (fiables avec des petits modèles) ; routeur en sortie JSON contrainte.
- Checkpoints dans PostgreSQL ; garde-fous : nombre d'étapes, délai maximal.

---

## 7. Données

### 7.1 Modèle JurisMind

```
users(id, email, password_hash, role [admin|avocat|assistant], is_active)
clients(id, external_id, name, kind [personne|societe], identifiers jsonb, ...)
matters(id, external_id, client_id, reference, title, kind, status, confidential)
matter_members(matter_id, user_id)                      -- qui voit quel dossier
parties(id, matter_id, name, role)
documents(id, matter_id, external_id, title, doc_type, sha256,
          storage_uri, ocr_applied, created_at)
communications(id, matter_id, client_id, channel, direction,
               sender, recipients, subject, body, sent_at)
chunks(id, matter_id, document_id | communication_id, content,
       page, embedding vector(1024), tsv tsvector, metadata jsonb)
extractions(id, document_id, schema_name, data jsonb, status, validated_by)
conversations / messages(..., citations jsonb)
agent_runs(id, user_id, agent, input, output, status, latency_ms)
pending_actions(id, agent_run_id, action_type, payload, status, decided_by)
jobs(id, kind, payload jsonb, status, attempts, run_after, error)
audit_log(id, user_id, action, resource, details jsonb, at)   -- ajout seul
```

`matter_id` est copié sur `chunks` pour filtrer les droits directement dans la requête vectorielle. `external_id` garde le lien avec la base d'origine (synchronisation idempotente).

### 7.2 Données simulées (`simulation/`)

- **Base legacy** (base PostgreSQL séparée) au schéma « à l'ancienne » : `T_CLIENT`, `T_DOSSIER`, `T_INTERVENANT`, `T_DOCUMENT`, `T_CORRESPONDANCE` ; codes de statut, doublons, champs vides — pour prouver que le connecteur gère des données réelles imparfaites.
- **CRM factice** : API FastAPI (contacts, opportunités, tâches, notes) avec pagination, clé d'API et erreurs occasionnelles.
- **Documents** cohérents avec la base : contrats, statuts, PV d'AG, mises en demeure, requêtes et ordonnances d'injonction de payer, assignations, conclusions, jugements, PV d'huissier, factures ; ~30 % en **scans bruités** (image seule, penchée, tamponnée) pour l'OCR ; emails `.eml`.
- Cadre : cabinet à Dakar, droit OHADA, montants en FCFA, RCCM/NINEA, juridictions sénégalaises.
- Deux tailles : `small` (~80 dossiers, usage quotidien) et `full` (~500 dossiers, à lancer la nuit).
- Les documents sont réalistes dans la forme, **pas juridiquement exacts** : ils servent aux tests.
- Comme les données sont générées, on connaît les bonnes réponses → base du **jeu d'évaluation** (F11).

---

## 8. Contraintes de la machine de dev (CPU, 16 Go)

- Modèle 3-4B pour le routeur, le tri et le chat ; 7B pour l'extraction et les résumés, **en tâche de fond**.
- Choix des modèles par un **banc d'essai** (qualité, respect du JSON, vitesse) à l'étape 3.
- Contexte court (4-5 extraits), résumés et extractions **pré-calculés à l'ingestion**.
- Pas de Redis, pas de re-ranker, un seul modèle chargé à la fois.
- OpenAI reste disponible pour comparer la qualité et pour la démo.

---

## 9. Isolation et sécurité (F12)

1. Droits vérifiés à trois niveaux : **API**, **outils des agents**, **base (RLS)** sur `user_id` ↔ `matter_members`.
2. Filtrage **avant** la recherche : un extrait interdit n'arrive jamais au LLM.
3. Rôles : l'admin gère sans lire le contenu des dossiers ; l'assistant ne voit pas les dossiers marqués confidentiels.
4. Contenu des documents et emails traité comme **données**, jamais comme instructions (injection de prompt) ; écritures uniquement après validation humaine.
5. Accès **en lecture seule** à la base legacy ; secrets dans `.env` ; journal d'audit en ajout seul.
6. Avec Ollama, aucune donnée ne quitte la machine ; avec OpenAI, c'est un choix explicite de configuration.

## 10. Fiabilité et anti-hallucination (F11)

- Réponse uniquement à partir des sources, **citations obligatoires et vérifiées par le code**.
- **Abstention** quand les sources sont insuffisantes.
- Température 0 ; extraction en JSON validé par Pydantic, chaque valeur avec son extrait source.
- Les faits de la base (dates, statuts, montants) sont lus par les outils, pas devinés par le LLM.
- **Évaluation** : ~50 questions avec réponses attendues ; métriques : bonne source retrouvée, fidélité, abstention correcte, justesse de l'extraction ; tests d'isolation et d'injection. Résultats publiés dans le README.

---

## 11. Plan de réalisation

| Étape | Contenu | Fonctionnalités | État |
|-------|---------|-----------------|------|
| 1 | PostgreSQL + pgvector (Docker), configuration | — | ✅ |
| 2a | Système existant simulé : base legacy + CRM factice (API) | — | ✅ |
| 2b | Système existant simulé : fichiers des documents (PDF, DOCX, scans) | — | ✅ |
| 3 | Modèle de données JurisMind, migrations, utilisateurs, droits, RLS, audit + `LLMProvider` Ollama/OpenAI | F12 | |
| 4 | Connecteurs + ingestion (OCR, découpage, embeddings) | F1, F4 | |
| 5 | Recherche hybride + RAG cité + évaluation | F2, F3, F11 | |
| 6 | Extraction structurée + agent analyse de documents | F5, F8 | |
| 7 | Agents assistance dossier + intelligence client + routeur | F6, F7 | |
| 8 | Agent workflows + validation humaine | F9 | |
| 9 | API REST complète + démo Streamlit | F10 | |
| 10 | README, vidéo de démo, CI, ADR, résultats d'évaluation | — | |

Chaque étape : tests verts, commit(s) propres, mise à jour de ce document.

### Qualité du dépôt
README (pitch, démo, architecture, démarrage en une commande, résultats d'évaluation), ADR dans `docs/adr/`, ruff + mypy + pytest, CI GitHub Actions, commits *Conventional Commits*, `.env.example`, licence MIT, aucune donnée réelle ni secret.

---

## 12. Bonus (hors offre — seulement une fois le cœur terminé)

- Vérification des conflits d'intérêts
- Calcul des délais de procédure
- Base de connaissances OHADA (Actes uniformes)
- Rapports hebdomadaires
- Recherche de dossiers similaires, comparaison de versions de contrats
- Multi-cabinets (multi-tenant)
- Interface complète au-delà de la démo
