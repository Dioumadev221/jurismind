"""Figer la base de la démonstration, et la recharger sur le serveur public.

L'export est un `pg_dump` en SQL simple, sans propriétaires ni droits : chez un hébergeur
(Neon, Render) le rôle propriétaire ne s'appelle pas comme sur la machine de développement,
et les droits du rôle de l'application sont rejoués ici, depuis le code, à l'identique de la
migration qui les a créés.

La restauration est écrite en Python plutôt que confiée à `psql` : l'image n'embarque pas de
client PostgreSQL, et un client de version différente de celle de l'export est une panne qui
n'arrive qu'en production. Le format SQL simple se lit sans peine : des instructions, et des
blocs `COPY … FROM stdin` terminés par `\\.`.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from jurismind.core.config import get_settings
from jurismind.demo import CRM, EXPORT

logger = logging.getLogger(__name__)

# Ce qu'un visiteur peut changer en cliquant : ses décisions, les valeurs qu'il valide, le
# courrier qu'il rattache, et le journal que tout cela alimente. Au démarrage, ces tables
# reviennent à l'état de l'export ; tout le reste n'est que lu.
# Dans l'ordre où l'on peut les recharger sans heurter une clé étrangère.
TABLES_RECHARGEES = ("extractions", "propositions", "taches", "journal_audit")
TABLES_MODIFIABLES = (*TABLES_RECHARGEES, "communications")
SCHEMA_ORIGINE = "demo_origine"


def _dsn_proprietaire() -> str:
    """La chaîne de connexion propriétaire, au format libpq que psycopg et pg_dump attendent."""
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


# ----------------------------------------------------------------------------- export


def exporter(
    destination: Path = EXPORT, conteneur: str = "jurismind-postgres", dsn: str | None = None
) -> Path:
    """`pg_dump` local s'il existe, sinon celui du conteneur Docker de la base."""
    options = ["--no-owner", "--no-privileges", "--format=plain", "--exclude-schema", SCHEMA_ORIGINE]
    if shutil.which("pg_dump"):
        commande = ["pg_dump", *options, dsn or _dsn_proprietaire()]
    else:
        reglages = get_settings()
        commande = [
            "docker", "exec", conteneur, "pg_dump", *options,
            "-U", reglages.postgres_user, reglages.postgres_db,
        ]  # fmt: skip
    logger.info("Export : %s", " ".join(c if "@" not in c else "<dsn>" for c in commande))
    destination.parent.mkdir(parents=True, exist_ok=True)
    resultat = subprocess.run(commande, check=True, capture_output=True)
    with gzip.open(destination, "wb", compresslevel=9) as fichier:
        fichier.write(resultat.stdout)
    # Le CRM simulé garde ses fiches dans un fichier, pas en base : il voyage à côté.
    crm = Path(os.environ.get("CRM_DATA_FILE", "data/crm/crm.json"))
    if crm.exists() and destination == EXPORT:
        shutil.copyfile(crm, CRM)
    return destination


# -------------------------------------------------------------------------- restauration


def _executer_export(connexion: psycopg.Connection, lignes: Iterator[str]) -> None:
    """Joue un export SQL simple : lots d'instructions, et blocs de données COPY en flux.

    Les données passent ligne à ligne, sans être chargées : la table des extraits, avec ses
    vecteurs, pèse des dizaines de mégaoctets, et le serveur gratuit n'en a que 512.
    """
    lot: list[str] = []
    for ligne in lignes:
        if ligne.startswith("COPY ") and ligne.rstrip().endswith("FROM stdin;"):
            if lot:
                connexion.execute("".join(lot).encode())  # plusieurs instructions : protocole simple
                lot = []
            with connexion.cursor().copy(ligne.rstrip().rstrip(";").removesuffix("stdin") + "STDIN") as copie:
                for valeur in lignes:
                    if valeur.rstrip("\r\n") == "\\.":
                        break
                    copie.write(valeur)
        elif ligne.startswith(("\\", "COMMENT ON EXTENSION")):
            # Méta-commandes de psql (\\restrict…), sans objet hors de psql ; et le commentaire
            # d'une extension, qu'un hébergeur réserve au propriétaire de l'extension.
            continue
        else:
            lot.append(ligne)
    if lot:
        connexion.execute("".join(lot).encode())
    # L'export vide le chemin de recherche pour se protéger ; on le rend pour la suite.
    connexion.execute(b"RESET search_path")


def base_chargee(dsn: str | None = None) -> bool:
    with psycopg.connect(dsn or _dsn_proprietaire()) as connexion:
        return connexion.execute(b"SELECT to_regclass('public.dossiers') IS NOT NULL").fetchone() == (True,)


def restaurer(source: Path = EXPORT, dsn: str | None = None) -> None:
    """Charge l'export dans une base vide, puis rend ses droits au rôle de l'application."""
    logger.info("Restauration de %s", source)
    with (
        psycopg.connect(dsn or _dsn_proprietaire()) as connexion,
        gzip.open(source, "rt", encoding="utf-8") as fichier,
    ):
        _executer_export(connexion, iter(fichier))
        accorder_droits(connexion)
        _photographier(connexion)


def accorder_droits(connexion: psycopg.Connection) -> None:
    """Les droits que la migration d'isolation accorde, rejoués sur la base restaurée."""
    reglages = get_settings()
    role = reglages.postgres_app_user
    mot_de_passe = reglages.postgres_app_password.get_secret_value().replace("'", "''")
    connexion.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN PASSWORD '{mot_de_passe}';
            ELSE
                ALTER ROLE {role} LOGIN PASSWORD '{mot_de_passe}';
            END IF;
        END $$;
    """)  # fmt: skip
    for instruction in (
        f"GRANT USAGE ON SCHEMA public TO {role}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
        f"REVOKE UPDATE, DELETE, TRUNCATE ON journal_audit FROM {role}",
    ):
        connexion.execute(instruction.encode())


def _photographier(connexion: psycopg.Connection) -> None:
    """Garde une copie des tables modifiables, dans un schéma que l'application ne lit pas."""
    connexion.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_ORIGINE} CASCADE".encode())
    connexion.execute(f"CREATE SCHEMA {SCHEMA_ORIGINE}".encode())
    for table in TABLES_MODIFIABLES:
        connexion.execute(f"CREATE TABLE {SCHEMA_ORIGINE}.{table} AS TABLE public.{table}".encode())


def reinitialiser(dsn: str | None = None) -> None:
    """Remet les tables modifiables dans l'état de l'export, en une transaction.

    Les tables qu'un visiteur remplit (décisions, valeurs validées, journal) sont vidées puis
    rechargées. Le courrier, lui, est référencé par les extraits de la recherche : on ne le
    supprime pas, on rétablit ses colonnes — un rattachement validé redevient « à trier ».
    """
    with psycopg.connect(dsn or _dsn_proprietaire()) as connexion:
        existe = connexion.execute(
            f"SELECT to_regnamespace('{SCHEMA_ORIGINE}') IS NOT NULL".encode()
        ).fetchone()
        if existe != (True,):
            _photographier(connexion)
            return
        for table in reversed(TABLES_RECHARGEES):
            connexion.execute(f"DELETE FROM public.{table}".encode())
        colonnes = [
            ligne[0]
            for ligne in connexion.execute(
                b"SELECT column_name FROM information_schema.columns "
                b"WHERE table_schema = 'public' AND table_name = 'communications' AND column_name <> 'id'"
            )
        ]
        affectations = ", ".join(f"{colonne} = o.{colonne}" for colonne in colonnes)
        connexion.execute(
            f"UPDATE public.communications c SET {affectations} "
            f"FROM {SCHEMA_ORIGINE}.communications o WHERE c.id = o.id".encode()
        )
        for table in TABLES_RECHARGEES:
            connexion.execute(f"INSERT INTO public.{table} SELECT * FROM {SCHEMA_ORIGINE}.{table}".encode())
            # La séquence repart après la plus grande clé rechargée.
            connexion.execute(
                f"""SELECT setval(pg_get_serial_sequence('public.{table}', 'id'),
                                  coalesce((SELECT max(id) FROM public.{table}), 0) + 1, false)
                    WHERE pg_get_serial_sequence('public.{table}', 'id') IS NOT NULL""".encode()
            )


def preparer() -> None:
    """Au démarrage du serveur public : charger si la base est vide, sinon remettre à zéro."""
    if not base_chargee():
        if not EXPORT.exists():
            raise SystemExit(f"{EXPORT} absent : la démonstration n'a pas été exportée")
        restaurer()
    else:
        reinitialiser()
    logger.info("Base de démonstration prête.")
