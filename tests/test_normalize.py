"""Tests für die Namensnormalisierung (nur synthetische Namen)."""

from __future__ import annotations

import datetime as dt

import pytest

from namematch.config import Einstellungen
from namematch.normalize import (
    Art,
    Normalisierer,
    Spitznamen,
    datum_normalisieren,
    email_normalisieren,
    falten,
    klasse_normalisieren,
)


@pytest.fixture()
def norm() -> Normalisierer:
    return Normalisierer.aus_einstellungen(Einstellungen())


# --- Grundform ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        ("Müller", "mueller"),
        ("MUELLER", "mueller"),
        ("Strauß", "strauss"),
        ("José", "jose"),
        ("Renée", "renee"),
        ("Ærø", "aero"),
        ("Łukasz", "lukasz"),
        ("Zoë", "zoe"),
        # zerlegte Umlaute (z. B. aus macOS-Dateinamen): u + Trema
        ("Müller", "mueller"),
    ],
)
def test_falten(roh: str, erwartet: str) -> None:
    assert falten(roh) == erwartet


# --- Voller Name in einer Spalte ----------------------------------------------

def test_vorname_nachname(norm: Normalisierer) -> None:
    n = norm.voller_name("Max Mustermann")
    assert n.art is Art.VOLL
    assert n.vorname == ("max",)
    assert n.nachname == ("mustermann",)
    assert n.reihenfolge_sicher is False
    assert n.alternativ == (("mustermann",), ("max",))


def test_leerzeichen_und_gross_klein(norm: Normalisierer) -> None:
    n = norm.voller_name("  max    MUSTERMANN ")
    assert (n.vorname, n.nachname) == (("max",), ("mustermann",))


def test_nachname_komma_vorname(norm: Normalisierer) -> None:
    n = norm.voller_name("Mustermann, Max")
    assert n.art is Art.VOLL
    assert (n.vorname, n.nachname) == (("max",), ("mustermann",))
    assert n.reihenfolge_sicher is True


def test_titel_werden_entfernt(norm: Normalisierer) -> None:
    for roh in ("Dr. Max Mustermann", "Prof. Dr. Max Mustermann", "Herr Max Mustermann",
                "Dipl.-Ing. Max Mustermann", "Max Mustermann jun.", "Frau Dr.med. Max Mustermann"):
        n = norm.voller_name(roh)
        assert (n.vorname, n.nachname) == (("max",), ("mustermann",)), roh


def test_jun_ohne_punkt_ist_kein_titel(norm: Normalisierer) -> None:
    n = norm.voller_name("Jun Tanaka")
    assert n.vorname == ("jun",)


def test_titel_liste_konfigurierbar() -> None:
    norm = Normalisierer.aus_einstellungen(Einstellungen(titel=("stud.",)))
    assert norm.voller_name("stud. Max Mustermann").vorname == ("max",)
    assert norm.voller_name("Dr. Max Mustermann").vorname == ("dr", "max")


def test_umlaute_gleich_umschrift(norm: Normalisierer) -> None:
    assert norm.voller_name("Dr. Jürgen Müller").teile == norm.voller_name("Juergen Mueller").teile


def test_doppelname_mit_bindestrich(norm: Normalisierer) -> None:
    n = norm.voller_name("Sabine Müller-Lang")
    assert n.vorname == ("sabine",)
    assert n.nachname == ("mueller", "lang")


def test_doppelvorname(norm: Normalisierer) -> None:
    n = norm.voller_name("Anna-Lena Schulz")
    assert n.vorname == ("anna", "lena")
    assert n.nachname == ("schulz",)
    n2 = norm.voller_name("Anna Maria Schulz")
    assert n2.vorname == ("anna", "maria")
    assert n2.nachname == ("schulz",)


def test_namenszusatz_gehoert_zum_nachnamen(norm: Normalisierer) -> None:
    n = norm.voller_name("Ludwig van Beethoven")
    assert n.vorname == ("ludwig",)
    assert n.nachname == ("beethoven",)
    assert n.zusaetze == ("van",)
    n2 = norm.voller_name("Beethoven, Ludwig van")
    assert (n2.vorname, n2.nachname, n2.zusaetze) == (("ludwig",), ("beethoven",), ("van",))
    n3 = norm.voller_name("van Beethoven, Ludwig")
    assert (n3.vorname, n3.nachname, n3.zusaetze) == (("ludwig",), ("beethoven",), ("van",))


def test_zusatz_am_ende_ist_nachname(norm: Normalisierer) -> None:
    # „Le“ ist hier der Nachname, kein Zusatz
    n = norm.voller_name("Minh Le")
    assert n.nachname == ("le",)
    assert n.zusaetze == ()


def test_apostroph(norm: Normalisierer) -> None:
    assert norm.voller_name("Sean O'Brien").nachname == ("obrien",)


def test_nur_ein_wort(norm: Normalisierer) -> None:
    n = norm.voller_name("Anna")
    assert n.art is Art.EINZELN
    assert n.teile == ("anna",)


def test_leer(norm: Normalisierer) -> None:
    assert norm.voller_name("").art is Art.LEER
    assert norm.voller_name("   ").art is Art.LEER
    assert norm.voller_name(None).art is Art.LEER
    assert norm.voller_name("Dr.").art is Art.LEER


def test_komma_nur_nachname(norm: Normalisierer) -> None:
    assert norm.voller_name("Mustermann,").art is Art.NACHNAME


# --- Getrennte Spalten --------------------------------------------------------

def test_getrennt(norm: Normalisierer) -> None:
    n = norm.getrennt("Max", "Mustermann")
    assert n.art is Art.VOLL
    assert n.reihenfolge_sicher is True
    assert (n.vorname, n.nachname) == (("max",), ("mustermann",))


def test_getrennt_mit_zusatz_und_titel(norm: Normalisierer) -> None:
    n = norm.getrennt("Dr. Ludwig", "van Beethoven")
    assert (n.vorname, n.nachname, n.zusaetze) == (("ludwig",), ("beethoven",), ("van",))


def test_getrennt_nur_vorname(norm: Normalisierer) -> None:
    n = norm.getrennt("Anna", "")
    assert n.art is Art.VORNAME
    assert n.teile == ("anna",)


def test_getrennt_nur_nachname(norm: Normalisierer) -> None:
    assert norm.getrennt(None, "Schulz").art is Art.NACHNAME


def test_spalte_nur_vorname(norm: Normalisierer) -> None:
    assert norm.nur_vorname("Anna").art is Art.VORNAME
    assert norm.nur_nachname("Schulz").art is Art.NACHNAME
    assert norm.nur_vorname("").art is Art.LEER


# --- Spitznamen ---------------------------------------------------------------

def test_spitznamen_standardliste() -> None:
    sp = Spitznamen.laden(Einstellungen().spitznamen_datei)
    assert sp.gleichwertig(("alex",), ("alexander",))
    assert sp.gleichwertig(("kaethe",), ("katharina",))
    assert not sp.gleichwertig(("alexander",), ("alexandra",))
    assert not sp.gleichwertig(("anna",), ("anna",))  # gleich ist nicht „Kurzform“


def test_spitznamen_eigene_datei(tmp_path) -> None:
    datei = tmp_path / "spitz.txt"
    datei.write_text("# Kommentar\nBeppo = Josef\n\n", encoding="utf-8")
    sp = Spitznamen.laden(datei)
    assert sp.gleichwertig(("beppo",), ("josef",))
    assert sp.erweiterungen("beppo") == {"josef"}


# --- Zusatzmerkmale -----------------------------------------------------------

@pytest.mark.parametrize("roh", ["7b", "7 b", "07B", " 7B ", "Klasse 7b", "7-b", "7.b"])
def test_klasse(roh: str) -> None:
    assert klasse_normalisieren(roh) == "7b"


def test_klasse_zahl_und_leer() -> None:
    assert klasse_normalisieren(7) == "7"
    assert klasse_normalisieren(7.0) == "7"
    assert klasse_normalisieren("") is None
    assert klasse_normalisieren(None) is None
    assert klasse_normalisieren("10a") == "10a"


@pytest.mark.parametrize(
    "roh",
    ["03.05.2010", "3.5.2010", "2010-05-03", "03/05/2010", "03-05-2010", "03.05.10",
     "2010-05-03 00:00:00", dt.date(2010, 5, 3), dt.datetime(2010, 5, 3), 40301, 40301.0],
)
def test_datum(roh) -> None:
    assert datum_normalisieren(roh) == dt.date(2010, 5, 3)


def test_datum_ungueltig() -> None:
    assert datum_normalisieren("31.02.2010") is None
    assert datum_normalisieren("unbekannt") is None
    assert datum_normalisieren("") is None
    assert datum_normalisieren(None) is None


def test_email() -> None:
    assert email_normalisieren(" Max.Mustermann@Example.ORG ") == "max.mustermann@example.org"
    assert email_normalisieren("mailto:a@b.de") == "a@b.de"
    assert email_normalisieren("") is None
