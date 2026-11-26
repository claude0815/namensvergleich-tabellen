"""Tests für die Excel-Ausgabe (Aufbau, Farben, Werte, keine Spuren außerhalb des Ausgabeordners)."""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

import openpyxl
import pytest

from namematch.config import Einstellungen
from namematch.errors import AusgabeFehler
from namematch.io import Tabelle
from namematch.matcher import Abgleich, Person, Status, Zeilenergebnis
from namematch.normalize import LEER
from namematch.output import Protokollzeile, ergebniszeilen, schreiben

E = Einstellungen()


def _tabellen() -> tuple[Tabelle, Tabelle]:
    a = Tabelle(
        quelle=Path("a.xlsx"), dateityp="xlsx",
        spalten=["Name", "Klasse", "Geburtsdatum", "PLZ", "Spalte_5"],
        zeilen=[
            ["Max Mustermann", "7b", dt.datetime(2012, 3, 14), "01067", None],
            ["Jens Meier", "8a", None, "01069", "=1+1"],
            ["Petra Lang", "9a", None, "01309", "Steuer\x0bzeichen"],
        ],
        zeilennummern=[2, 3, 4],
        formate=[[None, None, "DD.MM.YYYY", None, None], [None] * 5, [None] * 5],
    )
    b = Tabelle(
        quelle=Path("b.csv"), dateityp="csv",
        spalten=["Vorname", "Nachname", "Klasse", "Telefon"],
        zeilen=[["Max", "Mustermann", "7b", "0123 456"], ["Tom", "Becker", "5b", "0123 222"],
                ["Jens", "Meyer", "8a", None]],
        zeilennummern=[2, 3, 4],
    )
    return a, b


def _abgleich() -> Abgleich:
    return Abgleich(
        zeilen_a=[
            Zeilenergebnis(Status.SICHER, a=0, b=0, score=100),
            Zeilenergebnis(Status.PRUEFEN, a=1, b=2, score=84, hinweise=["Klasse abweichend: 8a / 8b"]),
            Zeilenergebnis(Status.NUR_A, a=2),
        ],
        nur_b=[Zeilenergebnis(Status.NUR_B, b=1)],
        kandidaten={0: [(0, 100)], 1: [(2, 84), (0, 40)], 2: []},
    )


def _personen(namen: list[str]) -> list[Person]:
    return [Person(index=i, name=LEER, anzeige=n) for i, n in enumerate(namen)]


def _schreiben(pfad: Path, einstellungen: Einstellungen = E, **kw) -> Path:
    a, b = _tabellen()
    return schreiben(
        pfad, a, b, _abgleich(), _personen(["Max Mustermann", "Jens Meier", "Petra Lang"]),
        _personen(["Max Mustermann", "Tom Becker", "Jens Meyer"]),
        [Protokollzeile("Eingabe", ueberschrift=True), Protokollzeile("Datei A", "a.xlsx")], einstellungen, **kw,
    )


def test_aufbau_und_werte(tmp_path: Path) -> None:
    pfad = _schreiben(tmp_path / "ergebnis.xlsx")
    mappe = openpyxl.load_workbook(pfad)
    assert mappe.sheetnames == ["Zusammengeführt", "Protokoll", "Kandidaten"]
    blatt = mappe["Zusammengeführt"]
    kopf = [z.value for z in blatt[1]]
    assert kopf == ["Match_Status", "Match_Score", "Match_Hinweis", "A_Name", "A_Klasse", "A_Geburtsdatum",
                    "A_PLZ", "A_Spalte_5", "B_Vorname", "B_Nachname", "B_Klasse", "B_Telefon"]
    zeilen = [[z.value for z in r] for r in blatt.iter_rows(min_row=2)]
    assert len(zeilen) == 4  # 3 aus A + 1 nur in B
    assert zeilen[0][:5] == ["Sicher", 100, None, "Max Mustermann", "7b"]
    assert zeilen[0][8:] == ["Max", "Mustermann", "7b", "0123 456"]
    assert zeilen[1][2] == "Klasse abweichend: 8a / 8b"
    assert zeilen[1][8:11] == ["Jens", "Meyer", "8a"]
    assert zeilen[2][0] == "Nur in A" and zeilen[2][1] is None
    assert zeilen[2][8:] == [None, None, None, None]
    assert zeilen[3][0] == "Nur in B"
    assert zeilen[3][3:8] == [None] * 5
    assert zeilen[3][8:] == ["Tom", "Becker", "5b", "0123 222"]


def test_typen_formate_und_formeltext(tmp_path: Path) -> None:
    blatt = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx"))["Zusammengeführt"]
    datum = blatt.cell(row=2, column=6)
    assert datum.value == dt.datetime(2012, 3, 14)
    assert datum.number_format == "DD.MM.YYYY"
    assert blatt.cell(row=2, column=7).value == "01067"
    formel = blatt.cell(row=3, column=8)
    assert formel.value == "=1+1"
    assert formel.data_type == "s"  # als Text, nicht als Formel
    assert blatt.cell(row=4, column=8).value == "Steuerzeichen"  # unzulässiges Zeichen entfernt


def test_farben_als_bedingte_formatierung(tmp_path: Path) -> None:
    """Ganze Zeile wird nach Match_Status gefärbt – auch wenn der Status von Hand geändert wird."""
    blatt = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx"))["Zusammengeführt"]
    bereiche = list(blatt.conditional_formatting)
    assert [str(b.sqref) for b in bereiche] == ["A2:L5"]  # alle Spalten, alle Datenzeilen
    regeln = {r.formula[0]: r.dxf.fill.fgColor.rgb[-6:] for r in bereiche[0].rules}
    assert regeln == {
        'TRIM($A2)="Sicher"': E.farben.sicher,
        'OR(TRIM($A2)="Prüfen",TRIM($A2)="Pruefen")': E.farben.pruefen,
        'TRIM($A2)="Mehrdeutig"': E.farben.mehrdeutig,
        'TRIM($A2)="Nur in A"': E.farben.nur_a,
        'TRIM($A2)="Nur in B"': E.farben.nur_b,
        'TRIM($A2)="Falsch"': E.farben.falsch,
    }
    assert E.farben.falsch != E.farben.nur_a  # „Falsch“ ist von „Nur in A“ unterscheidbar
    # keine festen Zellfarben mehr (sonst bliebe die alte Farbe bei unbekannten Eingaben stehen)
    assert {z.fill.fill_type for zeile in blatt.iter_rows(min_row=2) for z in zeile} == {None}
    assert blatt[1][0].font.b


def test_auswahlliste_fuer_status(tmp_path: Path) -> None:
    blatt = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx"))["Zusammengeführt"]
    [auswahl] = blatt.data_validations.dataValidation
    assert str(auswahl.sqref) == "A2:A5"
    assert auswahl.formula1 == '"Sicher,Prüfen,Mehrdeutig,Nur in A,Nur in B,Falsch"'
    assert auswahl.showErrorMessage is False  # andere Eingaben bleiben erlaubt


def test_farbe_folgt_geaendertem_status_in_libreoffice(tmp_path: Path) -> None:
    """Echte Darstellung prüfen: „Prüfen“ → „sicher“ geändert, LibreOffice rendert die Zeile grün."""
    import shutil
    import subprocess

    soffice = shutil.which("soffice")
    if soffice is None:
        pytest.skip("LibreOffice nicht installiert")
    pfad = _schreiben(tmp_path / "e.xlsx")
    mappe = openpyxl.load_workbook(pfad)
    blatt = mappe["Zusammengeführt"]
    blatt["A3"] = "sicher"  # Sichtprüfung: „Prüfen“ von Hand bestätigt (klein geschrieben)
    for name in mappe.sheetnames[1:]:
        del mappe[name]
    mappe.save(pfad)
    ergebnis = subprocess.run([soffice, "--headless", "--convert-to", "html", "--outdir", str(tmp_path), str(pfad)],
                              capture_output=True, text=True, timeout=120, check=False)
    html = (tmp_path / "e.html").read_text(encoding="utf-8", errors="replace") if ergebnis.returncode == 0 else ""
    if not html:
        pytest.skip("LibreOffice-Konvertierung nicht möglich")
    zeilen = html.lower().split("<tr")
    assert E.farben.sicher.lower() in zeilen[3]   # geänderte Zeile jetzt grün
    assert E.farben.pruefen.lower() not in zeilen[3]
    assert E.farben.sicher.lower() in zeilen[2]   # unveränderte „Sicher“-Zeile


def test_excel_bedienbarkeit(tmp_path: Path) -> None:
    blatt = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx"))["Zusammengeführt"]
    assert blatt.freeze_panes == "A2"
    assert blatt.auto_filter.ref == "A1:L5"
    assert 8 <= blatt.column_dimensions["A"].width <= 60


def test_protokoll_und_kandidaten(tmp_path: Path) -> None:
    mappe = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx"))
    protokoll = [[z.value for z in r] for r in mappe["Protokoll"].iter_rows()]
    assert ["Datei A", "a.xlsx"] in protokoll
    assert any(r[0] == "Bereinigte Zellen (unzulässige Steuerzeichen entfernt)" and r[1] == 1 for r in protokoll)
    kand = [[z.value for z in r] for r in mappe["Kandidaten"].iter_rows()]
    assert kand[0][:6] == ["A_Zeile", "A_Name", "Match_Status", "Kandidat_1", "Score_1", "B_Zeile_1"]
    assert kand[2][:9] == [3, "Jens Meier", "Prüfen", "Jens Meyer", 84, 4, "Max Mustermann", 40, 2]


def test_ohne_kandidatenblatt(tmp_path: Path) -> None:
    from dataclasses import replace
    mappe = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx", replace(E, kandidaten_blatt=False)))
    assert mappe.sheetnames == ["Zusammengeführt", "Protokoll"]


def test_sortierung_nach_status() -> None:
    abgleich = _abgleich()
    original = [z.status for z in ergebniszeilen(abgleich, "original")]
    assert original == [Status.SICHER, Status.PRUEFEN, Status.NUR_A, Status.NUR_B]
    nach_status = [z.status for z in ergebniszeilen(abgleich, "status")]
    assert nach_status == [Status.PRUEFEN, Status.NUR_A, Status.SICHER, Status.NUR_B]


def test_vorhandene_datei_wird_nicht_ueberschrieben(tmp_path: Path) -> None:
    ziel = tmp_path / "e.xlsx"
    ziel.write_bytes(b"alt")
    with pytest.raises(AusgabeFehler, match="existiert bereits"):
        _schreiben(ziel)
    assert ziel.read_bytes() == b"alt"
    _schreiben(ziel, ueberschreiben=True)
    assert openpyxl.load_workbook(ziel).sheetnames[0] == "Zusammengeführt"


def test_nur_xlsx(tmp_path: Path) -> None:
    with pytest.raises(AusgabeFehler, match=r"\.xlsx"):
        _schreiben(tmp_path / "e.csv")


def test_ausgabeordner_wird_angelegt(tmp_path: Path) -> None:
    assert _schreiben(tmp_path / "neu" / "e.xlsx").exists()


def test_keine_temporaeren_dateien_ausserhalb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    system_temp = tmp_path / "systemtemp"
    system_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))
    ausgabe = tmp_path / "ausgabe"
    ausgabe.mkdir()
    _schreiben(ausgabe / "e.xlsx")
    assert list(system_temp.iterdir()) == []
    assert [p.name for p in ausgabe.iterdir()] == ["e.xlsx"]  # Arbeitsordner wieder entfernt
    assert tempfile.tempdir == str(system_temp)  # Einstellung wiederhergestellt


def test_protokoll_mit_live_zaehlern(tmp_path: Path) -> None:
    blatt = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx"))["Protokoll"]
    zeilen = [[z.value for z in r] for r in blatt.iter_rows()]
    assert zeilen[0][0].startswith("Aktueller Stand")
    formeln = {r[0]: r[1] for r in zeilen[1:10]}
    bereich = "'Zusammengeführt'!$A$2:$A$5"
    assert formeln["Sicher"] == f'=SUMPRODUCT(--(TRIM({bereich})="Sicher"))'
    assert formeln["Prüfen"] == (f'=SUMPRODUCT(--(TRIM({bereich})="Prüfen"))'
                                 f'+SUMPRODUCT(--(TRIM({bereich})="Pruefen"))')
    assert formeln["Falsch"] == f'=SUMPRODUCT(--(TRIM({bereich})="Falsch"))'
    assert formeln["Zeilen gesamt"] == f"=ROWS({bereich})"
    assert "Sonstige Einträge" in formeln
    assert blatt["B2"].data_type == "f"  # echte Formeln, kein Text


def _libreoffice_html(tmp_path: Path, pfad: Path) -> str:
    import shutil
    import subprocess

    soffice = shutil.which("soffice")
    if soffice is None:
        pytest.skip("LibreOffice nicht installiert")
    ergebnis = subprocess.run([soffice, "--headless", "--convert-to", "html", "--outdir", str(tmp_path), str(pfad)],
                              capture_output=True, text=True, timeout=120, check=False)
    html_pfad = pfad.with_suffix(".html")
    if ergebnis.returncode != 0 or not html_pfad.exists():
        pytest.skip("LibreOffice-Konvertierung nicht möglich")
    return html_pfad.read_text(encoding="utf-8", errors="replace")


def test_live_zaehler_folgen_aenderungen_in_libreoffice(tmp_path: Path) -> None:
    """Status von Hand ändern → Zähler im Protokoll rechnen neu (LibreOffice berechnet die Formeln)."""
    import re

    pfad = _schreiben(tmp_path / "e.xlsx")
    mappe = openpyxl.load_workbook(pfad)
    blatt = mappe["Zusammengeführt"]
    blatt["A3"] = "sicher"   # Prüfen → Sicher
    blatt["A4"] = "Falsch"   # Nur in A → als falsch markiert
    mappe.save(pfad)
    html = _libreoffice_html(tmp_path, pfad)
    protokoll = html[html.find("Aktueller Stand"):]
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", protokoll))
    for status, anzahl in (("Sicher", 2), ("Prüfen", 0), ("Nur in A", 0), ("Nur in B", 1), ("Falsch", 1),
                           ("Zeilen gesamt", 4)):
        assert re.search(rf"{re.escape(status)} {anzahl}\b", text), (status, text[:400])


def test_falsch_wird_rot_in_libreoffice(tmp_path: Path) -> None:
    pfad = _schreiben(tmp_path / "e.xlsx")
    mappe = openpyxl.load_workbook(pfad)
    mappe["Zusammengeführt"]["A3"] = "falsch"
    for name in mappe.sheetnames[1:]:
        del mappe[name]
    mappe.save(pfad)
    zeilen = _libreoffice_html(tmp_path, pfad).lower().split("<tr")
    assert E.farben.falsch.lower() in zeilen[3]
