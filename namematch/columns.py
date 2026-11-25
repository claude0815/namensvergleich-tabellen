"""Erkennung der Namens- und Zusatzspalten anhand typischer Überschriften.

Die Vorschläge werden als Daten zurückgegeben; Kommandozeile bzw. GUI zeigen sie an und
lassen sie vor dem Lauf korrigieren.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .normalize import falten

_NICHT_ALNUM = re.compile(r"[^0-9a-z]+")

# Überschriften (vereinheitlicht: klein, ohne Umlaute/Sonderzeichen)
_VORNAME = {"vorname", "vornamen", "rufname", "firstname", "givenname", "forename", "vorn"}
_NACHNAME = {"nachname", "familienname", "zuname", "lastname", "surname", "familyname", "nachn"}
_KOMBINIERT = {"namevorname", "nachnamevorname", "vornamenachname", "vornamename"}  # beides in einer Spalte
_VOLL = {"name", "namen", "vollername", "namevollstaendig", "fullname", "teilnehmer", "teilnehmerin",
         "teilnehmende", "person", "schueler", "schuelerin", "schuelername", "kind", "mitglied"} | _KOMBINIERT
_KLASSE = {"klasse", "kl", "class", "lerngruppe", "stammgruppe", "stammklasse", "klassenbezeichnung"}
_GEBURTSDATUM = {"geburtsdatum", "gebdatum", "geburtstag", "geb", "gebam", "geboren", "geborenam", "dob",
                 "dateofbirth", "birthdate", "birthday", "geburtsdat"}
_EMAIL = {"email", "mail", "emailadresse", "mailadresse", "emailaddress"}

# Wortteile, die auf Angaben zu anderen Personen oder Dingen hindeuten
_FREMD = ("eltern", "erzieh", "mutter", "vater", "schule", "lehr", "betreu", "kontakt", "notfall",
          "firma", "datei", "ort", "strasse", "kurs", "verein", "sorgeber")


def _schluessel(ueberschrift: str) -> str:
    return _NICHT_ALNUM.sub("", falten(ueberschrift))


def _ist_fremd(schluessel: str) -> bool:
    return any(teil in schluessel for teil in _FREMD)


def _finden(spalten: Sequence[str], begriffe: set[str], belegt: set[str],
            enthalten: tuple[str, ...] = (), ausschluss: set[str] | None = None) -> str | None:
    """Erste Spalte mit exakt passender Überschrift, sonst erste, die einen Begriff enthält/damit beginnt."""
    ausschluss = ausschluss or set()
    schluessel = [(s, _schluessel(s)) for s in spalten if s not in belegt and _schluessel(s) not in ausschluss]
    for spalte, k in schluessel:
        if k in begriffe:
            return spalte
    for spalte, k in schluessel:
        if _ist_fremd(k):
            continue
        if any(k.startswith(b) for b in begriffe if len(b) >= 4) or any(t in k for t in enthalten):
            return spalte
    return None


@dataclass(frozen=True)
class Namensspalten:
    """Wo der Name steht: eine Spalte mit vollem Namen ODER Vorname/Nachname (auch einzeln)."""

    voll: str | None = None
    vorname: str | None = None
    nachname: str | None = None

    def __post_init__(self) -> None:
        if self.voll and (self.vorname or self.nachname):
            raise ValueError("Entweder eine Spalte mit vollem Namen oder Vor-/Nachname-Spalten angeben, nicht beides.")

    @property
    def art(self) -> str:
        """'voll', 'getrennt', 'nur_vorname', 'nur_nachname' oder 'keine'."""
        if self.voll:
            return "voll"
        if self.vorname and self.nachname:
            return "getrennt"
        if self.vorname:
            return "nur_vorname"
        if self.nachname:
            return "nur_nachname"
        return "keine"

    def spalten(self) -> list[str]:
        """Die beteiligten Spaltennamen in Anzeigereihenfolge."""
        return [s for s in (self.voll, self.vorname, self.nachname) if s]

    def beschreibung(self) -> str:
        """Lesbare Beschreibung, z. B. für Protokoll und Kommandozeile."""
        if self.voll:
            return f"voller Name in „{self.voll}“"
        teile = []
        if self.vorname:
            teile.append(f"Vorname in „{self.vorname}“")
        if self.nachname:
            teile.append(f"Nachname in „{self.nachname}“")
        return ", ".join(teile) or "keine Namensspalte"


@dataclass(frozen=True)
class Zusatzspalten:
    """Optionale Zusatzmerkmale einer Datei."""

    klasse: str | None = None
    geburtsdatum: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class Spaltenvorschlag:
    """Vorschlag für eine Datei."""

    namen: Namensspalten
    zusatz: Zusatzspalten


def vorschlagen(spalten: Sequence[str]) -> Spaltenvorschlag:
    """Schlägt Namens- und Zusatzspalten anhand der Überschriften vor."""
    belegt: set[str] = set()
    vorname = _finden(spalten, _VORNAME, belegt, enthalten=("vorname", "firstname", "givenname"),
                      ausschluss=_KOMBINIERT)
    if vorname:
        belegt.add(vorname)
    nachname = _finden(spalten, _NACHNAME, belegt, enthalten=("nachname", "familienname", "lastname", "surname"),
                       ausschluss=_KOMBINIERT)
    if nachname:
        belegt.add(nachname)
    voll = None
    if not (vorname and nachname):
        voll = _finden(spalten, _VOLL, belegt)
        # „Name“ + „Vorname“ → „Name“ ist der Nachname
        if voll and vorname and not nachname and _schluessel(voll) in ("name", "namen"):
            nachname, voll = voll, None
        elif voll and (vorname or nachname):
            # Spalte mit vollem Namen hat Vorrang vor einer einzelnen Teilspalte
            belegt.discard(vorname or "")
            belegt.discard(nachname or "")
            vorname = nachname = None
    if voll:
        belegt.add(voll)
    if nachname:
        belegt.add(nachname)
    namen = Namensspalten(voll=voll, vorname=vorname, nachname=nachname)

    klasse = _finden(spalten, _KLASSE, belegt, enthalten=("klasse",))
    if klasse:
        belegt.add(klasse)
    geburtsdatum = _finden(spalten, _GEBURTSDATUM, belegt, enthalten=("geburtsdat", "gebdat", "birth"))
    if geburtsdatum:
        belegt.add(geburtsdatum)
    email = _finden(spalten, _EMAIL, belegt, enthalten=("email",))
    return Spaltenvorschlag(namen, Zusatzspalten(klasse=klasse, geburtsdatum=geburtsdatum, email=email))
