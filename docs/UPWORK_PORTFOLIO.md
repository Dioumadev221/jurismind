# Portfolio entry: JurisMind

Upwork → Profile → Portfolio → **Add project**. Copy each block as is. The Malt version, in
French, is at the end.

This is a demonstration product built on a simulated firm. Present it as your own product,
never as client work.

## Project title

JurisMind: Legal AI Assistant with Verified, Cited Answers (RAG + LangGraph Agents)

## Your role

Founder & AI Engineer: product, RAG and agent architecture, data isolation, backend, UI, deployment

## Project description

JurisMind lets a law firm query its case files through its existing systems (practice database, documents, CRM). Every answer cites its source exhibit and passes five code checks; when the documents do not support an answer, it says it does not know. LangGraph agents summarise matters, brief clients, analyse exhibits and triage mail, and nothing reaches the CRM without a lawyer's approval. PostgreSQL row-level security keeps each lawyer to their own matters. Local models or OpenAI. Built on a simulated firm, no real data.

## Skills

RAG · LangGraph · LangChain · FastAPI · Python · PostgreSQL · pgvector · Ollama · OpenAI API · AI Agent Development

## Media (in this order)

| # | File | Caption |
|---|---|---|
| 1 (cover) | `docs/media/01-accueil.png` | JurisMind: an AI for law firms that cites its sources, or says it does not know |
| 2 | `docs/media/02-reponse.png` | A cited answer: the source exhibit, the quote, and the five checks it passed |
| 3 | `docs/media/03-abstention.png` | A question the documents cannot answer: the system declines instead of guessing |
| 4 | `docs/media/04-dossier.png` | The matter screen: team with access, running deadlines, timeline built from the documents |
| 5 | `docs/media/05-courrier.png` | Incoming mail triaged: matter, priority and draft reply, waiting for a lawyer's approval |
| 6 | `docs/media/06-echeances.png` | Deadlines across all matters, computed from the exhibits |

## Links

- Code, screenshots and documentation: https://github.com/Dioumadev221/jurismind

---

# Version Malt (français)

Malt → Mon profil → **Réalisations** → Ajouter. Même règle : produit de démonstration, pas
une mission client.

## Lien

https://github.com/Dioumadev221/jurismind

## Titre

JurisMind : assistant IA pour cabinet d'avocats, réponses sourcées et vérifiées (RAG + agents)

## Description

JurisMind se branche sur les systèmes qu'un cabinet possède déjà (base de gestion des dossiers, serveur de documents, CRM) et rend vingt ans d'archives interrogeables. Chaque réponse cite la pièce dont elle vient, et cinq contrôles écrits en code décident si elle s'affiche : quand les pièces ne permettent pas de répondre, l'outil le dit. Quatre agents LangGraph résument un dossier, préparent un rendez-vous client, analysent une pièce et trient le courrier entrant ; rien n'atteint le CRM sans la validation d'un avocat. L'isolation par PostgreSQL (RLS) garantit qu'un avocat ne voit que ses dossiers, y compris à travers l'IA. Fonctionne sur un simple PC avec des modèles locaux (Ollama), ou avec OpenAI. Construit sur un cabinet dakarois simulé : 433 pièces générées, aucune donnée réelle.

## Compétences

RAG · LangGraph · LangChain · FastAPI · Python · PostgreSQL · pgvector · Ollama · OpenAI · Agents IA

## Légendes des images (même ordre)

1. JurisMind : une IA de cabinet qui cite ses sources, ou qui dit qu'elle ne sait pas
2. Une réponse sourcée : la pièce, la citation, et les cinq contrôles passés
3. Une question sans réponse dans les pièces : l'outil s'abstient au lieu d'inventer
4. L'écran du dossier : l'équipe qui y a accès, les délais qui courent, la chronologie
5. Le courrier entrant trié : dossier, priorité, brouillon, en attente de validation
6. L'échéancier de tous les dossiers, calculé depuis les pièces
