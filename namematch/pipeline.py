"""Gesamtablauf als Bibliotheksfunktionen – ohne Bildschirmausgabe und ohne Eingaben.

Kommandozeile und GUI sind dünne Schichten darüber:

1. :func:`einlesen` beider Dateien (nur lesend)
2. :func:`spalten_vorschlagen` → Vorschlag anzeigen und ggf. korrigieren lassen
3. :func:`abgleichen` (Normalisieren, Scoring, 1:1-Zuordnung)
4. :func:`ergebnis_schreiben` (neue .xlsx-Datei)

:func:`ausfuehren` erledigt alles in einem Schritt.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import __version__
from .columns import Namensspalten, Zusatzspalten, vorschlagen
from .config import Einstellungen
from .errors import AusgabeFehler, SpaltenFehler
from .io import Einleseoptionen, Tabelle, einlesen, zelltext
from .matcher import Abgleich, Fortschritt, Matcher, Person, Status
from .normalize import (
    Art,
    Normalisierer,
    Spitznamen,
    datum_normalisieren,
    email_normalisieren,
    klasse_normalisieren,
)
from .output import Protokollzeile, schreiben

log = logging.getLogger(__name__)

__all__ = [
    "Einleseoptionen", "Spaltenwahl", "Laufergebnis", "einlesen", "spalten_vorschlagen", "abgleichen",
    "ergebnis_schreiben", "ausfuehren",
]

_TRENNZEICHEN_NAMEN = {";": "Semikolon (;)", ",": "Komma (,)", "\t": "Tabulator", "|": "senkrechter Strich (|)"}
MERKMALE = ("klasse", "geburtsdatum", "email")
_MERKMAL_NAMEN = {"klasse": "Klasse", "geburtsdatum": "Geburtsdatum", "email": "E-Mail"}


@dataclass(frozen=True)
class Spaltenwahl:
    """Namens- und Zusatzspalten beider Dateien."""

    namen_a: Namensspalten
    namen_b: Namensspalten
    zusatz_a: Zusatzspalten = field(default_factory=Zusatzspalten)
    zusatz_b: Zusatzspalten = field(default_factory=Zusatzspalten)

    def merkmale(self) -> dict[str, tuple[str, str]]:
        """Zusatzmerkmale, die in BEIDEN Dateien gewählt sind: Merkmal → (Spalte A, Spalte B)."""
        paare = {}
        for merkmal in MERKMALE:
            a, b = getattr(self.zusatz_a, merkmal), getattr(self.zusatz_b, merkmal)
            if a and b:
                paare[merkmal] = (a, b)
        return paare


@dataclass
class Laufergebnis:
    """Alles, was ein Lauf ergibt (für Ausgabe, Protokoll, GUI)."""

    tab_a: Tabelle
    tab_b: Tabelle
    wahl: Spaltenwahl
    einstellungen: Einstellungen
    abgleich: Abgleich
    personen_a: list[Person]
    personen_b: list[Person]
    duplikate_a: list[list[int]]   # Gruppen von Zeilenpositionen mit gleichem Namen
    duplikate_b: list[list[int]]
    zeitpunkt: dt.datetime
    ausgabe: Path | None = None

    def zaehlung(self) -> dict[Status, int]:
        """Anzahl Zeilen je Status."""
        return self.abgleich.zaehlung()

    def protokoll(self) -> list[Protokollzeile]:
        """Inhalt des Blatts „Protokoll“."""
        return _protokoll(self)


def spalten_vorschlagen(tab_a: Tabelle, tab_b: Tabelle) -> Spaltenwahl:
    """Schlägt Namens- und Zusatzspalten für beide Dateien vor (Daten, keine Ausgabe)."""
    va, vb = vorschlagen(tab_a.spalten), vorschlagen(tab_b.spalten)
    return Spaltenwahl(va.namen, vb.namen, va.zusatz, vb.zusatz)


def spaltenwahl_pruefen(wahl: Spaltenwahl, tab_a: Tabelle, tab_b: Tabelle) -> None:
    """Prüft, ob alle gewählten Spalten existieren und je Datei eine Namensspalte gewählt ist."""
    for kennung, tab, namen, zusatz in (("A", tab_a, wahl.namen_a, wahl.zusatz_a),
                                        ("B", tab_b, wahl.namen_b, wahl.zusatz_b)):
        if namen.art == "keine":
            raise SpaltenFehler(
                f"In Datei {kennung} ({tab.quelle.name}) wurde keine Namensspalte gefunden. Bitte angeben, z. B. mit "
                f"--name-{kennung.lower()} oder --vorname-{kennung.lower()}/--nachname-{kennung.lower()}. "
                f"Vorhandene Spalten: {', '.join(f'„{s}“' for s in tab.spalten)}"
            )
        for spalte in [*namen.spalten(), *(getattr(zusatz, m) for m in MERKMALE)]:
            if spalte and spalte not in tab.spalten:
                raise SpaltenFehler(
                    f"Spalte „{spalte}“ gibt es in Datei {kennung} ({tab.quelle.name}) nicht. "
                    f"Vorhanden: {', '.join(f'„{s}“' for s in tab.spalten)}"
                )


def _personen(tab: Tabelle, namen: Namensspalten, merkmale: dict[str, str], norm: Normalisierer) -> list[Person]:
    """Erzeugt die Vergleichsdaten je Zeile (Originalwerte bleiben in der Tabelle unverändert)."""
    def index(spalte: str | None) -> int | None:
        return tab.spalte(spalte) if spalte else None

    i_voll, i_vor, i_nach = index(namen.voll), index(namen.vorname), index(namen.nachname)
    i_klasse, i_datum, i_mail = (index(merkmale.get(m)) for m in MERKMALE)
    personen: list[Person] = []
    for k, zeile in enumerate(tab.zeilen):
        if i_voll is not None:
            wert = zeile[i_voll]
            name = norm.voller_name(wert)
            anzeige = zelltext(wert).strip()
        else:
            vor = zeile[i_vor] if i_vor is not None else None
            nach = zeile[i_nach] if i_nach is not None else None
            name = norm.getrennt(vor, nach)
            anzeige = " ".join(t for t in (zelltext(vor).strip(), zelltext(nach).strip()) if t)
        klasse_roh = zeile[i_klasse] if i_klasse is not None else None
        personen.append(Person(
            index=k, name=name, anzeige=anzeige, zeile=tab.zeilennummern[k],
            klasse=klasse_normalisieren(klasse_roh), klasse_original=zelltext(klasse_roh).strip() or None,
            geburtsdatum=datum_normalisieren(zeile[i_datum]) if i_datum is not None else None,
            email=email_normalisieren(zeile[i_mail]) if i_mail is not None else None,
        ))
    return personen


def _duplikate(personen: Sequence[Person]) -> list[list[int]]:
    """Gruppen von Zeilen mit nach Normalisierung gleichem Namen (in Dateireihenfolge)."""
    gruppen: dict[str, list[int]] = {}
    for p in personen:
        if p.name.art is not Art.LEER:
            gruppen.setdefault(p.name.schluessel, []).append(p.index)
    return [g for g in gruppen.values() if len(g) > 1]


def abgleichen(tab_a: Tabelle, tab_b: Tabelle, wahl: Spaltenwahl, einstellungen: Einstellungen | None = None,
               fortschritt: Fortschritt | None = None, zeitpunkt: dt.datetime | None = None) -> Laufergebnis:
    """Normalisiert, bewertet und ordnet zu (ohne Dateien zu schreiben)."""
    einstellungen = einstellungen or Einstellungen()
    spaltenwahl_pruefen(wahl, tab_a, tab_b)
    norm = Normalisierer.aus_einstellungen(einstellungen)
    merkmale = wahl.merkmale()
    personen_a = _personen(tab_a, wahl.namen_a, {m: s[0] for m, s in merkmale.items()}, norm)
    personen_b = _personen(tab_b, wahl.namen_b, {m: s[1] for m, s in merkmale.items()}, norm)
    spitznamen = Spitznamen.laden(einstellungen.spitznamen_datei) if einstellungen.spitznamen_aktiv else Spitznamen()
    matcher = Matcher(einstellungen, spitznamen)
    abgleich = matcher.abgleichen(personen_a, personen_b, fortschritt)
    duplikate_a, duplikate_b = _duplikate(personen_a), _duplikate(personen_b)
    log.info("Duplikate: %d Gruppen in A, %d Gruppen in B", len(duplikate_a), len(duplikate_b))
    return Laufergebnis(
        tab_a=tab_a, tab_b=tab_b, wahl=wahl, einstellungen=einstellungen, abgleich=abgleich,
        personen_a=personen_a, personen_b=personen_b, duplikate_a=duplikate_a, duplikate_b=duplikate_b,
        zeitpunkt=zeitpunkt or dt.datetime.now().replace(microsecond=0),
    )


def _gleiche_datei(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists():
            return a.samefile(b)
    except OSError:
        pass
    return a.resolve() == b.resolve()


def ergebnis_schreiben(ergebnis: Laufergebnis, ausgabe: Path | str, ueberschreiben: bool = False) -> Path:
    """Schreibt die Ergebnisdatei. Eingabedateien werden nie überschrieben."""
    ausgabe = Path(ausgabe)
    for kennung, tab in (("A", ergebnis.tab_a), ("B", ergebnis.tab_b)):
        if _gleiche_datei(ausgabe, tab.quelle):
            raise AusgabeFehler(f"Die Ergebnisdatei darf nicht die Eingabedatei {kennung} sein.")
    pfad = schreiben(ausgabe, ergebnis.tab_a, ergebnis.tab_b, ergebnis.abgleich, ergebnis.personen_a,
                     ergebnis.personen_b, ergebnis.protokoll(), ergebnis.einstellungen, ueberschreiben=ueberschreiben)
    ergebnis.ausgabe = pfad
    return pfad


def ausfuehren(datei_a: Path | str, datei_b: Path | str, ausgabe: Path | str | None,
               wahl: Spaltenwahl | None = None, einstellungen: Einstellungen | None = None,
               optionen_a: Einleseoptionen | None = None, optionen_b: Einleseoptionen | None = None,
               fortschritt: Fortschritt | None = None, ueberschreiben: bool = False,
               zeitpunkt: dt.datetime | None = None) -> Laufergebnis:
    """Kompletter Lauf: einlesen, Spalten (Vorschlag oder Vorgabe), abgleichen, schreiben.

    Mit ``ausgabe=None`` wird nichts geschrieben (Probelauf).
    """
    tab_a = einlesen(Path(datei_a), optionen_a)
    tab_b = einlesen(Path(datei_b), optionen_b)
    wahl = wahl or spalten_vorschlagen(tab_a, tab_b)
    ergebnis = abgleichen(tab_a, tab_b, wahl, einstellungen, fortschritt, zeitpunkt)
    if ausgabe is not None:
        ergebnis_schreiben(ergebnis, ausgabe, ueberschreiben)
    return ergebnis


# --- Protokoll ------------------------------------------------------------------------

def _datei_protokoll(kennung: str, tab: Tabelle, namen: Namensspalten) -> list[Protokollzeile]:
    zeilen = [
        Protokollzeile(f"Datei {kennung}", ueberschrift=True),
        Protokollzeile("Pfad", str(tab.quelle.resolve())),
        Protokollzeile("Dateityp", tab.dateityp),
    ]
    if tab.blatt:
        zeilen.append(Protokollzeile("Tabellenblatt", tab.blatt))
    if tab.kodierung:
        zeilen.append(Protokollzeile("Kodierung", tab.kodierung))
    if tab.trennzeichen:
        zeilen.append(Protokollzeile("Trennzeichen", _TRENNZEICHEN_NAMEN.get(tab.trennzeichen, tab.trennzeichen)))
    zeilen += [
        Protokollzeile("Kopfzeile", tab.kopfzeile),
        Protokollzeile("Datenzeilen", len(tab.zeilen)),
        Protokollzeile("Leere Zeilen (ignoriert)", tab.leere_zeilen),
        Protokollzeile("Spalten", len(tab.spalten)),
        Protokollzeile("Namensspalten", namen.beschreibung()),
    ]
    return zeilen


def _protokoll(erg: Laufergebnis) -> list[Protokollzeile]:
    e = erg.einstellungen
    z: list[Protokollzeile] = [
        Protokollzeile("Allgemein", ueberschrift=True),
        Protokollzeile("Tool-Version", f"namematch {__version__}"),
        Protokollzeile("Zeitpunkt", erg.zeitpunkt.isoformat(sep=" ")),
    ]
    z += _datei_protokoll("A", erg.tab_a, erg.wahl.namen_a)
    z += _datei_protokoll("B", erg.tab_b, erg.wahl.namen_b)

    z.append(Protokollzeile("Zusatzmerkmale", ueberschrift=True))
    merkmale = erg.wahl.merkmale()
    for merkmal in MERKMALE:
        if merkmal in merkmale:
            a, b = merkmale[merkmal]
            wert = f"A: „{a}“ ↔ B: „{b}“"
        else:
            vorhanden = [f"{k}: „{s}“" for k, s in (("A", getattr(erg.wahl.zusatz_a, merkmal)),
                                                     ("B", getattr(erg.wahl.zusatz_b, merkmal))) if s]
            wert = "nicht verwendet" + (f" (nur {', '.join(vorhanden)})" if vorhanden else "")
        z.append(Protokollzeile(_MERKMAL_NAMEN[merkmal], wert))

    z += [
        Protokollzeile("Einstellungen", ueberschrift=True),
        Protokollzeile("Schwelle Sicher (ab)", e.schwelle_sicher),
        Protokollzeile("Schwelle Prüfen (ab)", e.schwelle_pruefen),
        Protokollzeile("Mehrdeutig, wenn Abstand kleiner als", e.mehrdeutig_abstand),
        Protokollzeile("Gewichtung Vorname / Nachname", f"{e.gewicht_vorname:g} / {e.gewicht_nachname:g}"),
        Protokollzeile("Deckel bei nur einem Namensteil", e.deckel_teilname),
        Protokollzeile("Bonus Klasse gleich", e.bonus_klasse),
        Protokollzeile("Geburtsdatum gleich / abweichend", f"+{e.bonus_geburtsdatum} / −{e.abzug_geburtsdatum}"),
        Protokollzeile("E-Mail gleich / abweichend", f"+{e.bonus_email} / −{e.abzug_email}"),
        Protokollzeile("Spitznamen-Liste", e.spitznamen_datei.name if e.spitznamen_aktiv else "aus"),
        Protokollzeile("Sortierung", "nach Status" if e.sortierung == "status" else "Reihenfolge von A"),
    ]

    zaehlung = erg.zaehlung()
    z.append(Protokollzeile("Ergebnis", ueberschrift=True))
    for status in Status:
        z.append(Protokollzeile(f"Anzahl „{status.value}“", zaehlung[status]))
    zugeordnet = sum(1 for r in erg.abgleich.zeilen_a if r.b is not None)
    z += [
        Protokollzeile("Zeilen im Ergebnis", len(erg.abgleich.zeilen_a) + len(erg.abgleich.nur_b)),
        Protokollzeile("Davon zugeordnete Paare", zugeordnet),
        Protokollzeile("Genau bewertete Kandidatenpaare", erg.abgleich.anzahl_paare),
    ]

    for kennung, gruppen, tab, personen in (("A", erg.duplikate_a, erg.tab_a, erg.personen_a),
                                            ("B", erg.duplikate_b, erg.tab_b, erg.personen_b)):
        z.append(Protokollzeile(f"Doppelte Namen in Datei {kennung}", ueberschrift=True))
        z.append(Protokollzeile("Anzahl Gruppen", len(gruppen)))
        for gruppe in gruppen:
            nummern = ", ".join(str(tab.zeilennummern[i]) for i in gruppe)
            z.append(Protokollzeile(f"Zeilen {nummern}", personen[gruppe[0]].anzeige))
    return z


def mit_schwellen(einstellungen: Einstellungen, sicher: int | None, pruefen: int | None) -> Einstellungen:
    """Hilfsfunktion: Schwellen überschreiben (z. B. aus Kommandozeile oder Schieberegler)."""
    neu = replace(einstellungen,
                  schwelle_sicher=einstellungen.schwelle_sicher if sicher is None else sicher,
                  schwelle_pruefen=einstellungen.schwelle_pruefen if pruefen is None else pruefen)
    return neu.validieren()
