"""Fehlerklassen mit deutschen, für Anwender verständlichen Meldungen.

Wichtig: Meldungen enthalten niemals Zellinhalte (Namen o. Ä.), höchstens
Dateinamen, Spaltennamen, Zeilennummern und Zahlen.
"""

from __future__ import annotations


class NamematchError(Exception):
    """Erwarteter Fehler mit verständlicher Meldung (wird ohne Traceback angezeigt)."""


class EingabeFehler(NamematchError):
    """Eine Eingabedatei kann nicht gelesen werden."""


class SpaltenFehler(NamematchError):
    """Spaltenwahl fehlt oder ist ungültig."""


class KonfigurationsFehler(NamematchError):
    """Die Einstellungsdatei ist ungültig."""


class AusgabeFehler(NamematchError):
    """Die Ergebnisdatei kann nicht geschrieben werden."""
