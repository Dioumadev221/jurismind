"""Connecteurs vers les systèmes existants du cabinet (logiciel de gestion, CRM)."""

from jurismind.connectors.legacy import Bilan, synchroniser

__all__ = ["Bilan", "synchroniser"]
