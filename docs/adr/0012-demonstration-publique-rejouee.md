# ADR 0012 — Une démonstration en ligne qui rejoue le modèle, et rien d'autre

- **Statut** : accepté
- **Date** : 2026-10-20
- **Concerne** : la démonstration publique ; aucune fonction du produit

## Contexte

JurisMind se juge en l'utilisant : une question, une réponse citée, une abstention, un
courrier trié, une proposition validée qui part dans le CRM. Une vidéo ne montre pas
l'isolation des données, ni ce qui arrive à une question imprévue.

Mais un hébergement gratuit offre 512 Mo de mémoire et un processeur partagé. `bge-m3` et
`qwen2.5:3b` pèsent 3 Go ; une réponse sur processeur prend 20 à 100 secondes. Faire tourner
les modèles sur le serveur public est impossible, et brancher une API payante ouverte à tout
visiteur expose une facture sans plafond.

## Décision

**Rejouer le modèle, exécuter tout le reste.** Chaque appel au modèle passe par une couche
(`jurismind.llm.rejeu`) qui, à l'enregistrement, consigne la réponse sous l'empreinte de
l'invite exacte — texte, réglages, mode JSON imposé. Sur le serveur public, la même empreinte
retrouve la même réponse. Recherche hybride, contrôles de vérification, isolation par
PostgreSQL, étapes déterministes des agents, validation humaine et écriture dans le CRM
s'exécutent réellement, à chaque visite.

**Une invite jamais vue n'a pas de réponse.** Pas de réponse la plus proche, pas de réponse
générique : `ModeleIndisponible`, que l'API traduit en une phrase (503) disant ce qui
fonctionne sans modèle. Pour la recherche, la voie vectorielle tombe et la voie plein texte
reste : une question imprévue renvoie encore des passages, jamais une réponse rédigée.

**Le scénario est tiré du corrigé, pas choisi.** Les questions viennent du jeu d'évaluation,
dans ses proportions, avec trois questions qui doivent être refusées. Le résultat mesuré à
l'enregistrement est affiché à côté de chaque question, réponses fausses comprises. Choisir
à la main les questions qui réussissent aurait fait une vitrine ; ce serait mentir sur le
taux de réussite.

**Le jour du cabinet est figé** (`DATE_DU_CABINET`). Une échéance « dans 8 jours » calculée
à l'enregistrement doit le rester des mois plus tard ; sinon les invites changent, et plus
rien ne se rejoue.

**Chaque redémarrage efface les visiteurs.** La base est restaurée une fois depuis l'export,
puis les tables qu'un visiteur peut modifier (propositions, extractions, tâches, journal,
rattachements de courrier) sont remises dans l'état de l'export. Sans
`session_replication_role`, que Neon réserve au super-utilisateur : suppressions et
insertions dans l'ordre des clés étrangères.

## Conséquences

- La démonstration ne prouve pas la vitesse du produit : les réponses rejouées sont
  instantanées. La page d'accueil le dit, et donne les temps mesurés sur processeur.
- Toute modification d'une invite invalide l'enregistrement. C'est voulu : une
  démonstration qui rejouerait les réponses d'une autre version du code serait fausse sans
  le savoir. Il faut réenregistrer après chaque changement d'invite.
- L'entrée sans mot de passe n'existe que si `DEMO=true`, et seulement pour les comptes du
  scénario. Le jeton émis est ordinaire : l'isolation s'applique comme à n'importe qui.
- Le rôle de l'application reçoit le mot de passe de l'hébergeur à chaque démarrage. Les
  rôles PostgreSQL sont partagés par tout le serveur : ne jamais faire tourner
  `docker/demo.sh` contre le PostgreSQL de développement.
