"""Excel-Ausgabe: Blätter „Zusammengeführt“, „Protokoll“ und optional „Kandidaten“.

- Jede Zeile aus A und jede Zeile aus B kommt genau einmal vor, alle Spalten bleiben erhalten.
- Werte werden 1:1 übernommen (Excel-Werte mit Typ und Zahlenformat, CSV-Werte als Text).
  Texte, die mit „=“ beginnen, bleiben Text und werden nicht zur Formel.
- Ganze Zeilen werden per bedingter Formatierung nach Match_Status eingefärbt – ändert man den Status
  von Hand (z. B. „Prüfen“ → „Sicher“), ändert sich die Farbe mit. Kopfzeile fixiert, Autofilter.
- openpyxl legt beim Speichern Zwischendateien an. Diese landen in einem versteckten
  Arbeitsordner im Ausgabeordner (nicht im System-Temp) und werden danach gelöscht.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import __version__
from .config import Einstellungen
from .errors import AusgabeFehler
from .io import Tabelle, zelltext
from .matcher import Abgleich, Person, Status, Zeilenergebnis

log = logging.getLogger(__name__)

BLATT_ERGEBNIS = "Zusammengeführt"
BLATT_PROTOKOLL = "Protokoll"
BLATT_KANDIDATEN = "Kandidaten"
MATCH_SPALTEN = ["Match_Status", "Match_Score", "Match_Hinweis"]
MAX_ZELLTEXT = 32767  # Grenze von Excel

_STATUS_RANG = {Status.MEHRDEUTIG: 0, Status.PRUEFEN: 1, Status.NUR_A: 2, Status.SICHER: 3, Status.NUR_B: 4}
_TEMP_SPERRE = threading.Lock()


@dataclass(frozen=True)
class Protokollzeile:
    """Eine Zeile im Blatt „Protokoll“."""

    eintrag: str
    wert: Any = None
    ueberschrift: bool = False


def ergebniszeilen(abgleich: Abgleich, sortierung: str = "original") -> list[Zeilenergebnis]:
    """Reihenfolge der Ergebniszeilen: A-Reihenfolge (oder nach Status), „Nur in B“ immer am Ende."""
    zeilen = list(abgleich.zeilen_a)
    if sortierung == "status":
        zeilen.sort(key=lambda z: _STATUS_RANG[z.status])  # stabil: innerhalb des Status A-Reihenfolge
    return zeilen + list(abgleich.nur_b)


class _Zellen:
    """Erzeugt Zellen für den Schreibmodus und zählt bereinigte Werte."""

    def __init__(self, blatt: Any) -> None:
        self.blatt = blatt
        self.bereinigt = 0
        self.gekuerzt = 0

    def zelle(self, wert: Any, fuellung: PatternFill | None = None, format_: str | None = None,
              fett: bool = False, formel: bool = False) -> WriteOnlyCell:
        """Zelle mit Originalwert. ``formel=True`` nur für vom Tool selbst erzeugte Formeln."""
        if formel:
            return WriteOnlyCell(self.blatt, value=wert)
        if isinstance(wert, str):
            if wert == "":
                wert = None
            else:
                sauber = ILLEGAL_CHARACTERS_RE.sub("", wert)
                if sauber != wert:
                    self.bereinigt += 1
                if len(sauber) > MAX_ZELLTEXT:
                    sauber = sauber[:MAX_ZELLTEXT]
                    self.gekuerzt += 1
                wert = sauber
        zelle = WriteOnlyCell(self.blatt, value=wert)
        if isinstance(wert, str) and wert.startswith("="):
            zelle.data_type = "s"  # Text bleibt Text (keine Formel, kein Formel-Einschleusen)
        if format_ and not isinstance(wert, str) and wert is not None:
            zelle.number_format = format_
        if fuellung is not None:
            zelle.fill = fuellung
        if fett:
            zelle.font = Font(bold=True)
        return zelle


def _breiten(kopf: list[str], zeilen: Sequence[Sequence[Any]], maximal: int = 50) -> list[float]:
    """Spaltenbreiten aus Überschrift und den ersten 500 Zeilen."""
    breiten = [len(k) + 2 for k in kopf]
    for zeile in zeilen[:500]:
        for k, wert in enumerate(zeile):
            if wert is None:
                continue
            laenge = 10 if isinstance(wert, (dt.date, dt.datetime)) else len(zelltext(wert))
            breiten[k] = max(breiten[k], laenge + 2)
    return [float(min(max(b, 8), maximal)) for b in breiten]


def _kopf_und_layout(blatt: Any, kopf: list[str], werte: Sequence[Sequence[Any]], hinweis_spalte: int | None,
                     anzahl_zeilen: int) -> None:
    blatt.freeze_panes = "A2"
    letzte = get_column_letter(max(1, len(kopf)))
    blatt.auto_filter.ref = f"A1:{letzte}{anzahl_zeilen + 1}"
    for k, breite in enumerate(_breiten(kopf, werte), start=1):
        if hinweis_spalte is not None and k == hinweis_spalte:
            breite = max(breite, 30.0)
        blatt.column_dimensions[get_column_letter(k)].width = breite


@contextmanager
def _arbeitsordner(ordner: Path) -> Iterator[Path]:
    """Leitet temporäre Dateien (openpyxl) in einen versteckten Ordner im Ausgabeordner um."""
    with _TEMP_SPERRE:
        arbeit = Path(tempfile.mkdtemp(prefix=".namematch-", dir=ordner))
        vorher = tempfile.tempdir
        tempfile.tempdir = str(arbeit)
        try:
            yield arbeit
        finally:
            tempfile.tempdir = vorher
            shutil.rmtree(arbeit, ignore_errors=True)


def _fuellung(hex_: str) -> PatternFill:
    """Füllung für die bedingte Formatierung (Vorder- und Hintergrundfarbe gleich, für Excel und LibreOffice)."""
    return PatternFill(fill_type="solid", start_color=hex_.upper(), end_color=hex_.upper())


#: Schreibweisen je Status, auf die die bedingte Formatierung reagiert (Groß-/Kleinschreibung egal)
#: (Anzeige, Schreibweisen, Farbe aus Einstellungen.farben). „Falsch“ setzt nur der Mensch nach der Sichtprüfung.
STATUS_FALSCH = "Falsch"
_MARKIERUNGEN: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (Status.SICHER.value, ("Sicher",), "sicher"),
    (Status.PRUEFEN.value, ("Prüfen", "Pruefen"), "pruefen"),
    (Status.MEHRDEUTIG.value, ("Mehrdeutig",), "mehrdeutig"),
    (Status.NUR_A.value, ("Nur in A",), "nur_a"),
    (Status.NUR_B.value, ("Nur in B",), "nur_b"),
    (STATUS_FALSCH, ("Falsch",), "falsch"),
)


def _bedingte_formatierung(blatt: Any, spalten: int, zeilen: int, einstellungen: Einstellungen) -> None:
    """Färbt ganze Zeilen nach dem Wert in Spalte A (Match_Status) – auch nach Änderungen von Hand.

    Wird z. B. „Prüfen“ nach der Sichtprüfung durch „Sicher“ (oder „sicher“) ersetzt, wird die
    Zeile automatisch grün. Dazu gibt es in Spalte A eine Auswahlliste (andere Eingaben bleiben erlaubt).
    """
    if zeilen == 0:
        return
    bereich = f"A2:{get_column_letter(spalten)}{zeilen + 1}"
    for _anzeige, schreibweisen, farbe in _MARKIERUNGEN:
        vergleiche = [f'TRIM($A2)="{text}"' for text in schreibweisen]
        formel = vergleiche[0] if len(vergleiche) == 1 else f"OR({','.join(vergleiche)})"
        fuellung = _fuellung(getattr(einstellungen.farben, farbe))
        blatt.conditional_formatting.add(bereich, FormulaRule(formula=[formel], fill=fuellung, stopIfTrue=True))
    auswahl = DataValidation(type="list", formula1='"' + ",".join(m[0] for m in _MARKIERUNGEN) + '"',
                             allow_blank=True, showErrorMessage=False)
    auswahl.add(f"A2:A{zeilen + 1}")
    blatt.data_validations.append(auswahl)


def _blatt_ergebnis(mappe: Any, tab_a: Tabelle, tab_b: Tabelle, zeilen: list[Zeilenergebnis],
                    einstellungen: Einstellungen) -> _Zellen:
    blatt = mappe.create_sheet(BLATT_ERGEBNIS)
    kopf = MATCH_SPALTEN + [f"A_{s}" for s in tab_a.spalten] + [f"B_{s}" for s in tab_b.spalten]
    leer_a, leer_b = [None] * len(tab_a.spalten), [None] * len(tab_b.spalten)
    werte: list[list[Any]] = []
    for z in zeilen:
        a = tab_a.zeilen[z.a] if z.a is not None else leer_a
        b = tab_b.zeilen[z.b] if z.b is not None else leer_b
        werte.append([z.status.value, z.score, "; ".join(z.hinweise) or None, *a, *b])
    _kopf_und_layout(blatt, kopf, werte, hinweis_spalte=3, anzahl_zeilen=len(werte))

    _bedingte_formatierung(blatt, len(kopf), len(werte), einstellungen)
    zellen = _Zellen(blatt)
    blatt.append([zellen.zelle(k, fett=True) for k in kopf])
    for z, zeilenwerte in zip(zeilen, werte):
        fmt_a = tab_a.formate[z.a] if (tab_a.formate is not None and z.a is not None) else leer_a
        fmt_b = tab_b.formate[z.b] if (tab_b.formate is not None and z.b is not None) else leer_b
        formate = [None, None, None, *fmt_a, *fmt_b]
        blatt.append([zellen.zelle(w, None, f) for w, f in zip(zeilenwerte, formate)])
    return zellen


def _live_zaehler(zellen: _Zellen, anzahl_zeilen: int) -> list[list[WriteOnlyCell]]:
    """Formeln, die den aktuellen Status in „Zusammengeführt“ zählen – auch nach Änderungen von Hand."""
    bereich = f"'{BLATT_ERGEBNIS}'!$A$2:$A${max(anzahl_zeilen, 1) + 1}"
    zeilen = [[zellen.zelle("Aktueller Stand in „Zusammengeführt“ (zählt Änderungen von Hand mit)", fett=True),
               zellen.zelle(None)]]
    for anzeige, schreibweisen, _farbe in _MARKIERUNGEN:
        formel = "=" + "+".join(f'SUMPRODUCT(--(TRIM({bereich})="{text}"))' for text in schreibweisen)
        zeilen.append([zellen.zelle(anzeige), zellen.zelle(formel, formel=True)])
    erste, letzte = 2, 1 + len(_MARKIERUNGEN)
    zeilen.append([zellen.zelle("Sonstige Einträge"),
                   zellen.zelle(f"=ROWS({bereich})-SUM(B{erste}:B{letzte})", formel=True)])
    zeilen.append([zellen.zelle("Zeilen gesamt"), zellen.zelle(f"=ROWS({bereich})", formel=True)])
    zeilen.append([zellen.zelle("Hinweis zu „Falsch“"),
                   zellen.zelle("Die Werte aus B stehen dann noch in der Zeile – bitte von Hand entfernen "
                                "oder in die richtige Zeile verschieben.")])
    zeilen.append([zellen.zelle(None), zellen.zelle(None)])
    return zeilen


def _blatt_protokoll(mappe: Any, protokoll: list[Protokollzeile], anzahl_zeilen: int) -> None:
    blatt = mappe.create_sheet(BLATT_PROTOKOLL)
    blatt.column_dimensions["A"].width = 52
    blatt.column_dimensions["B"].width = 70
    zellen = _Zellen(blatt)
    for zeile in _live_zaehler(zellen, anzahl_zeilen):
        blatt.append(zeile)
    for zeile in protokoll:
        wert = zeile.wert
        if isinstance(wert, (list, tuple)):
            wert = ", ".join(str(w) for w in wert)
        erste = zellen.zelle(zeile.eintrag, fett=zeile.ueberschrift)
        zweite = zellen.zelle(wert)
        zweite.alignment = Alignment(wrap_text=False)
        blatt.append([erste, zweite])


def _blatt_kandidaten(mappe: Any, tab_a: Tabelle, tab_b: Tabelle, abgleich: Abgleich,
                      personen_a: Sequence[Person], personen_b: Sequence[Person]) -> None:
    blatt = mappe.create_sheet(BLATT_KANDIDATEN)
    kopf = ["A_Zeile", "A_Name", "Match_Status"]
    for k in range(1, 4):
        kopf += [f"Kandidat_{k}", f"Score_{k}", f"B_Zeile_{k}"]
    werte: list[list[Any]] = []
    for z in abgleich.zeilen_a:
        assert z.a is not None
        zeile: list[Any] = [tab_a.zeilennummern[z.a], personen_a[z.a].anzeige or None, z.status.value]
        for j, score in abgleich.kandidaten.get(z.a, [])[:3]:
            zeile += [personen_b[j].anzeige, score, tab_b.zeilennummern[j]]
        zeile += [None] * (len(kopf) - len(zeile))
        werte.append(zeile)
    _kopf_und_layout(blatt, kopf, werte, hinweis_spalte=None, anzahl_zeilen=len(werte))
    zellen = _Zellen(blatt)
    blatt.append([zellen.zelle(k, fett=True) for k in kopf])
    for zeile in werte:
        blatt.append([zellen.zelle(w) for w in zeile])


def schreiben(pfad: Path | str, tab_a: Tabelle, tab_b: Tabelle, abgleich: Abgleich,
              personen_a: Sequence[Person], personen_b: Sequence[Person], protokoll: list[Protokollzeile],
              einstellungen: Einstellungen, ueberschreiben: bool = False) -> Path:
    """Schreibt die Ergebnisdatei (.xlsx) und gibt ihren Pfad zurück."""
    pfad = Path(pfad)
    if pfad.suffix.lower() != ".xlsx":
        raise AusgabeFehler(f"Die Ergebnisdatei muss die Endung .xlsx haben (angegeben: {pfad.name}).")
    if pfad.exists() and not ueberschreiben:
        raise AusgabeFehler(f"Die Ergebnisdatei {pfad.name} existiert bereits. "
                            "Bitte anderen Namen wählen oder Überschreiben erlauben.")
    ordner = pfad.parent
    try:
        ordner.mkdir(parents=True, exist_ok=True)
    except OSError as fehler:
        raise AusgabeFehler(f"Ausgabeordner kann nicht angelegt werden ({fehler.__class__.__name__}).") from None

    zeilen = ergebniszeilen(abgleich, einstellungen.sortierung)
    try:
        with _arbeitsordner(ordner) as arbeit:
            mappe = openpyxl.Workbook(write_only=True)
            mappe.properties.creator = f"namematch {__version__}"
            mappe.calculation.fullCalcOnLoad = True  # Zähler-Formeln beim Öffnen berechnen
            zellen = _blatt_ergebnis(mappe, tab_a, tab_b, zeilen, einstellungen)
            protokoll = list(protokoll)
            if zellen.bereinigt:
                protokoll.append(Protokollzeile("Bereinigte Zellen (unzulässige Steuerzeichen entfernt)",
                                                zellen.bereinigt))
            if zellen.gekuerzt:
                protokoll.append(Protokollzeile("Gekürzte Zellen (über 32.767 Zeichen)", zellen.gekuerzt))
            _blatt_protokoll(mappe, protokoll, len(zeilen))
            if einstellungen.kandidaten_blatt:
                _blatt_kandidaten(mappe, tab_a, tab_b, abgleich, personen_a, personen_b)
            zwischen = arbeit / "ergebnis.xlsx"
            mappe.save(zwischen)
            try:
                os.replace(zwischen, pfad)
            except PermissionError:
                raise AusgabeFehler(f"Die Ergebnisdatei {pfad.name} ist gesperrt. "
                                    "Ist sie gerade in Excel geöffnet? Bitte schließen und erneut versuchen.") from None
    except PermissionError:
        raise AusgabeFehler(f"Keine Schreibberechtigung im Ausgabeordner für {pfad.name}.") from None
    except OSError as fehler:
        raise AusgabeFehler(f"Die Ergebnisdatei {pfad.name} kann nicht geschrieben werden "
                            f"({fehler.__class__.__name__}).") from None
    log.info("Ergebnis geschrieben: %d Zeilen, %d Spalten", len(zeilen),
             len(MATCH_SPALTEN) + len(tab_a.spalten) + len(tab_b.spalten))
    return pfad
