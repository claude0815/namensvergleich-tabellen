"""Tests der Plausibilitätsprüfung von Namensspalten und Ergebnis (Warnungen ohne Zellinhalte)."""

from __future__ import annotations

from pathlib import Path

from namematch.columns import Namensspalten, namensspalten_pruefen
from namematch.io import Tabelle


def _tab(spalten: list[str], zeilen: list[list]) -> Tabelle:
    return Tabelle(quelle=Path("x.csv"), dateityp="csv", spalten=spalten, zeilen=zeilen,
                   zeilennummern=list(range(2, 2 + len(zeilen))))


NORMAL = [["Max", "Mustermann"], ["Anna", "Schulz"], ["Jens", "Meier"], ["Lisa", "Schneider"],
          ["Ludwig", "van Beethoven"], ["Sabine", "Müller-Lang"]]


def test_normale_namen_ohne_warnung() -> None:
    tab = _tab(["Vorname", "Nachname"], NORMAL)
    assert namensspalten_pruefen(tab, Namensspalten(vorname="Vorname", nachname="Nachname"), "A") == []
    voll = _tab(["Name"], [[f"{n}, {v}"] for v, n in NORMAL])
    assert namensspalten_pruefen(voll, Namensspalten(voll="Name"), "B") == []


def test_kurzname_statt_nachname() -> None:
    tab = _tab(["foreName", "name"], [["Max", "MustMax"], ["Anna", "SchuAnn"], ["Jens", "MeieJen"],
                                      ["Lisa", "SchnLis"], ["Paul", "WagnPau"]])
    warnungen = namensspalten_pruefen(tab, Namensspalten(vorname="foreName", nachname="name"), "A")
    assert any("„name“" in w and "Kurz" in w for w in warnungen)


def test_benutzername_mit_punkt() -> None:
    tab = _tab(["Vorname", "Login"], [["Max", "max.mustermann"], ["Anna", "anna.schulz"], ["Jens", "jens.meier"]])
    warnungen = namensspalten_pruefen(tab, Namensspalten(vorname="Vorname", nachname="Login"), "A")
    assert any("„Login“" in w for w in warnungen)


def test_kennungen_mit_ziffern() -> None:
    tab = _tab(["Vorname", "ID"], [["Max", "10234"], ["Anna", "10235"], ["Jens", "10236"]])
    warnungen = namensspalten_pruefen(tab, Namensspalten(vorname="Vorname", nachname="ID"), "A")
    assert any("Ziffern" in w for w in warnungen)


def test_ueberwiegend_ein_wort() -> None:
    tab = _tab(["Name"], [["Max"], ["Anna"], ["Jens"], ["Lisa Schneider"]])
    warnungen = namensspalten_pruefen(tab, Namensspalten(voll="Name"), "B")
    assert any("nur ein Wort" in w for w in warnungen)


def test_viele_leere_namen() -> None:
    tab = _tab(["Vorname", "Nachname"], [["Max", "Mustermann"], [None, None], [None, None], ["Anna", "Schulz"]])
    warnungen = namensspalten_pruefen(tab, Namensspalten(vorname="Vorname", nachname="Nachname"), "A")
    assert any("leer" in w for w in warnungen)


def test_warnungen_ohne_zellinhalte() -> None:
    tab = _tab(["foreName", "name"], [["Max", "MustMax"], ["Anna", "SchuAnn"], ["Jens", "10236"]])
    text = " ".join(namensspalten_pruefen(tab, Namensspalten(vorname="foreName", nachname="name"), "A"))
    for inhalt in ("Max", "MustMax", "Anna", "SchuAnn", "Jens", "10236"):
        assert inhalt not in text
