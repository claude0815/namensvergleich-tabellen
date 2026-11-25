"""Tests für Standardwerte und das Laden der TOML-Einstellungen."""

from __future__ import annotations

from pathlib import Path

import pytest

from namematch.config import Einstellungen, laden
from namematch.errors import KonfigurationsFehler

PROJEKT = Path(__file__).parent.parent


def test_standardwerte() -> None:
    e = laden()
    assert (e.schwelle_sicher, e.schwelle_pruefen, e.mehrdeutig_abstand) == (90, 70, 5)
    assert e.gewicht_nachname > e.gewicht_vorname
    assert (e.bonus_klasse, e.bonus_geburtsdatum, e.abzug_geburtsdatum) == (5, 10, 10)
    assert e.deckel_teilname == 80
    assert e.spitznamen_datei.exists()


def test_beispieldatei_entspricht_standard() -> None:
    assert laden(PROJEKT / "einstellungen.beispiel.toml") == Einstellungen()


def test_werte_aus_datei(tmp_path: Path) -> None:
    datei = tmp_path / "e.toml"
    (tmp_path / "spitz.txt").write_text("beppo = josef\n", encoding="utf-8")
    datei.write_text(
        '[schwellen]\nsicher = 95\npruefen = 60\n[gewichtung]\nvorname = 1\nnachname = 3\n'
        '[normalisierung]\ntitel = ["stud."]\nspitznamen_datei = "spitz.txt"\n'
        '[farben]\nnur_a = "#FF0000"\n[ausgabe]\nsortierung = "status"\nkandidaten = false\n',
        encoding="utf-8",
    )
    e = laden(datei)
    assert (e.schwelle_sicher, e.schwelle_pruefen) == (95, 60)
    assert (e.gewicht_vorname, e.gewicht_nachname) == (1.0, 3.0)
    assert e.titel == ("stud.",)
    assert e.spitznamen_datei == tmp_path / "spitz.txt"
    assert e.farben.nur_a == "FF0000"
    assert e.sortierung == "status" and e.kandidaten_blatt is False


def test_ueberschreiben_hat_vorrang(tmp_path: Path) -> None:
    datei = tmp_path / "e.toml"
    datei.write_text("[schwellen]\nsicher = 95\n", encoding="utf-8")
    assert laden(datei, schwelle_sicher=92).schwelle_sicher == 92
    assert laden(datei, schwelle_sicher=None).schwelle_sicher == 95


@pytest.mark.parametrize(
    ("inhalt", "meldung"),
    [
        ("[schwellen]\nsicher = 60\npruefen = 70\n", "Schwellen"),
        ("[schwellen]\nsicher = \"neunzig\"\n", "ganze Zahl"),
        ("[schwelen]\nsicher = 90\n", "Unbekannter Abschnitt"),
        ("[schwellen]\nsichr = 90\n", "Unbekannte Einstellung"),
        ("[farben]\nsicher = \"grün\"\n", "Hex"),
        ("[farben]\nlila = \"FF00FF\"\n", "unbekannte Farbe"),
        ("[ausgabe]\nsortierung = \"zufall\"\n", "Sortierung"),
        ("[gewichtung]\nvorname = 0\nnachname = 0\n", "Gewichte"),
        ("[normalisierung]\nspitznamen = \"ja\"\n", "true oder false"),
        ("das ist kein toml", "TOML"),
    ],
)
def test_ungueltige_einstellungen(tmp_path: Path, inhalt: str, meldung: str) -> None:
    datei = tmp_path / "e.toml"
    datei.write_text(inhalt, encoding="utf-8")
    with pytest.raises(KonfigurationsFehler, match=meldung):
        laden(datei)


def test_datei_fehlt(tmp_path: Path) -> None:
    with pytest.raises(KonfigurationsFehler, match="nicht gefunden"):
        laden(tmp_path / "fehlt.toml")
