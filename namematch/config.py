"""Einstellungen: eingebaute Standardwerte und optionales Laden aus einer TOML-Datei."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .errors import KonfigurationsFehler

#: Titel und Zusätze, die vor dem Vergleich entfernt werden (Vergleich ohne Groß-/Kleinschreibung).
#: Einträge mit Punkt werden nur mit Punkt erkannt („jun.“, nicht „Jun“ – das ist auch ein Vorname).
STANDARD_TITEL: tuple[str, ...] = (
    "dr.", "dr", "prof.", "prof", "herr", "frau", "hr.", "fr.",
    "dipl.", "ing.", "dipl.-ing.", "med.", "rer.", "nat.", "phil.", "mag.",
    "jun.", "sen.", "jr.", "sr.",
)

#: Namenszusätze, die als Teil des Nachnamens gelten (von, van, de …).
STANDARD_NAMENSZUSAETZE: tuple[str, ...] = (
    "von", "van", "de", "der", "den", "del", "della", "di", "da", "du", "dos", "das",
    "la", "le", "ten", "ter", "zu", "vom", "zum", "zur", "y", "bin", "ibn", "al", "el",
)

#: Mitgelieferte Spitznamen-/Kurzformliste.
STANDARD_SPITZNAMEN_DATEI = Path(__file__).parent / "daten" / "spitznamen.txt"

_HEX_FARBE = re.compile(r"^[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class Farben:
    """Hintergrundfarben (RGB-Hex ohne #) für die Zeilen im Ergebnis."""

    sicher: str = "C6EFCE"      # grün
    pruefen: str = "FFEB9C"     # gelb
    mehrdeutig: str = "FFEB9C"  # gelb
    nur_a: str = "FFC7CE"       # rot
    nur_b: str = "D9D9D9"       # grau
    falsch: str = "FF9999"      # kräftiges Rot – Status „Falsch“, von Hand nach der Sichtprüfung gesetzt


@dataclass(frozen=True)
class Einstellungen:
    """Alle einstellbaren Werte mit sinnvollen Standardwerten."""

    # Schwellen
    schwelle_sicher: int = 90
    schwelle_pruefen: int = 70
    mehrdeutig_abstand: int = 5
    # Gewichtung des Namensvergleichs
    gewicht_vorname: float = 0.4
    gewicht_nachname: float = 0.6
    deckel_teilname: int = 80     # nur Vor- ODER Nachname verglichen
    score_namensteil: int = 85    # Doppelname / zweiter Vorname nur auf einer Seite
    score_kurzform: int = 85      # Spitzname/Kurzform (Alex/Alexander)
    # Zusatzmerkmale
    bonus_klasse: int = 5
    bonus_geburtsdatum: int = 10
    abzug_geburtsdatum: int = 10
    bonus_email: int = 10
    abzug_email: int = 10
    min_namensscore_bonus: int = 60  # darunter gibt es keinen Bonus (Zusatzmerkmale erzeugen keinen Treffer)
    # Normalisierung
    titel: tuple[str, ...] = STANDARD_TITEL
    namenszusaetze: tuple[str, ...] = STANDARD_NAMENSZUSAETZE
    spitznamen_aktiv: bool = True
    spitznamen_datei: Path = STANDARD_SPITZNAMEN_DATEI
    # Ausgabe
    farben: Farben = field(default_factory=Farben)
    kandidaten_blatt: bool = True
    sortierung: str = "original"  # "original" oder "status"

    def validieren(self) -> Einstellungen:
        """Prüft die Werte auf Plausibilität und gibt sich selbst zurück."""
        if not 0 <= self.schwelle_pruefen <= self.schwelle_sicher <= 100:
            raise KonfigurationsFehler(
                "Schwellen ungültig: Es muss gelten 0 ≤ Prüfen ≤ Sicher ≤ 100 "
                f"(Prüfen={self.schwelle_pruefen}, Sicher={self.schwelle_sicher})."
            )
        if self.gewicht_vorname < 0 or self.gewicht_nachname < 0 or (
            self.gewicht_vorname + self.gewicht_nachname
        ) <= 0:
            raise KonfigurationsFehler("Gewichte für Vor- und Nachname müssen ≥ 0 sein und dürfen nicht beide 0 sein.")
        for name in ("deckel_teilname", "score_namensteil", "score_kurzform", "min_namensscore_bonus"):
            if not 0 <= getattr(self, name) <= 100:
                raise KonfigurationsFehler(f"Wert „{name}“ muss zwischen 0 und 100 liegen.")
        for name in ("mehrdeutig_abstand", "bonus_klasse", "bonus_geburtsdatum", "abzug_geburtsdatum",
                     "bonus_email", "abzug_email"):
            if not 0 <= getattr(self, name) <= 100:
                raise KonfigurationsFehler(f"Wert „{name}“ muss zwischen 0 und 100 liegen.")
        if self.sortierung not in ("original", "status"):
            raise KonfigurationsFehler("Sortierung muss „original“ oder „status“ sein.")
        for name, wert in vars(self.farben).items():
            if not _HEX_FARBE.match(wert):
                raise KonfigurationsFehler(f"Farbe „{name}“ muss ein 6-stelliger Hex-Wert sein (z. B. C6EFCE).")
        return self


# Zuordnung TOML-Abschnitt.Schlüssel → Feldname in Einstellungen
_TOML_FELDER: dict[str, dict[str, str]] = {
    "schwellen": {
        "sicher": "schwelle_sicher",
        "pruefen": "schwelle_pruefen",
        "mehrdeutig_abstand": "mehrdeutig_abstand",
    },
    "gewichtung": {
        "vorname": "gewicht_vorname",
        "nachname": "gewicht_nachname",
        "deckel_teilname": "deckel_teilname",
        "namensteil": "score_namensteil",
        "kurzform": "score_kurzform",
    },
    "zusatzmerkmale": {
        "bonus_klasse": "bonus_klasse",
        "bonus_geburtsdatum": "bonus_geburtsdatum",
        "abzug_geburtsdatum": "abzug_geburtsdatum",
        "bonus_email": "bonus_email",
        "abzug_email": "abzug_email",
        "min_namensscore": "min_namensscore_bonus",
    },
    "normalisierung": {
        "titel": "titel",
        "namenszusaetze": "namenszusaetze",
        "spitznamen": "spitznamen_aktiv",
        "spitznamen_datei": "spitznamen_datei",
    },
    "ausgabe": {
        "kandidaten": "kandidaten_blatt",
        "sortierung": "sortierung",
    },
}

_GANZZAHL = {"schwelle_sicher", "schwelle_pruefen", "mehrdeutig_abstand", "deckel_teilname", "score_namensteil",
             "score_kurzform", "bonus_klasse", "bonus_geburtsdatum", "abzug_geburtsdatum", "bonus_email",
             "abzug_email", "min_namensscore_bonus"}
_KOMMAZAHL = {"gewicht_vorname", "gewicht_nachname"}
_WAHRHEITSWERT = {"spitznamen_aktiv", "kandidaten_blatt"}
_TEXTLISTE = {"titel", "namenszusaetze"}


def _wert_umwandeln(feld: str, wert: Any, abschnitt: str, schluessel: str, basis: Path) -> Any:
    ort = f"[{abschnitt}] {schluessel}"
    if feld in _GANZZAHL:
        if isinstance(wert, bool) or not isinstance(wert, int):
            raise KonfigurationsFehler(f"{ort}: ganze Zahl erwartet.")
        return wert
    if feld in _KOMMAZAHL:
        if isinstance(wert, bool) or not isinstance(wert, (int, float)):
            raise KonfigurationsFehler(f"{ort}: Zahl erwartet.")
        return float(wert)
    if feld in _WAHRHEITSWERT:
        if not isinstance(wert, bool):
            raise KonfigurationsFehler(f"{ort}: true oder false erwartet.")
        return wert
    if feld in _TEXTLISTE:
        if not isinstance(wert, list) or not all(isinstance(x, str) for x in wert):
            raise KonfigurationsFehler(f"{ort}: Liste von Texten erwartet.")
        return tuple(wert)
    if feld == "spitznamen_datei":
        if not isinstance(wert, str):
            raise KonfigurationsFehler(f"{ort}: Dateipfad als Text erwartet.")
        pfad = Path(wert)
        return pfad if pfad.is_absolute() else (basis / pfad)
    if feld == "sortierung":
        if not isinstance(wert, str):
            raise KonfigurationsFehler(f"{ort}: Text erwartet.")
        return wert
    raise KonfigurationsFehler(f"{ort}: unbekannte Einstellung.")  # pragma: no cover


def laden(pfad: Path | None = None, **ueberschreiben: Any) -> Einstellungen:
    """Lädt Einstellungen aus einer TOML-Datei (optional) und wendet Überschreibungen an.

    Unbekannte Abschnitte oder Schlüssel werden als Fehler gemeldet, damit Tippfehler auffallen.
    """
    werte: dict[str, Any] = {}
    farben: dict[str, str] = {}
    if pfad is not None:
        pfad = Path(pfad)
        try:
            with pfad.open("rb") as datei:
                daten = tomllib.load(datei)
        except FileNotFoundError:
            raise KonfigurationsFehler(f"Einstellungsdatei nicht gefunden: {pfad}") from None
        except tomllib.TOMLDecodeError as fehler:
            raise KonfigurationsFehler(f"Einstellungsdatei {pfad.name} ist kein gültiges TOML: {fehler}") from None
        for abschnitt, inhalt in daten.items():
            if not isinstance(inhalt, dict):
                raise KonfigurationsFehler(f"Unbekannter Eintrag „{abschnitt}“ in {pfad.name}.")
            if abschnitt == "farben":
                for schluessel, wert in inhalt.items():
                    if schluessel not in vars(Farben()):
                        raise KonfigurationsFehler(f"[farben] {schluessel}: unbekannte Farbe.")
                    if not isinstance(wert, str):
                        raise KonfigurationsFehler(f"[farben] {schluessel}: Hex-Wert als Text erwartet.")
                    farben[schluessel] = wert.lstrip("#")
                continue
            felder = _TOML_FELDER.get(abschnitt)
            if felder is None:
                raise KonfigurationsFehler(f"Unbekannter Abschnitt [{abschnitt}] in {pfad.name}.")
            for schluessel, wert in inhalt.items():
                feld = felder.get(schluessel)
                if feld is None:
                    raise KonfigurationsFehler(f"Unbekannte Einstellung [{abschnitt}] {schluessel} in {pfad.name}.")
                werte[feld] = _wert_umwandeln(feld, wert, abschnitt, schluessel, pfad.parent)
    werte.update({k: v for k, v in ueberschreiben.items() if v is not None})
    einstellungen = Einstellungen(**werte)
    if farben:
        einstellungen = replace(einstellungen, farben=replace(einstellungen.farben, **farben))
    return einstellungen.validieren()
