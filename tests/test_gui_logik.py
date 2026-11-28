"""Tests der GUI-Logik (ohne tkinter, läuft überall) mit synthetischen Testdaten."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from namematch.columns import Namensspalten, Zusatzspalten
from namematch.errors import EingabeFehler
from namematch.gui_logik import KEINE, KODIERUNGEN, TRENNZEICHEN, Liste, Sitzung
from namematch.io import Einleseoptionen

FIX = Path(__file__).parent / "fixtures"


def test_liste_laden_mit_vorschlag() -> None:
    liste = Liste("A")
    liste.laden(FIX / "schueler_a.xlsx")
    assert liste.namen == Namensspalten(voll="Name")
    assert liste.zusatz.klasse == "Klasse"
    assert liste.blaetter == ["Klassenliste", "Info"]
    assert liste.ist_excel
    assert "44 Zeilen" in liste.info()


def test_vorschau_zehn_zeilen_als_text() -> None:
    liste = Liste("A")
    liste.laden(FIX / "schueler_a.xlsx")
    kopf, zeilen = liste.vorschau()
    assert kopf[:2] == ["Nr", "Name"]
    assert len(zeilen) == 10
    assert all(isinstance(w, str) for z in zeilen for w in z)
    assert zeilen[0][0] == "001"
    assert zeilen[0][3] == "14.03.2012"  # Datum wie in Excel angezeigt


def test_spaltenauswahl_setzen() -> None:
    liste = Liste("B")
    liste.laden(FIX / "schueler_b_semikolon_cp1252.csv")
    assert liste.spalten_auswahl() == [KEINE, *liste.tabelle.spalten]
    liste.namen_setzen(voll=None, vorname="Vorname", nachname=KEINE)
    assert liste.namen == Namensspalten(vorname="Vorname")
    liste.zusatz_setzen(klasse=KEINE, geburtsdatum="Geburtsdatum", email="E-Mail")
    assert liste.zusatz == Zusatzspalten(geburtsdatum="Geburtsdatum", email="E-Mail")


def test_neu_laden_mit_optionen() -> None:
    liste = Liste("B")
    liste.laden(FIX / "mit_titelzeilen.csv")
    assert liste.namen.art == "keine"
    liste.optionen_setzen(Einleseoptionen(kopfzeile=4))
    assert liste.namen == Namensspalten(vorname="Vorname", nachname="Nachname")
    assert liste.tabelle.zeilennummern[0] == 5


def test_auswahl_bleibt_beim_neu_laden_wenn_moeglich() -> None:
    liste = Liste("B")
    liste.laden(FIX / "schueler_b_semikolon_cp1252.csv")
    liste.zusatz_setzen(klasse=KEINE, geburtsdatum=KEINE, email=KEINE)
    liste.optionen_setzen(Einleseoptionen(kodierung="cp1252"))
    assert liste.zusatz == Zusatzspalten()  # eigene Wahl bleibt erhalten


def test_kodierung_und_trennzeichen_auswahl() -> None:
    assert KODIERUNGEN["automatisch"] is None
    assert KODIERUNGEN["Mac (mac_roman)"] == "mac_roman"
    assert TRENNZEICHEN["Tabulator"] == "\t"


def test_warnungen_ohne_zellinhalte() -> None:
    liste = Liste("A")
    liste.laden(FIX / "webuntis_a.csv")
    assert liste.warnungen() == []
    liste.namen_setzen(voll=None, vorname="foreName", nachname="name")
    warnungen = liste.warnungen()
    assert any("Kurz" in w for w in warnungen)


def test_lesefehler_verstaendlich(tmp_path: Path) -> None:
    with pytest.raises(EingabeFehler, match="nicht gefunden"):
        Liste("A").laden(tmp_path / "fehlt.xlsx")


def _sitzung() -> Sitzung:
    s = Sitzung()
    s.a.laden(FIX / "schueler_a.xlsx")
    s.b.laden(FIX / "schueler_b_semikolon_cp1252.csv")
    return s


def test_ausgabe_vorschlag() -> None:
    s = _sitzung()
    assert s.ausgabe_vorschlag() == FIX / "schueler_a_zusammengefuehrt.xlsx"


def test_pruefen_vor_dem_lauf(tmp_path: Path) -> None:
    s = Sitzung()
    fehler = s.pruefen_vor_lauf()
    assert any("Liste A" in f for f in fehler) and any("Liste B" in f for f in fehler)
    s = _sitzung()
    s.ausgabe = None
    assert any("Ergebnisdatei" in f for f in s.pruefen_vor_lauf())
    s.ausgabe = FIX / "schueler_a.xlsx"
    assert any("Eingabedatei" in f for f in s.pruefen_vor_lauf())
    s.ausgabe = tmp_path / "e.csv"
    assert any(".xlsx" in f for f in s.pruefen_vor_lauf())
    s.ausgabe = tmp_path / "e.xlsx"
    s.a.namen_setzen(voll=KEINE, vorname=KEINE, nachname=KEINE)
    assert any("Namensspalte" in f and "Liste A" in f for f in s.pruefen_vor_lauf())
    s.a.namen_setzen(voll="Name", vorname=None, nachname=None)
    s.pruefen, s.sicher = 95, 90
    assert any("Schwelle" in f for f in s.pruefen_vor_lauf())
    s.pruefen = 70
    assert s.pruefen_vor_lauf() == []


def test_ausfuehren_schreibt_ergebnis(tmp_path: Path) -> None:
    s = _sitzung()
    s.ausgabe = tmp_path / "e.xlsx"
    s.sortierung = "status"
    s.kandidaten = False
    meldungen: list[float] = []
    ergebnis = s.ausfuehren(lambda _t, anteil: meldungen.append(anteil))
    assert (tmp_path / "e.xlsx").exists()
    assert meldungen and meldungen[-1] == 1.0
    assert ergebnis.einstellungen.sortierung == "status"
    assert openpyxl.load_workbook(tmp_path / "e.xlsx").sheetnames == ["Zusammengeführt", "Protokoll"]
    text = s.zusammenfassung(ergebnis)
    assert "Sicher" in text and "28" in text


def test_ausfuehren_vorhandene_datei_nur_mit_erlaubnis(tmp_path: Path) -> None:
    s = _sitzung()
    s.ausgabe = tmp_path / "e.xlsx"
    s.ausgabe.write_bytes(b"alt")
    with pytest.raises(Exception, match="existiert bereits"):
        s.ausfuehren(None)
    s.ausfuehren(None, ueberschreiben=True)
    assert openpyxl.load_workbook(s.ausgabe).sheetnames[0] == "Zusammengeführt"
