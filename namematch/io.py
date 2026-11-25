"""Einlesen von CSV- und Excel-Dateien (.csv, .xlsx, .xls) – nur lesend.

- CSV: Kodierung (UTF-8, UTF-8 mit BOM, UTF-16 mit BOM, Windows-1252) und Trennzeichen
  (; , Tab |) werden erkannt; beides ist überschreibbar. Alle Werte bleiben Text.
- Excel: Werte behalten Typ und Zahlenformat (Datum bleibt Datum, Text bleibt Text),
  damit sie unverändert in die Ergebnisdatei übernommen werden können.

Die Originaldatei wird nur gelesen, es entstehen keine temporären Kopien.
"""

from __future__ import annotations

import codecs
import csv
import datetime as dt
import io
import logging
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import EingabeFehler

log = logging.getLogger(__name__)

TRENNZEICHEN = (";", ",", "\t", "|")


@dataclass(frozen=True)
class Einleseoptionen:
    """Optionen zum Einlesen einer Datei (alles optional)."""

    blatt: str | None = None        # Excel: Blattname (Standard: erstes Blatt)
    kopfzeile: int = 1              # Zeilennummer der Überschriften (1 = erste Zeile)
    trennzeichen: str | None = None  # CSV: None = automatisch
    kodierung: str | None = None     # CSV: None = automatisch


@dataclass
class Tabelle:
    """Eingelesene Tabelle. Werte sind Originalwerte; ``None`` steht für eine leere Zelle."""

    quelle: Path
    dateityp: str                   # "csv", "xlsx" oder "xls"
    spalten: list[str]              # eindeutige Spaltennamen (ohne Überschrift: „Spalte_7“)
    zeilen: list[list[Any]]         # Datenzeilen, je Zeile so lang wie ``spalten``
    zeilennummern: list[int]        # Zeilennummer in der Datei (1-basiert)
    formate: list[list[str | None]] | None = None  # Excel-Zahlenformate je Zelle
    blatt: str | None = None
    blaetter: list[str] = field(default_factory=list)
    kodierung: str | None = None
    trennzeichen: str | None = None
    kopfzeile: int = 1
    leere_zeilen: int = 0

    def spalte(self, name: str) -> int:
        """Index einer Spalte; Fehler mit Liste der vorhandenen Spalten."""
        try:
            return self.spalten.index(name)
        except ValueError:
            vorhanden = ", ".join(f"„{s}“" for s in self.spalten)
            raise EingabeFehler(f"Spalte „{name}“ gibt es in {self.quelle.name} nicht. Vorhanden: {vorhanden}") from None


def zelltext(wert: Any) -> str:
    """Text eines Zellwerts für Vergleich und Anzeige (der Originalwert bleibt unverändert)."""
    if wert is None:
        return ""
    if isinstance(wert, bool):
        return "WAHR" if wert else "FALSCH"
    if isinstance(wert, dt.datetime):
        if (wert.hour, wert.minute, wert.second, wert.microsecond) == (0, 0, 0, 0):
            return wert.date().isoformat()
        return wert.isoformat(sep=" ")
    if isinstance(wert, (dt.date, dt.time)):
        return wert.isoformat()
    if isinstance(wert, float) and wert.is_integer():
        return str(int(wert))
    return str(wert)


def _ist_leer(wert: Any) -> bool:
    return wert is None or (isinstance(wert, str) and not wert.strip())


# --- gemeinsame Aufbereitung -----------------------------------------------------------

def _aufbereiten(quelle: Path, dateityp: str, roh: list[list[Any]], formate: list[list[str | None]] | None,
                 kopfzeile: int, **extra: Any) -> Tabelle:
    """Bildet aus Rohzeilen (inkl. Kopfzeile) eine Tabelle mit eindeutigen Spaltennamen."""
    if not roh or all(all(_ist_leer(w) for w in zeile) for zeile in roh):
        raise EingabeFehler(f"Die Datei {quelle.name} ist leer.")
    if kopfzeile < 1 or kopfzeile > len(roh):
        raise EingabeFehler(
            f"Kopfzeile {kopfzeile} gibt es in {quelle.name} nicht (die Datei hat {len(roh)} Zeilen)."
        )
    kopf = roh[kopfzeile - 1]
    if all(_ist_leer(w) for w in kopf):
        raise EingabeFehler(f"Die Kopfzeile {kopfzeile} in {quelle.name} ist leer. Bitte die richtige Kopfzeile angeben.")

    daten: list[tuple[int, list[Any], list[str | None] | None]] = []
    leere = 0
    for offset, zeile in enumerate(roh[kopfzeile:], start=kopfzeile + 1):
        if all(_ist_leer(w) for w in zeile):
            leere += 1
            continue
        fmt = formate[offset - 1] if formate is not None else None
        daten.append((offset, zeile, fmt))

    def letzte_belegte(zeile: list[Any]) -> int:
        for k in range(len(zeile) - 1, -1, -1):
            if not _ist_leer(zeile[k]):
                return k + 1
        return 0

    breite = max([letzte_belegte(kopf)] + [letzte_belegte(z) for _, z, _ in daten])

    namen: list[str] = []
    for k in range(breite):
        wert = kopf[k] if k < len(kopf) else None
        text = zelltext(wert).strip()
        namen.append(text or f"Spalte_{k + 1}")
    eindeutig: list[str] = []
    for name in namen:
        kandidat, nummer = name, 2
        while kandidat in eindeutig or (kandidat != name and kandidat in namen):
            kandidat = f"{name}_{nummer}"
            nummer += 1
        eindeutig.append(kandidat)

    def auffuellen(zeile: list[Any], fuell: Any) -> list[Any]:
        zeile = list(zeile[:breite])
        return zeile + [fuell] * (breite - len(zeile))

    zeilen = [[None if w == "" else w for w in auffuellen(z, None)] for _, z, _ in daten]
    fmt_liste = [auffuellen(f or [], None) for _, _, f in daten] if formate is not None else None
    tabelle = Tabelle(
        quelle=quelle, dateityp=dateityp, spalten=eindeutig, zeilen=zeilen,
        zeilennummern=[n for n, _, _ in daten], formate=fmt_liste, kopfzeile=kopfzeile, leere_zeilen=leere, **extra,
    )
    log.info("%s: %d Zeilen, %d Spalten, %d leere Zeilen ignoriert", dateityp.upper(), len(zeilen), breite, leere)
    return tabelle


# --- CSV ---------------------------------------------------------------------------

def _dekodieren(daten: bytes, kodierung: str | None, quelle: Path) -> tuple[str, str]:
    """Liefert (Kodierung, Text). Reihenfolge: BOM → UTF-8 → Windows-1252."""
    if kodierung:
        try:
            codecs.lookup(kodierung)
        except LookupError:
            raise EingabeFehler(f"Unbekannte Kodierung „{kodierung}“.") from None
        try:
            return kodierung, daten.decode(kodierung)
        except UnicodeDecodeError as fehler:
            raise EingabeFehler(
                f"{quelle.name} lässt sich nicht mit der Kodierung „{kodierung}“ lesen "
                f"(ungültiges Zeichen an Byte-Position {fehler.start}). Bitte andere Kodierung wählen "
                "oder die automatische Erkennung verwenden."
            ) from None
    if daten.startswith(codecs.BOM_UTF8):
        return "utf-8-sig", daten.decode("utf-8-sig", errors="strict")
    if daten.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return "utf-16", daten.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return "utf-8", daten.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return "cp1252", daten.decode("cp1252")
    except UnicodeDecodeError:
        return "latin-1", daten.decode("latin-1")


def _trennzeichen_erkennen(text: str) -> str:
    """Wählt das Trennzeichen mit den gleichmäßigsten Feldanzahlen (Vorrang bei Gleichstand: ; , Tab |)."""
    probe = "\n".join(text.splitlines()[:50])
    bester, beste_wertung = ";", (-1.0, 0)
    for kandidat in TRENNZEICHEN:
        anzahlen = [len(z) for z in csv.reader(io.StringIO(probe, newline=""), delimiter=kandidat) if any(z)]
        if not anzahlen:
            continue
        haeufigste, haeufigkeit = Counter(anzahlen).most_common(1)[0]
        if haeufigste <= 1:
            continue
        wertung = (haeufigkeit / len(anzahlen), haeufigste)
        if wertung > beste_wertung:
            bester, beste_wertung = kandidat, wertung
    return bester


def _csv_lesen(pfad: Path, optionen: Einleseoptionen) -> Tabelle:
    daten = _bytes_lesen(pfad)
    kodierung, text = _dekodieren(daten, optionen.kodierung, pfad)
    trennzeichen = optionen.trennzeichen or _trennzeichen_erkennen(text)
    try:
        roh = [list(z) for z in csv.reader(io.StringIO(text, newline=""), delimiter=trennzeichen)]
    except csv.Error as fehler:
        raise EingabeFehler(f"{pfad.name} ist keine gültige CSV-Datei ({fehler.__class__.__name__}).") from None
    return _aufbereiten(pfad, "csv", roh, None, optionen.kopfzeile, kodierung=kodierung, trennzeichen=trennzeichen)


# --- Excel -------------------------------------------------------------------------

def _xlsx_lesen(pfad: Path, optionen: Einleseoptionen) -> Tabelle:
    mappe = _xlsx_oeffnen(pfad)
    try:
        blaetter = [b.title for b in mappe.worksheets]
        blatt = _blatt_waehlen(mappe, blaetter, optionen.blatt, pfad)
        blatt.reset_dimensions()  # falsche Größenangaben mancher Programme ignorieren
        roh: list[list[Any]] = []
        formate: list[list[str | None]] = []
        for zeile in blatt.iter_rows():
            werte, fmt = [], []
            for zelle in zeile:
                werte.append(zelle.value)
                format_ = getattr(zelle, "number_format", None)
                fmt.append(None if format_ in (None, "General") else format_)
            roh.append(werte)
            formate.append(fmt)
        titel = blatt.title
    except EingabeFehler:
        raise
    except Exception as fehler:  # beschädigte Datei
        raise EingabeFehler(f"Excel-Datei {pfad.name} kann nicht gelesen werden ({fehler.__class__.__name__}).") from None
    finally:
        mappe.close()
    return _aufbereiten(pfad, "xlsx", roh, formate, optionen.kopfzeile, blatt=titel, blaetter=blaetter)


def _xlsx_oeffnen(pfad: Path):
    import openpyxl

    _pruefen_lesbar(pfad)
    try:
        return openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    except PermissionError:
        raise EingabeFehler(_gesperrt(pfad)) from None
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as fehler:
        raise EingabeFehler(
            f"{pfad.name} ist keine gültige Excel-Datei (.xlsx) ({fehler.__class__.__name__}). "
            "Ist die Datei beschädigt oder passwortgeschützt?"
        ) from None


def _blatt_waehlen(mappe: Any, blaetter: list[str], gewuenscht: str | None, pfad: Path) -> Any:
    if not blaetter:
        raise EingabeFehler(f"{pfad.name} enthält kein Tabellenblatt.")
    if gewuenscht is None:
        return mappe[blaetter[0]]
    if gewuenscht not in blaetter:
        liste = ", ".join(f"„{b}“" for b in blaetter)
        raise EingabeFehler(f"Blatt „{gewuenscht}“ gibt es in {pfad.name} nicht. Vorhanden: {liste}")
    return mappe[gewuenscht]


def _xls_lesen(pfad: Path, optionen: Einleseoptionen) -> Tabelle:
    import xlrd

    daten = _bytes_lesen(pfad)
    try:
        mappe = xlrd.open_workbook(file_contents=daten, formatting_info=True, on_demand=True)
    except Exception as fehler:
        raise EingabeFehler(f"{pfad.name} ist keine gültige Excel-Datei (.xls) ({fehler.__class__.__name__}).") from None
    try:
        blaetter = mappe.sheet_names()
        if not blaetter:
            raise EingabeFehler(f"{pfad.name} enthält kein Tabellenblatt.")
        name = optionen.blatt or blaetter[0]
        if name not in blaetter:
            liste = ", ".join(f"„{b}“" for b in blaetter)
            raise EingabeFehler(f"Blatt „{name}“ gibt es in {pfad.name} nicht. Vorhanden: {liste}")
        blatt = mappe.sheet_by_name(name)
        roh: list[list[Any]] = []
        formate: list[list[str | None]] = []
        for r in range(blatt.nrows):
            werte, fmt = [], []
            for c in range(blatt.ncols):
                zelle = blatt.cell(r, c)
                format_ = None
                try:
                    xf = mappe.xf_list[zelle.xf_index]
                    format_ = mappe.format_map[xf.format_key].format_str
                except (IndexError, KeyError, TypeError):
                    pass
                if format_ == "General":
                    format_ = None
                if zelle.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    wert: Any = None
                elif zelle.ctype == xlrd.XL_CELL_DATE:
                    wert = xlrd.xldate.xldate_as_datetime(zelle.value, mappe.datemode)
                    format_ = format_ or "DD.MM.YYYY"
                elif zelle.ctype == xlrd.XL_CELL_NUMBER:
                    wert = int(zelle.value) if float(zelle.value).is_integer() else zelle.value
                elif zelle.ctype == xlrd.XL_CELL_BOOLEAN:
                    wert = bool(zelle.value)
                elif zelle.ctype == xlrd.XL_CELL_ERROR:
                    wert = xlrd.error_text_from_code.get(zelle.value, "#FEHLER")
                else:
                    wert = zelle.value
                werte.append(wert)
                fmt.append(format_)
            roh.append(werte)
            formate.append(fmt)
    finally:
        mappe.release_resources()
    return _aufbereiten(pfad, "xls", roh, formate, optionen.kopfzeile, blatt=name, blaetter=blaetter)


# --- öffentliche Funktionen ------------------------------------------------------------

def _gesperrt(pfad: Path) -> str:
    return (f"Die Datei {pfad.name} ist gesperrt oder es fehlt die Leseberechtigung. "
            "Ist sie gerade in Excel geöffnet? Bitte schließen und erneut versuchen.")


def _pruefen_lesbar(pfad: Path) -> None:
    if not pfad.exists():
        raise EingabeFehler(f"Datei nicht gefunden: {pfad}")
    if not pfad.is_file():
        raise EingabeFehler(f"Keine Datei: {pfad}")


def _bytes_lesen(pfad: Path) -> bytes:
    _pruefen_lesbar(pfad)
    try:
        return pfad.read_bytes()
    except PermissionError:
        raise EingabeFehler(_gesperrt(pfad)) from None
    except OSError as fehler:
        raise EingabeFehler(f"Die Datei {pfad.name} kann nicht gelesen werden ({fehler.__class__.__name__}).") from None


def _dateityp(pfad: Path) -> str:
    endung = pfad.suffix.lower()
    if endung in (".csv", ".txt", ".tsv"):
        return "csv"
    if endung in (".xlsx", ".xlsm"):
        return "xlsx"
    if endung == ".xls":
        return "xls"
    raise EingabeFehler(f"Dateiformat „{pfad.suffix or '(ohne Endung)'}“ wird nicht unterstützt. "
                        "Erlaubt sind .xlsx, .xls und .csv.")


def einlesen(pfad: Path | str, optionen: Einleseoptionen | None = None) -> Tabelle:
    """Liest eine CSV- oder Excel-Datei (nur lesend)."""
    pfad = Path(pfad)
    optionen = optionen or Einleseoptionen()
    typ = _dateityp(pfad)
    if typ == "csv":
        return _csv_lesen(pfad, optionen)
    if typ == "xlsx":
        return _xlsx_lesen(pfad, optionen)
    return _xls_lesen(pfad, optionen)


def blattnamen(pfad: Path | str) -> list[str]:
    """Namen der Tabellenblätter einer Excel-Datei (für CSV: leere Liste)."""
    pfad = Path(pfad)
    typ = _dateityp(pfad)
    if typ == "csv":
        return []
    if typ == "xlsx":
        mappe = _xlsx_oeffnen(pfad)
        try:
            return [b.title for b in mappe.worksheets]
        finally:
            mappe.close()
    import xlrd

    try:
        mappe = xlrd.open_workbook(file_contents=_bytes_lesen(pfad), on_demand=True)
    except Exception as fehler:
        raise EingabeFehler(f"{pfad.name} ist keine gültige Excel-Datei (.xls) ({fehler.__class__.__name__}).") from None
    try:
        return mappe.sheet_names()
    finally:
        mappe.release_resources()
