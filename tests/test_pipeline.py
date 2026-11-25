"""Ende-zu-Ende-Tests der Bibliotheksfunktionen mit den synthetischen Testdateien."""

from __future__ import annotations

from pathlib import Path

import pytest

from namematch.columns import Namensspalten, Zusatzspalten
from namematch.errors import AusgabeFehler, SpaltenFehler
from namematch.io import Einleseoptionen, einlesen
from namematch.matcher import Status
from namematch.pipeline import Spaltenwahl, abgleichen, ausfuehren, spalten_vorschlagen
from tests.fixtures import erzeuge_fixtures as fx

FIX = Path(__file__).parent / "fixtures"
fx.daten()  # füllt ERWARTUNG auch für die Zusatzpersonen


def _zuordnung(ergebnis) -> dict[str, tuple[str, str | None]]:
    a, b = ergebnis.tab_a, ergebnis.tab_b
    i_nr, i_id = a.spalte("Nr"), b.spalte("Schüler-ID")
    return {a.zeilen[z.a][i_nr]: (z.status.value, b.zeilen[z.b][i_id] if z.b is not None else None)
            for z in ergebnis.abgleich.zeilen_a}


@pytest.mark.parametrize("datei_b", ["schueler_b_semikolon_cp1252.csv", "schueler_b_komma_utf8.csv",
                                     "schueler_b_tab_utf8bom.csv", "schueler_b.xlsx", "schueler_b.xls"])
def test_erwartete_zuordnung(datei_b: str) -> None:
    ergebnis = ausfuehren(FIX / "schueler_a.xlsx", FIX / datei_b, ausgabe=None)
    ist = _zuordnung(ergebnis)
    for nr, (status, b_id) in fx.ERWARTUNG.items():
        if status == "nicht Sicher":
            assert ist[nr][0] != "Sicher", nr
        elif status == "Nur in A":
            assert ist[nr] == ("Nur in A", None), nr
        else:
            assert ist[nr] == (status, b_id), nr
    i_id = ergebnis.tab_b.spalte("Schüler-ID")
    nur_b = {ergebnis.tab_b.zeilen[z.b][i_id] for z in ergebnis.abgleich.nur_b}
    assert nur_b == fx.NUR_IN_B_ERWARTET


def test_spaltenvorschlag_fixtures() -> None:
    wahl = spalten_vorschlagen(einlesen(FIX / "schueler_a.xlsx"), einlesen(FIX / "schueler_b.xlsx"))
    assert wahl.namen_a == Namensspalten(voll="Name")
    assert wahl.namen_b == Namensspalten(vorname="Vorname", nachname="Nachname")
    assert wahl.merkmale() == {"klasse": ("Klasse", "Klasse"), "geburtsdatum": ("Geburtsdatum", "Geburtsdatum")}


def test_duplikate_im_protokoll() -> None:
    ergebnis = ausfuehren(FIX / "schueler_a.xlsx", FIX / "schueler_b.xlsx", ausgabe=None)
    assert len(ergebnis.duplikate_a) == 1
    nummern = [ergebnis.tab_a.zeilennummern[i] for i in ergebnis.duplikate_a[0]]
    assert nummern == [17, 18]  # zwei „Paul Wagner“ (Zeile 12 ist leer)
    protokoll = {(z.eintrag, z.wert) for z in ergebnis.protokoll()}
    assert ("Zeilen 17, 18", "Paul Wagner") in protokoll
    assert ("Schwelle Sicher (ab)", 90) in protokoll
    assert ("Anzahl „Nur in B“", 2) in protokoll


def test_gemischte_formate_und_nur_vornamen() -> None:
    ergebnis = ausfuehren(FIX / "gemischt_teilnehmer.csv", FIX / "schueler_b.xlsx", ausgabe=None)
    status = [z.status for z in ergebnis.abgleich.zeilen_a]
    assert status == [Status.MEHRDEUTIG, Status.SICHER, Status.SICHER, Status.SICHER]

    ergebnis2 = ausfuehren(FIX / "nur_vornamen.csv", FIX / "schueler_b.xlsx", ausgabe=None)
    for zeile in ergebnis2.abgleich.zeilen_a:
        assert zeile.status in (Status.PRUEFEN, Status.MEHRDEUTIG, Status.NUR_A)
        assert zeile.score is None or zeile.score < 90


def test_titelzeilen() -> None:
    ergebnis = ausfuehren(FIX / "schueler_a.xlsx", FIX / "mit_titelzeilen.csv", ausgabe=None,
                          optionen_b=Einleseoptionen(kopfzeile=4))
    assert ergebnis.zaehlung()[Status.SICHER] == 2  # Max Mustermann, Lisa Schneider


def test_spaltenwahl_fehler() -> None:
    a, b = einlesen(FIX / "schueler_a.xlsx"), einlesen(FIX / "schueler_b.xlsx")
    with pytest.raises(SpaltenFehler, match="keine Namensspalte"):
        abgleichen(a, b, Spaltenwahl(Namensspalten(), Namensspalten(voll="Vorname")))
    with pytest.raises(SpaltenFehler, match="„Gibtsnicht“"):
        abgleichen(a, b, Spaltenwahl(Namensspalten(voll="Name"), Namensspalten(voll="Vorname"),
                                     Zusatzspalten(klasse="Gibtsnicht")))


def test_ausgabe_darf_nicht_eingabe_sein(tmp_path: Path) -> None:
    kopie = tmp_path / "a.xlsx"
    kopie.write_bytes((FIX / "schueler_a.xlsx").read_bytes())
    with pytest.raises(AusgabeFehler, match="Eingabedatei A"):
        ausfuehren(kopie, FIX / "schueler_b.xlsx", ausgabe=kopie, ueberschreiben=True)


def test_fortschritt() -> None:
    meldungen = []
    ausfuehren(FIX / "schueler_a.xlsx", FIX / "schueler_b.xlsx", ausgabe=None,
               fortschritt=lambda text, anteil: meldungen.append(anteil))
    assert meldungen[0] == 0.0 and meldungen[-1] == 1.0
    assert meldungen == sorted(meldungen)
