# JurisMind — image unique, servant l'API, l'interface web et les tâches d'amorçage.
#
# Deux étages. Le premier installe les dépendances à partir du verrou `uv.lock`, donc une
# reconstruction six mois plus tard donne les mêmes versions. Le second ne garde que le
# nécessaire à l'exécution : ni compilateur, ni cache, ni outillage de développement.
#
# Tesseract est installé ici plutôt que laissé à la charge de celui qui déploie. C'est un
# binaire système, pas une dépendance Python : l'oublier ne casse rien au démarrage, mais
# fait échouer la lecture des pièces scannées — soit un tiers du corpus.

# ------------------------------------------------------------------ étage de construction
#
# L'image officielle d'`uv` vit sur ghcr.io, qui n'est pas joignable depuis tous les réseaux
# — on l'a constaté ici même, en échec de poignée de main TLS. On part donc de l'image
# Python de Docker Hub, la même que l'étage d'exécution, et on installe `uv` depuis PyPI :
# deux registres au lieu de trois, et les deux qui répondent partout.
FROM python:3.13-slim-bookworm AS constructeur

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install "uv>=0.12.13,<0.13.0"

WORKDIR /app

# Les dépendances changent bien moins souvent que le code : on les installe d'abord, dans
# leur propre couche, pour qu'une modification du code ne les réinstalle pas.
COPY pyproject.toml uv.lock ./
# `--no-dev` écarte pytest, mypy et ruff, qui n'ont rien à faire dans une image d'exécution.
# `--group simulation` ajoute `reportlab` : le générateur du cabinet est un livrable de cette
# image, puisque l'amorçage de la démonstration s'en sert à sa toute première étape.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev --group simulation

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY simulation/ ./simulation/
# `pyproject.toml` déclare `readme` et `license-files` : sans ces deux fichiers, la
# construction du paquet échoue, et elle échoue tard — après le téléchargement de toutes
# les dépendances.
COPY README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --group simulation

# ------------------------------------------------------------------ étage d'exécution
FROM python:3.13-slim-bookworm AS execution

# `tesseract-ocr-fra` porte le modèle français : sans lui, l'OCR lit du latin approximatif
# sur des actes rédigés en français. `libgl1` et `libglib2.0-0` sont requis par Pillow.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-fra \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# L'application n'a aucune raison de tourner en root : une faille dans une dépendance de
# lecture de documents ne doit pas livrer le conteneur entier.
RUN useradd --create-home --uid 10001 jurismind

WORKDIR /app
COPY --from=constructeur --chown=jurismind:jurismind /app/.venv /app/.venv
COPY --from=constructeur --chown=jurismind:jurismind /app/src /app/src
COPY --from=constructeur --chown=jurismind:jurismind /app/migrations /app/migrations
COPY --from=constructeur --chown=jurismind:jurismind /app/alembic.ini /app/alembic.ini
COPY --from=constructeur --chown=jurismind:jurismind /app/simulation /app/simulation
COPY --chown=jurismind:jurismind docker/amorcer.sh /app/docker/amorcer.sh
RUN chmod +x /app/docker/amorcer.sh \
    && mkdir -p /app/data \
    && chown jurismind:jurismind /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Le paquet Debian place le modèle français ici ; le défaut du projet vise un dossier
    # local qui n'existe pas dans l'image.
    TESSDATA_DIR=/usr/share/tesseract-ocr/5/tessdata

USER jurismind
EXPOSE 8000

# `/sante` répond 200 même quand la base est injoignable — il rend alors « dégradé », par
# choix : un contrôle de santé qui jette une trace n'aide personne. Mais un conteneur sain
# avec une base morte ne sert à rien, donc on lit la réponse au lieu de se contenter du code
# HTTP. C'est la différence entre « le processus tourne » et « le service rend un service ».
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/sante | grep -q '"base":true' || exit 1

CMD ["uvicorn", "jurismind.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
