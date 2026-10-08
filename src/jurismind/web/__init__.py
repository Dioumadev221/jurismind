"""Interface web de JurisMind (F10).

Des fichiers statiques — HTML, CSS, JavaScript simple — servis par l'API elle-même. Pas de
cadriciel ni d'étape de compilation : le projet reste un projet Python, et l'interface tient
dans trois fichiers lisibles d'un bout à l'autre.

Elle ne parle qu'à l'API, avec le jeton de l'utilisateur connecté, jamais à la base. C'est ce
qui rend l'isolation démontrable : deux avocats ouvrent la même page et voient des listes
différentes, parce que c'est PostgreSQL qui tranche.
"""

from pathlib import Path

STATIQUE = Path(__file__).parent / "statique"

__all__ = ["STATIQUE"]
