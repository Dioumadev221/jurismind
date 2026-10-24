# Mettre JurisMind en ligne (gratuit)

Hébergement : **Render** (le site et l'API) + **Neon** (la base de données). Les deux sont
gratuits, sans carte bancaire.

Le serveur gratuit n'a pas la mémoire des modèles d'IA (3 Go). La démonstration en ligne
**rejoue des réponses enregistrées sur ton PC**, et calcule tout le reste en direct :
recherche, contrôles, droits d'accès, validation, CRM. Le pourquoi est dans
[l'ADR 0012](adr/0012-demonstration-publique-rejouee.md).

Trois temps : enregistrer sur ton PC (une fois), créer la base sur Neon, créer le site sur
Render.

## Étape 1 : enregistrer la démonstration (sur ton PC, une fois)

Il faut Docker Desktop démarré, et le dépôt à jour (`git pull`).

1. Dans PowerShell, à la racine du dépôt :

   ```powershell
   docker compose up -d --build
   ```

   Au tout premier démarrage, la pile télécharge les modèles et indexe le cabinet : 30 à
   60 minutes. Attends que `docker compose logs -f amorce` affiche la fin de l'amorçage.

2. Lance l'enregistrement :

   ```powershell
   .\docker\enregistrer-demo.ps1
   ```

   Le script joue le scénario avec les vrais modèles (quelques dizaines de minutes sur
   processeur), fige la base, et dépose quatre fichiers dans `demo/`.

3. Ouvre `demo/scenario.json` et regarde la fin : `"bilan"` dit combien de questions ont
   reçu une réponse juste. C'est ce chiffre que la démonstration affichera, tel quel.

4. Envoie les fichiers sur GitHub :

   ```powershell
   git add demo
   git commit -m "feat(demo): enregistrement de la demonstration publique"
   git push
   ```

   Ces fichiers ne contiennent que le cabinet simulé : aucun mot de passe, aucune donnée
   réelle. Le fichier `.env` et `data/` restent sur ton PC.

## Étape 2 : la base de données (Neon)

1. Va sur https://neon.tech et connecte-toi avec GitHub.
2. Clique **New Project**. Nom : `jurismind`. Version de Postgres : **16**. Région :
   **Europe (Frankfurt)**, la même que le site.
3. Sur la page du projet, clique **Connect**.
4. **Décoche** **Connection pooling** (important : la restauration a besoin d'une connexion
   directe).
5. Copie la ligne qui commence par `postgresql://...`. C'est ton `DATABASE_URL`. Garde-la de
   côté.

Rien d'autre à faire sur Neon : le site crée les tables et charge le cabinet tout seul, au
premier démarrage.

## Étape 3 : le site (Render)

1. Va sur https://render.com et connecte-toi avec GitHub.
2. Clique **New → Blueprint**, choisis le dépôt `jurismind`, clique **Connect**.
3. Render lit `render.yaml` et demande deux valeurs :

   | Nom | Valeur |
   |---|---|
   | `DATABASE_URL` | la ligne copiée sur Neon |
   | `CONTACT_URL` | le lien de ton profil Upwork ou Malt |

   Les deux secrets (`API_SECRET`, `POSTGRES_APP_PASSWORD`) sont tirés au hasard par Render :
   n'y touche pas.
4. Clique **Apply** et attends la fin de la construction (5 à 10 minutes la première fois).
5. Render te donne une adresse du type `https://jurismind-xxxx.onrender.com`.

Ton site est en ligne : `/` est la page de présentation, `/app` est l'application, `/docs`
la documentation de l'API.

## Bon à savoir

- **Le site s'endort** après 15 minutes sans visite (plan gratuit de Render). La visite
  suivante le réveille en une minute environ. Avant d'envoyer le lien à un client, ouvre-le
  toi-même une fois.
- **Chaque redémarrage remet la démonstration à zéro** : ce qu'un visiteur a validé ou
  rattaché disparaît, le suivant retrouve le cabinet intact.
- **Une question qui n'a pas été enregistrée** reçoit une phrase qui l'explique, jamais une
  réponse inventée. Les questions préparées sont proposées dans l'écran « Question ».
- **Après une modification des invites du modèle** (dossier `src/jurismind/rag`,
  `agents`, `extraction`), refais l'étape 1 : les anciennes réponses ne correspondent plus.

## En cas de problème

| Ce que tu vois | Ce qu'il faut faire |
|---|---|
| Render : `DATABASE_URL manquante` | La variable n'a pas été collée : **Environment** → ajoute-la → **Save** |
| Render : erreur de connexion à la base | Vérifie que la ligne Neon finit par `?sslmode=require` et que le pooling est décoché |
| Render : `demo/base.sql.gz absent` ou `scenario.json` introuvable | `demo/` n'a pas été envoyé sur GitHub : refais l'étape 1.4, puis **Manual Deploy** sur Render |
