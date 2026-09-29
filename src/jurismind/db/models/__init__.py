from jurismind.db.models.crm import ElementCrm, TypeElementCrm
from jurismind.db.models.documents import (
    Canal,
    Communication,
    Document,
    SensEchange,
    StatutTraitement,
)
from jurismind.db.models.extraction import Extraction, StatutExtraction
from jurismind.db.models.extrait import DIMENSION_VECTEURS, Extrait
from jurismind.db.models.metier import (
    AccesDossier,
    AliasClient,
    Client,
    Contact,
    Dossier,
    Partie,
    QualitePartie,
    StatutDossier,
    TypeClient,
    TypeDossier,
)
from jurismind.db.models.systeme import EntreeAudit, StatutTache, Tache
from jurismind.db.models.utilisateur import Role, Utilisateur

__all__ = [
    "DIMENSION_VECTEURS",
    "AccesDossier",
    "AliasClient",
    "Canal",
    "Client",
    "Communication",
    "Contact",
    "Document",
    "Dossier",
    "ElementCrm",
    "EntreeAudit",
    "Extraction",
    "Extrait",
    "Partie",
    "QualitePartie",
    "Role",
    "SensEchange",
    "StatutDossier",
    "StatutExtraction",
    "StatutTache",
    "StatutTraitement",
    "Tache",
    "TypeClient",
    "TypeDossier",
    "TypeElementCrm",
    "Utilisateur",
]
