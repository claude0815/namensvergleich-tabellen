"""Akzeptanzkriterien aus ANFORDERUNGEN.md – automatisch geprüft mit synthetischen Testdaten.

Alle Tests laufen mit gesperrtem Netzwerk (``--disable-socket`` in pyproject.toml).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import logging
import re
import socket
import tempfile
import time
from pathlib import Path

import openpyxl
import pytest
from pytest_socket import SocketBlockedError

from namematch.cli import main
from namematch.pipeline import ausfuehren
from tests.fixtures import erzeuge_fixtures as fx

FIX = Path(__file__).parent / "fixtures"
A_XLSX = FIX / "schueler_a.xlsx"
B_CP1252 = FIX / "schueler_b_semikolon_cp1252.csv"
B_UTF8 = FIX / "schueler_b_komma_utf8.csv"
FESTER_ZEITPUNKT = dt.datetime(2025, 1, 1, 12, 0, 0)


def _cli(*args: str) -> tuple[int, str, str]:
    aus, fehler = io.StringIO(), io.StringIO()
    code = main(list(args), aus=aus, fehler=fehler, ist_terminal=lambda: False)
    return code, aus.getvalue(), fehler.getvalue()


def _blatt(pfad: Path, name: str = "Zusammengeführt") -> list[list]:
    return [list(r) for r in openpyxl.load_workbook(pfad)[name].iter_rows(values_only=True)]


def _sha256(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _csv_original(pfad: Path, kodierung: str, trennzeichen: str) -> tuple[list[str], list[list[str]]]:
    """Unabhängiges Einlesen mit dem csv-Modul (zum zellweisen Vergleich)."""
    zeilen = list(csv.reader(io.StringIO(pfad.read_bytes().decode(kodierung), newline=""), delimiter=trennzeichen))
    return zeilen[0], [z for z in zeilen[1:] if any(w.strip() for w in z)]


def _xlsx_original(pfad: Path) -> list[list[openpyxl.cell.Cell]]:
    blatt = openpyxl.load_workbook(pfad).worksheets[0]
    zeilen = list(blatt.iter_rows(min_row=2))
    return [z for z in zeilen if any(c.value not in (None, "") for c in z)]


@pytest.fixture(scope="module")
def lauf(tmp_path_factory: pytest.TempPathFactory):
    """Ein kompletter Lauf A (xlsx) × B (CSV ; cp1252) mit Ergebnisdatei."""
    ordner = tmp_path_factory.mktemp("lauf")
    ziel = ordner / "ergebnis.xlsx"
    ergebnis = ausfuehren(A_XLSX, B_CP1252, ziel, zeitpunkt=FESTER_ZEITPUNKT)
    return ergebnis, ziel


# --- Zeilen und Spalten ---------------------------------------------------------------

def test_zeilenanzahl_und_eindeutigkeit(lauf) -> None:
    ergebnis, ziel = lauf
    zeilen = _blatt(ziel)[1:]
    treffer = sum(1 for z in ergebnis.abgleich.zeilen_a if z.b is not None)
    nur_a = sum(1 for z in ergebnis.abgleich.zeilen_a if z.b is None)
    nur_b = len(ergebnis.abgleich.nur_b)
    assert len(zeilen) == treffer + nur_a + nur_b
    # jede A-Zeile und jede B-Zeile genau einmal
    a_indizes = [z.a for z in ergebnis.abgleich.zeilen_a]
    b_indizes = [z.b for z in ergebnis.abgleich.zeilen_a if z.b is not None] + [z.b for z in ergebnis.abgleich.nur_b]
    assert sorted(a_indizes) == list(range(len(ergebnis.tab_a.zeilen)))
    assert sorted(b_indizes) == list(range(len(ergebnis.tab_b.zeilen)))
    # unabhängig über die IDs in der Ergebnisdatei geprüft
    kopf = _blatt(ziel)[0]
    i_nr, i_id = kopf.index("A_Nr"), kopf.index("B_Schüler-ID")
    nrs = [z[i_nr] for z in zeilen if z[i_nr] is not None]
    ids = [z[i_id] for z in zeilen if z[i_id] is not None]
    assert len(nrs) == len(set(nrs)) == len(ergebnis.tab_a.zeilen)
    assert len(ids) == len(set(ids)) == len(ergebnis.tab_b.zeilen)


def test_spaltenanzahl(lauf) -> None:
    ergebnis, ziel = lauf
    kopf = _blatt(ziel)[0]
    assert len(kopf) == len(ergebnis.tab_a.spalten) + len(ergebnis.tab_b.spalten) + 3
    assert kopf[:3] == ["Match_Status", "Match_Score", "Match_Hinweis"]
    # leere Spalte, Spalte ohne Überschrift und gleichnamige Spalten bleiben erhalten
    for spalte in ("A_Bemerkung", "A_Spalte_6", "B_Spalte_8", "A_Klasse", "B_Klasse", "A_PLZ", "B_PLZ"):
        assert spalte in kopf


# --- Werte -----------------------------------------------------------------------------

def test_zellwerte_wie_original(lauf) -> None:
    """Zellweiser Vergleich gegen unabhängig eingelesene Originaldateien."""
    ergebnis, ziel = lauf
    mappe = openpyxl.load_workbook(ziel)["Zusammengeführt"]
    zeilen = list(mappe.iter_rows(min_row=2))
    original_a = _xlsx_original(A_XLSX)
    _kopf_b, original_b = _csv_original(B_CP1252, "cp1252", ";")
    n_a, n_b = len(ergebnis.tab_a.spalten), len(ergebnis.tab_b.spalten)
    geprueft = 0
    for zelle_zeile, z in zip(zeilen, ergebnis.abgleich.zeilen_a + ergebnis.abgleich.nur_b):
        a_teil, b_teil = zelle_zeile[3:3 + n_a], zelle_zeile[3 + n_a:3 + n_a + n_b]
        if z.a is not None:
            for neu, alt in zip(a_teil, original_a[z.a]):
                assert neu.value == (None if alt.value == "" else alt.value)
                if alt.value is not None and not isinstance(alt.value, str):
                    assert neu.number_format == alt.number_format
                geprueft += 1
        else:
            assert all(c.value is None for c in a_teil)
        if z.b is not None:
            alt_zeile = original_b[z.b] + [""] * (n_b - len(original_b[z.b]))
            for neu, alt in zip(b_teil, alt_zeile):
                assert neu.value == (alt or None)
                geprueft += 1
        else:
            assert all(c.value is None for c in b_teil)
    assert geprueft > 500


def test_fuehrende_nullen_datum_umlaute(lauf) -> None:
    _ergebnis, ziel = lauf
    blatt = openpyxl.load_workbook(ziel)["Zusammengeführt"]
    kopf = [c.value for c in blatt[1]]
    zeilen = list(blatt.iter_rows(min_row=2))
    erste = {k: c for k, c in zip(kopf, zeilen[0])}
    assert erste["A_Nr"].value == "001"
    assert erste["A_PLZ"].value == "01067"
    assert erste["A_Geburtsdatum"].value == dt.datetime(2012, 3, 14)
    assert erste["A_Geburtsdatum"].number_format == "DD.MM.YYYY"
    assert erste["B_Geburtsdatum"].value == "14.03.2012"
    assert erste["B_PLZ"].value == "01067"
    assert erste["B_Telefon"].value == "0123 456"
    alle_werte = {c.value for z in zeilen for c in z if isinstance(c.value, str)}
    for text in ("Özlem Yılmaz", "José García", "Dr. Jürgen Müller", "Hans-Peter Groß", "Müller", "Sabine Müller-Lang"):
        assert text in alle_werte


def test_csv_semikolon_cp1252_und_komma_utf8_gleich(tmp_path: Path) -> None:
    e1 = ausfuehren(A_XLSX, B_CP1252, tmp_path / "e1.xlsx", zeitpunkt=FESTER_ZEITPUNKT)
    e2 = ausfuehren(A_XLSX, B_UTF8, tmp_path / "e2.xlsx", zeitpunkt=FESTER_ZEITPUNKT)
    assert e1.tab_b.kodierung == "cp1252" and e1.tab_b.trennzeichen == ";"
    assert e2.tab_b.kodierung == "utf-8" and e2.tab_b.trennzeichen == ","
    assert _blatt(tmp_path / "e1.xlsx") == _blatt(tmp_path / "e2.xlsx")


# --- Offline, Logs, Spuren ---------------------------------------------------------------

def test_netzwerk_ist_gesperrt() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_kompletter_lauf_ohne_netzwerk(tmp_path: Path) -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)  # Dokumentationsadresse, wird nie erreicht
    code, _aus, fehler = _cli(str(A_XLSX), str(B_CP1252), "-o", str(tmp_path / "e.xlsx"), "--ja")
    assert code == 0, fehler
    assert (tmp_path / "e.xlsx").exists()


def _personendaten() -> set[str]:
    """Alle Namen und längeren Zellinhalte aus den Testdateien."""
    zeilen_a, zeilen_b = fx.daten()
    werte: set[str] = set()
    spalten = {str(s) for s in fx.SPALTEN_A + fx.SPALTEN_B if s}
    for zeile in [*zeilen_a, *zeilen_b]:
        if zeile is None:
            continue
        for wert in zeile:
            if isinstance(wert, str) and len(wert) >= 4 and wert not in spalten:
                werte.add(wert)
                werte.update(t for t in re.split(r"[\s,]+", wert)
                             if len(t) >= 4 and not t.endswith(".") and t not in spalten)
    return werte


def test_logs_ohne_namen_und_zellinhalte(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    code, aus, fehler = _cli(str(A_XLSX), str(B_CP1252), "-o", str(tmp_path / "e.xlsx"), "--ja", "-v")
    assert code == 0
    assert "INFO" in fehler  # ausführliche Meldungen wurden ausgegeben
    texte = fehler + aus + "\n".join(r.getMessage() for r in caplog.records)
    # Dateinamen der Testdaten selbst sind keine Personendaten
    texte = texte.replace(str(tmp_path), "").replace(A_XLSX.name, "").replace(B_CP1252.name, "")
    gefunden = sorted(w for w in _personendaten() if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", texte))
    assert gefunden == []


def test_keine_spuren_ausserhalb_des_ausgabeordners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    system_temp = tmp_path / "systemtemp"
    system_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))
    ausgabe = tmp_path / "ausgabe"
    code, _, _ = _cli(str(A_XLSX), str(B_CP1252), "-o", str(ausgabe / "e.xlsx"), "--ja")
    assert code == 0
    assert list(system_temp.iterdir()) == []
    assert [p.name for p in ausgabe.iterdir()] == ["e.xlsx"]


def test_originaldateien_unveraendert(tmp_path: Path) -> None:
    dateien = sorted(p for p in FIX.iterdir() if p.suffix in (".csv", ".xlsx", ".xls"))
    vorher = {p: (_sha256(p), p.stat().st_mtime_ns) for p in dateien}
    for datei_b in ("schueler_b_semikolon_cp1252.csv", "schueler_b_komma_utf8.csv", "schueler_b_tab_utf8bom.csv",
                    "schueler_b.xlsx", "schueler_b.xls"):
        code, _, _ = _cli(str(A_XLSX), str(FIX / datei_b), "-o", str(tmp_path / f"{datei_b}.xlsx"), "--ja")
        assert code == 0
    nachher = {p: (_sha256(p), p.stat().st_mtime_ns) for p in dateien}
    assert vorher == nachher


# --- Determinismus ---------------------------------------------------------------------

def test_zwei_laeufe_identisch(tmp_path: Path) -> None:
    ausfuehren(A_XLSX, B_CP1252, tmp_path / "e1.xlsx", zeitpunkt=FESTER_ZEITPUNKT)
    ausfuehren(A_XLSX, B_CP1252, tmp_path / "e2.xlsx", zeitpunkt=FESTER_ZEITPUNKT)
    m1, m2 = openpyxl.load_workbook(tmp_path / "e1.xlsx"), openpyxl.load_workbook(tmp_path / "e2.xlsx")
    assert m1.sheetnames == m2.sheetnames
    for name in m1.sheetnames:
        z1 = [[(c.value, c.number_format, c.fill.fgColor.rgb) for c in r] for r in m1[name].iter_rows()]
        z2 = [[(c.value, c.number_format, c.fill.fgColor.rgb) for c in r] for r in m2[name].iter_rows()]
        assert z1 == z2, name


def test_zwei_laeufe_identisch_ohne_festen_zeitpunkt(tmp_path: Path) -> None:
    """Auch über die Kommandozeile: alles gleich bis auf die Zeitpunkt-Zeile im Protokoll."""
    for name in ("e1.xlsx", "e2.xlsx"):
        assert _cli(str(A_XLSX), str(B_CP1252), "-o", str(tmp_path / name), "--ja")[0] == 0
    for blatt in ("Zusammengeführt", "Kandidaten"):
        assert _blatt(tmp_path / "e1.xlsx", blatt) == _blatt(tmp_path / "e2.xlsx", blatt)
    p1 = [z for z in _blatt(tmp_path / "e1.xlsx", "Protokoll") if z[0] != "Zeitpunkt"]
    p2 = [z for z in _blatt(tmp_path / "e2.xlsx", "Protokoll") if z[0] != "Zeitpunkt"]
    assert p1 == p2


# --- Leistung ----------------------------------------------------------------------------

@pytest.mark.langsam
def test_5000_mal_5000_unter_einer_minute(tmp_path: Path) -> None:
    datei_a, datei_b = fx.grosse_listen(tmp_path, anzahl=5000)
    start = time.perf_counter()
    code, aus, fehler = _cli(str(datei_a), str(datei_b), "-o", str(tmp_path / "gross.xlsx"), "--ja")
    dauer = time.perf_counter() - start
    assert code == 0, fehler
    zeilen = _blatt(tmp_path / "gross.xlsx")
    assert len(zeilen) - 1 >= 5000
    print(f"\n5.000 × 5.000 Zeilen: {dauer:.1f} s")
    assert dauer < 60


def test_kein_netzwerkcode_im_programm() -> None:
    """Statische Prüfung: Das Programm importiert keine Netzwerk- oder Telemetrie-Module."""
    import ast

    verboten = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
                "telnetlib", "xmlrpc", "websocket", "websockets", "subprocess", "webbrowser"}
    funde = []
    for datei in sorted((Path(__file__).parent.parent / "namematch").rglob("*.py")):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Import):
                namen = [a.name for a in knoten.names]
            elif isinstance(knoten, ast.ImportFrom) and knoten.module and knoten.level == 0:
                namen = [knoten.module]
            else:
                continue
            for n in namen:
                modul = n.split(".")[0]
                # Ausnahme: die GUI öffnet die fertige Ergebnisdatei mit dem Standardprogramm (open/xdg-open)
                if modul == "subprocess" and datei.name == "gui.py":
                    continue
                if modul in verboten:
                    funde.append(f"{datei.name}: {n}")
    assert funde == []
