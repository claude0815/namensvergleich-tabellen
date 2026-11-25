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


def test_farben_ganze_zeile(tmp_path: Path) -> None:
    blatt = openpyxl.load_workbook(_schreiben(tmp_path / "e.xlsx"))["Zusammengeführt"]
    erwartet = {2: E.farben.sicher, 3: E.farben.pruefen, 4: E.farben.nur_a, 5: E.farben.nur_b}
    for zeile, farbe in erwartet.items():
        farben = {z.fill.fgColor.rgb[-6:] for z in blatt[zeile]}
        assert farben == {farbe}, zeile
    assert blatt[1][0].font.b


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
