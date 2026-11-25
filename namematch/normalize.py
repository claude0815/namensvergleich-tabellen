"""Namensnormalisierung – nur für den Vergleich, Originalwerte bleiben unverändert.

Ein Name wird in Tokens zerlegt (klein, ohne Akzente, Umlaute als ae/oe/ue, ß als ss,
ohne Titel) und soweit erkennbar in Vorname und Nachname aufgeteilt.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import KonfigurationsFehler
from .kodierung import zeichensalat_reparieren

# Ersetzungen vor dem Entfernen der Akzente (ä → ae statt ä → a)
_ERSETZUNGEN = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i",
}
_APOSTROPHE = re.compile(r"['’‘`´ʼ]")
_NICHT_ALNUM = re.compile(r"[^0-9a-z]+")
_TITEL_STUECKE = re.compile(r"[^.\-]+\.?")


def falten(text: str) -> str:
    """Vereinheitlicht Schreibweisen: klein, ä→ae, ß→ss, Akzente entfernt, Zeichensalat („Ã¼“) repariert."""
    text = zeichensalat_reparieren(unicodedata.normalize("NFC", text)).casefold()
    text = "".join(_ERSETZUNGEN.get(zeichen, zeichen) for zeichen in text)
    text = unicodedata.normalize("NFKD", text)
    return "".join(zeichen for zeichen in text if not unicodedata.combining(zeichen))


def _tokens(wort: str) -> tuple[str, ...]:
    """Zerlegt ein Wort in Tokens (Bindestriche trennen, Apostrophe verbinden)."""
    wort = _APOSTROPHE.sub("", falten(wort))
    return tuple(t for t in _NICHT_ALNUM.split(wort) if t)


def _als_text(wert: Any) -> str:
    """Wandelt einen Zellwert in Text um (None → leer)."""
    if wert is None:
        return ""
    if isinstance(wert, float) and wert.is_integer():
        return str(int(wert))
    return str(wert)


class Art(StrEnum):
    """Welche Namensinformation vorliegt."""

    VOLL = "voll"              # Vor- und Nachname
    VORNAME = "nur_vorname"
    NACHNAME = "nur_nachname"
    EINZELN = "einzeln"        # ein einzelnes Wort, Rolle unbekannt
    LEER = "leer"


@dataclass(frozen=True)
class Name:
    """Normalisierter Name (nur für den Vergleich)."""

    art: Art
    vorname: tuple[str, ...] = ()
    nachname: tuple[str, ...] = ()      # Kern des Nachnamens ohne Zusätze
    zusaetze: tuple[str, ...] = ()      # von, van, de … (Teil des Nachnamens)
    einzeln: tuple[str, ...] = ()       # Tokens bei Art EINZELN/VORNAME/NACHNAME (ohne Zusätze)
    reihenfolge_sicher: bool = True
    #: alternative Lesart (Vorname, Nachname), wenn die Reihenfolge unsicher ist
    alternativ: tuple[tuple[str, ...], tuple[str, ...]] | None = None

    @property
    def teile(self) -> tuple[str, ...]:
        """Alle Tokens des Namens (ohne Titel)."""
        if self.art is Art.VOLL:
            return self.vorname + self.zusaetze + self.nachname
        return self.zusaetze + self.einzeln

    @property
    def schluessel(self) -> str:
        """Reihenfolgeunabhängiger Schlüssel, z. B. für die Duplikaterkennung."""
        return " ".join(sorted(self.teile))


LEER = Name(Art.LEER)


class Normalisierer:
    """Zerlegt Namen anhand konfigurierbarer Titel- und Zusatzlisten."""

    def __init__(self, titel: Iterable[str], namenszusaetze: Iterable[str]) -> None:
        self._titel = frozenset(falten(t.strip()) for t in titel if t.strip())
        self._zusaetze = frozenset(falten(z.strip()) for z in namenszusaetze if z.strip())

    @classmethod
    def aus_einstellungen(cls, einstellungen: Any) -> Normalisierer:
        """Erzeugt einen Normalisierer aus :class:`~namematch.config.Einstellungen`."""
        return cls(einstellungen.titel, einstellungen.namenszusaetze)

    # --- Hilfsfunktionen ------------------------------------------------------

    def _ist_titel(self, wort: str) -> bool:
        w = falten(wort)
        if w in self._titel:
            return True
        stuecke = _TITEL_STUECKE.findall(w)
        return len(stuecke) > 1 and all(s in self._titel or s.strip("-") in self._titel for s in stuecke)

    def _woerter(self, text: str) -> list[tuple[str, ...]]:
        """Teilt Text in Wörter (je Wort Tokens) und entfernt Titel."""
        roh = [w for w in text.split() if w]
        ohne_titel = [w for w in roh if not self._ist_titel(w)]
        woerter = [_tokens(w) for w in ohne_titel]
        return [w for w in woerter if w]

    def _ist_zusatz(self, wort: tuple[str, ...]) -> bool:
        return len(wort) == 1 and wort[0] in self._zusaetze

    def _nachname_aufteilen(self, woerter: list[tuple[str, ...]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Trennt führende Namenszusätze vom Kern des Nachnamens: (zusaetze, kern)."""
        i = 0
        while i < len(woerter) - 1 and self._ist_zusatz(woerter[i]):
            i += 1
        zusaetze = tuple(t for w in woerter[:i] for t in w)
        kern = tuple(t for w in woerter[i:] for t in w)
        return zusaetze, kern

    def _vor_nach(self, woerter: list[tuple[str, ...]]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """„Vorname(n) [Zusätze] Nachname“ → (vorname, zusaetze, nachname)."""
        start = len(woerter) - 1
        # erster Zusatz ab dem 2. Wort, auf den noch ein Wort folgt, beginnt den Nachnamen
        for i in range(1, len(woerter) - 1):
            if self._ist_zusatz(woerter[i]):
                start = i
                break
        vorname = tuple(t for w in woerter[:start] for t in w)
        zusaetze, kern = self._nachname_aufteilen(woerter[start:])
        return vorname, zusaetze, kern

    # --- öffentliche Varianten -------------------------------------------------

    def voller_name(self, wert: Any) -> Name:
        """Name aus einer Spalte: „Max Mustermann“, „Mustermann, Max“, „Dr. Max Mustermann“, „Anna“."""
        text = _als_text(wert).strip()
        if not text:
            return LEER
        if "," in text:
            vorne, _, hinten = text.partition(",")
            nach_woerter = self._woerter(vorne)
            vor_woerter = self._woerter(hinten.replace(",", " "))
            # Zusätze am Ende des Vornamensteils („Beethoven, Ludwig van“) gehören zum Nachnamen
            while vor_woerter and self._ist_zusatz(vor_woerter[-1]) and len(vor_woerter) > 1:
                nach_woerter.insert(0, vor_woerter.pop())
            vorname = tuple(t for w in vor_woerter for t in w)
            if nach_woerter:
                zusaetze, kern = self._nachname_aufteilen(nach_woerter)
            else:
                zusaetze, kern = (), ()
            return self._zusammensetzen(vorname, zusaetze, kern, sicher=True)
        woerter = self._woerter(text)
        if not woerter:
            return LEER
        if len(woerter) == 1:
            return Name(Art.EINZELN, einzeln=woerter[0])
        vorname, zusaetze, kern = self._vor_nach(woerter)
        # alternative Lesart „Nachname Vorname“ (ohne Komma): erstes Wort ist der Nachname
        alt_nach = woerter[0]
        alt_vor = tuple(t for w in woerter[1:] for t in w)
        return Name(
            Art.VOLL, vorname=vorname, nachname=kern, zusaetze=zusaetze,
            reihenfolge_sicher=False, alternativ=(alt_vor, alt_nach),
        )

    def getrennt(self, vorname: Any, nachname: Any) -> Name:
        """Name aus zwei Spalten (Vorname, Nachname)."""
        vor_woerter = self._woerter(_als_text(vorname))
        nach_woerter = self._woerter(_als_text(nachname))
        vor = tuple(t for w in vor_woerter for t in w)
        zusaetze, kern = self._nachname_aufteilen(nach_woerter) if nach_woerter else ((), ())
        return self._zusammensetzen(vor, zusaetze, kern, sicher=True)

    def nur_vorname(self, wert: Any) -> Name:
        """Datei enthält nur eine Vornamensspalte."""
        return self.getrennt(wert, None)

    def nur_nachname(self, wert: Any) -> Name:
        """Datei enthält nur eine Nachnamensspalte."""
        return self.getrennt(None, wert)

    @staticmethod
    def _zusammensetzen(vorname: tuple[str, ...], zusaetze: tuple[str, ...], kern: tuple[str, ...],
                        sicher: bool) -> Name:
        if vorname and kern:
            return Name(Art.VOLL, vorname=vorname, nachname=kern, zusaetze=zusaetze, reihenfolge_sicher=sicher)
        if vorname:
            return Name(Art.VORNAME, einzeln=vorname)
        if kern:
            return Name(Art.NACHNAME, einzeln=kern, zusaetze=zusaetze)
        return LEER


class Spitznamen:
    """Kurzformen (Alex → Alexander, Alexandra) aus einer lokalen Textdatei."""

    def __init__(self, zuordnung: dict[str, frozenset[str]] | None = None) -> None:
        self._zuordnung = zuordnung or {}

    @classmethod
    def laden(cls, pfad: Path) -> Spitznamen:
        """Liest eine Datei im Format „kurz = lang1, lang2“ (Kommentare mit #)."""
        try:
            text = Path(pfad).read_text(encoding="utf-8")
        except OSError:
            raise KonfigurationsFehler(f"Spitznamen-Datei kann nicht gelesen werden: {pfad}") from None
        zuordnung: dict[str, set[str]] = {}
        for nummer, zeile in enumerate(text.splitlines(), start=1):
            zeile = zeile.split("#", 1)[0].strip()
            if not zeile:
                continue
            kurz, gleich, lang = zeile.partition("=")
            kurz_t = "".join(_tokens(kurz))
            lang_t = ["".join(_tokens(x)) for x in lang.split(",")]
            lang_t = [x for x in lang_t if x]
            if not gleich or not kurz_t or not lang_t:
                raise KonfigurationsFehler(f"Spitznamen-Datei {Path(pfad).name}, Zeile {nummer}: Format „kurz = lang“ erwartet.")
            zuordnung.setdefault(kurz_t, set()).update(lang_t)
        return cls({k: frozenset(v) for k, v in zuordnung.items()})

    def erweiterungen(self, token: str) -> set[str]:
        """Langformen zu einer Kurzform (leer, wenn keine bekannt)."""
        return set(self._zuordnung.get(token, ()))

    def _varianten(self, token: str) -> frozenset[str]:
        return frozenset({token}) | self._zuordnung.get(token, frozenset())

    def gleichwertig(self, a: tuple[str, ...], b: tuple[str, ...]) -> bool:
        """True, wenn sich a und b nur durch Kurzformen unterscheiden (nicht bei völliger Gleichheit)."""
        if a == b or len(a) != len(b) or not self._zuordnung:
            return False
        return all(x == y or (self._varianten(x) & self._varianten(y)) for x, y in zip(a, b))


# --- Zusatzmerkmale -------------------------------------------------------------

_KLASSE_PRAEFIX = re.compile(r"^(klasse|kl)(?=\d)")
_FUEHRENDE_NULLEN = re.compile(r"^0+(?=\d)")


def klasse_normalisieren(wert: Any) -> str | None:
    """„7 b“, „7b“, „07B“, „Klasse 7b“ → „7b“."""
    text = _NICHT_ALNUM.sub("", falten(_als_text(wert)))
    text = _KLASSE_PRAEFIX.sub("", text)
    text = _FUEHRENDE_NULLEN.sub("", text)
    return text or None


_DATUM_MUSTER = (
    (re.compile(r"^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4}|\d{2})(?!\d)"), "tmj"),
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"), "jmt"),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)"), "tmj/"),
    (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})(?!\d)"), "tmj"),
)
_EXCEL_NULLDATUM = dt.date(1899, 12, 30)


def datum_normalisieren(wert: Any) -> dt.date | None:
    """Vereinheitlicht Datumsangaben (Excel-Datum, Seriennummer oder Text) zu einem ``date``."""
    if wert is None or isinstance(wert, bool):
        return None
    if isinstance(wert, dt.datetime):
        return wert.date()
    if isinstance(wert, dt.date):
        return wert
    if isinstance(wert, (int, float)):
        if 1 <= wert < 100000:
            return _EXCEL_NULLDATUM + dt.timedelta(days=int(wert))
        return None
    text = str(wert).strip()
    for muster, ordnung in _DATUM_MUSTER:
        treffer = muster.match(text)
        if not treffer:
            continue
        a, b, c = (int(x) for x in treffer.groups())
        if ordnung == "jmt":
            jahr, monat, tag = a, b, c
        else:
            tag, monat, jahr = a, b, c
            if ordnung == "tmj/" and monat > 12 >= tag:  # amerikanisch mm/dd/yyyy
                tag, monat = monat, tag
        if jahr < 100:
            jahr += 2000 if jahr < 50 else 1900
        try:
            return dt.date(jahr, monat, tag)
        except ValueError:
            return None
    if re.fullmatch(r"\d{4,5}", text):
        return datum_normalisieren(int(text))
    return None


def email_normalisieren(wert: Any) -> str | None:
    """E-Mail-Adressen ohne Leerzeichen, klein, ohne „mailto:“."""
    text = _als_text(wert).strip().casefold()
    if text.startswith("mailto:"):
        text = text[len("mailto:"):]
    return text or None
