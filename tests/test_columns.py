"""Tests für die Erkennung von Namens- und Zusatzspalten anhand der Überschriften."""

from __future__ import annotations

import pytest

from namematch.columns import Namensspalten, vorschlagen


def test_datei_a_voller_name() -> None:
    v = vorschlagen(["Nr", "Name", "Klasse", "Geburtsdatum", "PLZ", "Spalte_6", "Bemerkung", "Telefon"])
    assert v.namen == Namensspalten(voll="Name")
    assert v.namen.art == "voll"
    assert (v.zusatz.klasse, v.zusatz.geburtsdatum, v.zusatz.email) == ("Klasse", "Geburtsdatum", None)


def test_datei_b_getrennt_umgekehrte_reihenfolge() -> None:
    v = vorschlagen(["Schüler-ID", "Nachname", "Vorname", "Klasse", "Geburtsdatum", "Telefon", "E-Mail", "Spalte_8"])
    assert v.namen == Namensspalten(vorname="Vorname", nachname="Nachname")
    assert v.namen.art == "getrennt"
    assert v.zusatz.email == "E-Mail"


def test_name_plus_vorname_ist_nachname() -> None:
    v = vorschlagen(["Name", "Vorname", "Klasse"])
    assert v.namen == Namensspalten(vorname="Vorname", nachname="Name")


@pytest.mark.parametrize(
    ("spalten", "erwartet"),
    [
        (["Vorname", "Klasse"], Namensspalten(vorname="Vorname")),
        (["Familienname", "Ort"], Namensspalten(nachname="Familienname")),
        (["Teilnehmer", "Kurs"], Namensspalten(voll="Teilnehmer")),
        (["Teilnehmer/in", "Kurs"], Namensspalten(voll="Teilnehmer/in")),
        (["First Name", "Last Name"], Namensspalten(vorname="First Name", nachname="Last Name")),
        (["Surname", "Given name"], Namensspalten(vorname="Given name", nachname="Surname")),
        (["Name der Schule", "Schüler"], Namensspalten(voll="Schüler")),
        (["Name, Vorname", "Klasse"], Namensspalten(voll="Name, Vorname")),
        (["Vorname des Kindes", "Nachname des Kindes"],
         Namensspalten(vorname="Vorname des Kindes", nachname="Nachname des Kindes")),
        (["Person"], Namensspalten(voll="Person")),
        (["ID", "Wert"], Namensspalten()),
    ],
)
def test_namensspalten(spalten: list[str], erwartet: Namensspalten) -> None:
    assert vorschlagen(spalten).namen == erwartet


def test_keine_namensspalte() -> None:
    assert vorschlagen(["ID", "Wert"]).namen.art == "keine"


def test_zusatzspalten_englisch_und_varianten() -> None:
    v = vorschlagen(["First Name", "Last Name", "Class", "Date of Birth", "Email"])
    assert (v.zusatz.klasse, v.zusatz.geburtsdatum, v.zusatz.email) == ("Class", "Date of Birth", "Email")
    v2 = vorschlagen(["Name", "Kl.", "geb. am", "Mail"])
    assert (v2.zusatz.klasse, v2.zusatz.geburtsdatum, v2.zusatz.email) == ("Kl.", "geb. am", "Mail")


def test_fremde_spalten_werden_nicht_genommen() -> None:
    v = vorschlagen(["Name", "Klassenlehrer", "Klasse", "E-Mail Eltern", "E-Mail", "Name Erziehungsberechtigte"])
    assert v.namen == Namensspalten(voll="Name")
    assert v.zusatz.klasse == "Klasse"
    assert v.zusatz.email == "E-Mail"


def test_namensspalten_pruefen() -> None:
    with pytest.raises(ValueError):
        Namensspalten(voll="Name", vorname="Vorname")
    assert Namensspalten(vorname="V", nachname="N").spalten() == ["V", "N"]
