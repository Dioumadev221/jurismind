-- Exécuté automatiquement au premier démarrage du conteneur (volume vide).

-- Base JurisMind : données de l'application + vecteurs.
\connect jurismind
CREATE EXTENSION IF NOT EXISTS vector;

-- Base « existante » simulée du cabinet (logiciel legacy), séparée de JurisMind.
CREATE DATABASE legacy;
