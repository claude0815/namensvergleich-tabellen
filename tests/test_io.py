"""Tests für das Einlesen von CSV- und Excel-Dateien (nur synthetische Testdateien)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from namematch.errors import EingabeFehler
from namematch.io import Einleseoptionen, blattnamen, einlesen, zelltext
from tests.fixtures import erzeuge_fixtures as fx

FIX = Path(__file__).parent / "fixtures"
SPALTEN_B = ["Schüler-ID", "Nachname", "Vorname", "Klasse", "Geburtsdatum", "Telefon", "E-Mail", "Spalte_8", "PLZ"]


def _b_erwartet() -> list[list]:
    _a, b = fx.daten()
    return [[None if w in ("", None) else w for w in z] for z in b if z is not None]


def _als_vergleich(zeilen: list[list]) -> list[list]:
    return [[None if w in ("", None) else w for w in z] for z in zeilen]


@pytest.mark.parametrize(
    ("datei", "kodierung", "trennzeichen"),
    [
        ("schueler_b_semikolon_cp1252.csv", "cp1252", ";"),
        ("schueler_b_komma_utf8.csv", "utf-8", ","),
        ("schueler_b_tab_utf8bom.csv", "utf-8-sig", "\t"),
    ],
)
def test_csv_varianten(datei: str, kodierung: str, trennzeichen: str) -> None:
    tab = einlesen(FIX / datei)
    assert tab.dateityp == "csv"
    assert tab.kodierung == kodierung
    assert tab.trennzeichen == trennzeichen
    assert tab.spalten == SPALTEN_B
    assert _als_vergleich(tab.zeilen) == _b_erwartet()
    assert tab.leere_zeilen == 1


@pytest.mark.parametrize("datei", ["schueler_b.xlsx", "schueler_b.xls"])
def test_excel_b_gleicher_inhalt(datei: str) -> None:
    tab = einlesen(FIX / datei)
    assert tab.spalten == SPALTEN_B
    assert _als_vergleich(tab.zeilen) == _b_erwartet()
    assert tab.leere_zeilen == 1


def test_csv_werte_bleiben_text() -> None:
    tab = einlesen(FIX / "schueler_b_semikolon_cp1252.csv")
    erste = dict(zip(tab.spalten, tab.zeilen[0]))
    assert erste["PLZ"] == "01067"
    assert erste["Geburtsdatum"] == "14.03.2012"
    assert erste["Telefon"] == "0123 456"
    nachnamen = [z[1] for z in tab.zeilen]
    assert "Müller" in nachnamen


def test_csv_formelzeichen_bleibt_text() -> None:
    tab = einlesen(FIX / "schueler_b_komma_utf8.csv")
    assert "=SUMME(A1:A3)" in [z[7] for z in tab.zeilen]


def test_xlsx_typen_und_formate() -> None:
    tab = einlesen(FIX / "schueler_a.xlsx")
    assert tab.blatt == "Klassenliste"
    assert tab.blaetter == ["Klassenliste", "Info"]
    assert tab.spalten == ["Nr", "Name", "Klasse", "Geburtsdatum", "PLZ", "Spalte_6", "Bemerkung", "Telefon"]
    erste = dict(zip(tab.spalten, tab.zeilen[0]))
    assert erste["Nr"] == "001"
    assert erste["PLZ"] == "01067"
    assert erste["Geburtsdatum"] == dt.datetime(2012, 3, 14)
    assert tab.formate is not None
    assert tab.formate[0][3] == "DD.MM.YYYY"
    assert tab.leere_zeilen == 1
    # Zeilennummern beziehen sich auf die Datei (Kopfzeile = 1, leere Zeile übersprungen)
    assert tab.zeilennummern[:2] == [2, 3]
    assert tab.zeilennummern[10] == 13


def test_blatt_auswahl() -> None:
    assert blattnamen(FIX / "schueler_a.xlsx") == ["Klassenliste", "Info"]
    tab = einlesen(FIX / "schueler_a.xlsx", Einleseoptionen(blatt="Info"))
    assert tab.spalten == ["Hinweis"]
    with pytest.raises(EingabeFehler, match="Blatt „Gibtsnicht“"):
        einlesen(FIX / "schueler_a.xlsx", Einleseoptionen(blatt="Gibtsnicht"))


def test_kopfzeile_waehlbar() -> None:
    tab = einlesen(FIX / "mit_titelzeilen.csv", Einleseoptionen(kopfzeile=4))
    assert tab.spalten == ["Vorname", "Nachname", "Klasse"]
    assert len(tab.zeilen) == 3
    assert tab.zeilennummern[0] == 5


def test_kodierung_und_trennzeichen_ueberschreibbar() -> None:
    tab = einlesen(FIX / "schueler_b_semikolon_cp1252.csv", Einleseoptionen(kodierung="cp1252", trennzeichen=";"))
    assert tab.spalten == SPALTEN_B
    with pytest.raises(EingabeFehler, match="Kodierung"):
        einlesen(FIX / "schueler_b_semikolon_cp1252.csv", Einleseoptionen(kodierung="utf-8"))
    tab2 = einlesen(FIX / "schueler_b_semikolon_cp1252.csv", Einleseoptionen(trennzeichen=","))
    assert len(tab2.spalten) == 1


def test_doppelte_und_leere_ueberschriften(tmp_path: Path) -> None:
    datei = tmp_path / "x.csv"
    datei.write_text("Name;Name;;Klasse;;\nA;B;C;7b;;\nD;E;;8a;;X;Y\n", encoding="utf-8")
    tab = einlesen(datei)
    assert tab.spalten == ["Name", "Name_2", "Spalte_3", "Klasse", "Spalte_5", "Spalte_6", "Spalte_7"]
    assert tab.zeilen[0] == ["A", "B", "C", "7b", None, None, None]
    assert tab.zeilen[1] == ["D", "E", None, "8a", None, "X", "Y"]


def test_leere_spalten_am_ende_entfallen(tmp_path: Path) -> None:
    datei = tmp_path / "x.csv"
    datei.write_text("Name;Klasse;;\nA;7b;;\n", encoding="utf-8")
    assert einlesen(datei).spalten == ["Name", "Klasse"]


def test_leere_ueberschrift_mit_daten_bleibt(tmp_path: Path) -> None:
    datei = tmp_path / "x.csv"
    datei.write_text("Name;;Klasse\nA;Notiz;7b\n", encoding="utf-8")
    assert einlesen(datei).spalten == ["Name", "Spalte_2", "Klasse"]


def test_fehler_verstaendlich(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(EingabeFehler, match="nicht gefunden"):
        einlesen(tmp_path / "fehlt.csv")
    (tmp_path / "x.pdf").write_text("a", encoding="utf-8")
    with pytest.raises(EingabeFehler, match="Dateiformat"):
        einlesen(tmp_path / "x.pdf")
    (tmp_path / "leer.csv").write_bytes(b"")
    with pytest.raises(EingabeFehler, match="leer"):
        einlesen(tmp_path / "leer.csv")
    (tmp_path / "kaputt.xlsx").write_bytes(b"keine Excel-Datei")
    with pytest.raises(EingabeFehler, match="Excel"):
        einlesen(tmp_path / "kaputt.xlsx")
    with pytest.raises(EingabeFehler, match="Kopfzeile"):
        einlesen(FIX / "nur_vornamen.csv", Einleseoptionen(kopfzeile=99))


def test_gesperrte_datei(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    datei = tmp_path / "gesperrt.csv"
    datei.write_text("Name\nA\n", encoding="utf-8")

    def gesperrt(*_args, **_kwargs):
        raise PermissionError("gesperrt")

    monkeypatch.setattr(Path, "read_bytes", gesperrt)
    with pytest.raises(EingabeFehler, match="gesperrt"):
        einlesen(datei)


def test_fehlermeldungen_ohne_zellinhalt(tmp_path: Path) -> None:
    datei = tmp_path / "x.csv"
    datei.write_bytes("Name\nGeheimname Ä\n".encode("cp1252"))
    with pytest.raises(EingabeFehler) as fehler:
        einlesen(datei, Einleseoptionen(kodierung="utf-8"))
    assert "Geheimname" not in str(fehler.value)


def test_unbekannte_kodierung(tmp_path: Path) -> None:
    datei = tmp_path / "x.csv"
    datei.write_text("Name\nA\n", encoding="utf-8")
    with pytest.raises(EingabeFehler, match="Kodierung"):
        einlesen(datei, Einleseoptionen(kodierung="gibt-es-nicht"))


def test_zelltext() -> None:
    assert zelltext(None) == ""
    assert zelltext("x") == "x"
    assert zelltext(7) == "7"
    assert zelltext(7.0) == "7"
    assert zelltext(7.5) == "7.5"
    assert zelltext(dt.datetime(2012, 3, 14)) == "2012-03-14"
    assert zelltext(dt.datetime(2012, 3, 14, 8, 30)) == "2012-03-14 08:30:00"
    assert zelltext(True) == "WAHR"
