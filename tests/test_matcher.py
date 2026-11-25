"""Tests für Scoring, Einstufung und 1:1-Zuordnung (synthetische Namen)."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

import pytest

from namematch.config import Einstellungen
from namematch.matcher import Matcher, Person, Status
from namematch.normalize import Normalisierer, Spitznamen, klasse_normalisieren

E = Einstellungen()
NORM = Normalisierer.aus_einstellungen(E)


def person(index: int, name: str | tuple[str, str], klasse: str | None = None,
           geburtsdatum: dt.date | None = None, email: str | None = None) -> Person:
    """Hilfsfunktion: Person aus vollem Namen oder (Vorname, Nachname)."""
    if isinstance(name, tuple):
        n = NORM.getrennt(*name)
        anzeige = " ".join(name)
    else:
        n = NORM.voller_name(name)
        anzeige = name
    return Person(index=index, zeile=index + 2, name=n, anzeige=anzeige,
                  klasse=klasse_normalisieren(klasse), klasse_original=klasse,
                  geburtsdatum=geburtsdatum, email=email)


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    return Matcher(E, Spitznamen.laden(E.spitznamen_datei))


def abgleich(matcher: Matcher, a: list, b: list):
    return matcher.abgleichen([person(i, x) if not isinstance(x, Person) else x for i, x in enumerate(a)],
                              [person(i, x) if not isinstance(x, Person) else x for i, x in enumerate(b)])


# --- Testfälle aus den Anforderungen --------------------------------------------

def test_voller_name_gegen_zwei_spalten(matcher: Matcher) -> None:
    erg = abgleich(matcher, ["Max Mustermann"], [("Max", "Mustermann")])
    z = erg.zeilen_a[0]
    assert (z.status, z.score, z.b) == (Status.SICHER, 100, 0)


def test_nachname_komma_vorname(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Mustermann, Max"], ["Max Mustermann"]).zeilen_a[0]
    assert (z.status, z.score) == (Status.SICHER, 100)


def test_titel_und_umlaute(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Dr. Jürgen Müller"], ["Juergen Mueller"]).zeilen_a[0]
    assert (z.status, z.score) == (Status.SICHER, 100)


def test_tippfehler_ist_pruefen(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Jens Meier"], ["Jens Meyer"]).zeilen_a[0]
    assert z.status is Status.PRUEFEN
    assert 70 <= z.score < 90


def test_nur_vorname_gedeckelt(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Anna"], ["Anna Schulz"]).zeilen_a[0]
    assert z.status is Status.PRUEFEN
    assert z.score == 80
    assert "nur Vorname verglichen" in z.hinweise


def test_nur_vorname_mehrdeutig(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Anna"], ["Anna Schulz", "Anna Weber"]).zeilen_a[0]
    assert z.status is Status.MEHRDEUTIG
    assert z.b == 0  # deterministisch: bei Gleichstand die frühere Zeile aus B
    assert "2. Kandidat: Anna Weber (80)" in z.hinweise


def test_klasse_loest_mehrdeutigkeit(matcher: Matcher) -> None:
    a = [person(0, "Anna", klasse="6c")]
    b = [person(0, "Anna Weber", klasse="7a"), person(1, "Anna Schulz", klasse="6c")]
    z = matcher.abgleichen(a, b).zeilen_a[0]
    assert z.b == 1
    assert z.status is Status.PRUEFEN
    assert z.score == 85


def test_klasse_abweichend_bleibt_sicher(matcher: Matcher) -> None:
    a = [person(0, "Max Mustermann", klasse="7b")]
    b = [person(0, "Max Mustermann", klasse="8b")]
    z = matcher.abgleichen(a, b).zeilen_a[0]
    assert (z.status, z.score) == (Status.SICHER, 100)
    assert "Klasse abweichend: 7b / 8b" in z.hinweise


def test_doppelname_teilweise(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Sabine Müller-Lang"], ["Sabine Müller"]).zeilen_a[0]
    assert z.status is Status.PRUEFEN


def test_nur_in_a_und_nur_in_b(matcher: Matcher) -> None:
    erg = abgleich(matcher, ["Petra Lang"], ["Tom Becker"])
    assert erg.zeilen_a[0].status is Status.NUR_A
    assert erg.zeilen_a[0].score is None
    assert [z.status for z in erg.nur_b] == [Status.NUR_B]
    assert erg.nur_b[0].b == 0


def test_peter_schmidt_petra_schmitt_nicht_sicher(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Peter Schmidt"], ["Petra Schmitt"]).zeilen_a[0]
    assert z.status is not Status.SICHER


# --- weitere Regeln ------------------------------------------------------------

def test_reihenfolge_ohne_komma(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Mustermann Max"], [("Max", "Mustermann")]).zeilen_a[0]
    assert (z.status, z.score) == (Status.SICHER, 100)


def test_bindestrich_varianten_gleich(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Hans-Peter Müller"], ["Hanspeter Müller"]).zeilen_a[0]
    assert z.status is Status.SICHER


def test_zweiter_vorname_fehlt(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Anna Maria Schulz"], ["Anna Schulz"]).zeilen_a[0]
    assert z.status is Status.PRUEFEN


def test_vertauschte_vor_und_nachnamen_bei_sicherer_reihenfolge(matcher: Matcher) -> None:
    z = abgleich(matcher, [("Max", "Thomas")], [("Thomas", "Max")]).zeilen_a[0]
    assert z.status is not Status.SICHER


def test_kurzform(matcher: Matcher) -> None:
    z = abgleich(matcher, ["Alex Mustermann"], ["Alexander Mustermann"]).zeilen_a[0]
    assert z.status is Status.PRUEFEN
    assert "Kurzform des Vornamens" in z.hinweise


def test_kurzform_abschaltbar() -> None:
    m = Matcher(E, Spitznamen())
    a, b = [person(0, "Kathi Mustermann")], [person(0, "Katharina Mustermann")]
    assert "Kurzform des Vornamens" not in m.abgleichen(a, b).zeilen_a[0].hinweise


def test_strikt_eins_zu_eins_global(matcher: Matcher) -> None:
    # Zeilenweise bekäme A0 den Kandidaten; global gewinnt der exakte Treffer A1.
    erg = abgleich(matcher, ["Jens Meier", "Jens Meyer"], ["Jens Meyer"])
    assert erg.zeilen_a[0].status is Status.NUR_A
    assert erg.zeilen_a[1].b == 0
    assert erg.zeilen_a[1].status is Status.SICHER  # A0 liegt > 5 Punkte darunter
    assert any("Jens Meyer" in h and "bereits" in h for h in erg.zeilen_a[0].hinweise)


def test_jede_b_zeile_hoechstens_einmal(matcher: Matcher) -> None:
    erg = abgleich(matcher, ["Max Mustermann", "Max Mustermann"], ["Max Mustermann"])
    zugeordnet = [z.b for z in erg.zeilen_a if z.b is not None]
    assert zugeordnet == [0]
    assert erg.zeilen_a[0].status is Status.MEHRDEUTIG
    assert erg.zeilen_a[1].status is Status.NUR_A


def test_exakte_duplikate_in_b_sind_mehrdeutig(matcher: Matcher) -> None:
    erg = abgleich(matcher, ["Max Mustermann"], ["Max Mustermann", "Max Mustermann"])
    assert erg.zeilen_a[0].status is Status.MEHRDEUTIG
    assert erg.zeilen_a[0].score == 100
    assert erg.zeilen_a[0].b == 0
    assert [z.b for z in erg.nur_b] == [1]


def test_leerer_name(matcher: Matcher) -> None:
    erg = abgleich(matcher, [""], ["Max Mustermann"])
    assert erg.zeilen_a[0].status is Status.NUR_A
    assert "kein Name vorhanden" in erg.zeilen_a[0].hinweise


def test_kein_treffer_hinweis_bester_kandidat(matcher: Matcher) -> None:
    erg = abgleich(matcher, ["Petra Lange"], ["Peter Langer"])
    z = erg.zeilen_a[0]
    if z.status is Status.NUR_A:
        assert any(h.startswith("bester Kandidat unter Schwelle") for h in z.hinweise)


# --- Zusatzmerkmale -------------------------------------------------------------

def test_geburtsdatum_hebt_tippfehler_auf_sicher(matcher: Matcher) -> None:
    d = dt.date(2010, 5, 3)
    z = matcher.abgleichen([person(0, "Jens Meier", geburtsdatum=d)],
                           [person(0, "Jens Meyer", geburtsdatum=d)]).zeilen_a[0]
    assert z.status is Status.SICHER


def test_klasse_hebt_tippfehler_nicht_auf_sicher(matcher: Matcher) -> None:
    z = matcher.abgleichen([person(0, "Jens Meier", klasse="8a")],
                           [person(0, "Jens Meyer", klasse="8a")]).zeilen_a[0]
    assert z.status is Status.PRUEFEN


def test_geburtsdatum_abweichend_gibt_abzug(matcher: Matcher) -> None:
    z = matcher.abgleichen([person(0, "Jens Meier", geburtsdatum=dt.date(2010, 5, 3))],
                           [person(0, "Jens Meyer", geburtsdatum=dt.date(2011, 1, 1))]).zeilen_a[0]
    ohne = abgleich(matcher, ["Jens Meier"], ["Jens Meyer"]).zeilen_a[0]
    assert z.score == ohne.score - 10
    assert "Geburtsdatum abweichend" in z.hinweise


def test_email_gleich_gibt_bonus(matcher: Matcher) -> None:
    z = matcher.abgleichen([person(0, "Jens Meier", email="j.m@example.org")],
                           [person(0, "Jens Meyer", email="j.m@example.org")]).zeilen_a[0]
    assert z.status is Status.SICHER


def test_deckel_bleibt_trotz_bonus(matcher: Matcher) -> None:
    d = dt.date(2010, 5, 3)
    z = matcher.abgleichen([person(0, "Anna", klasse="6c", geburtsdatum=d, email="a@x.de")],
                           [person(0, "Anna Schulz", klasse="6c", geburtsdatum=d, email="a@x.de")]).zeilen_a[0]
    assert z.status is Status.PRUEFEN
    assert z.score == 89


def test_zusatzmerkmale_erzeugen_keinen_treffer(matcher: Matcher) -> None:
    d = dt.date(2010, 5, 3)
    z = matcher.abgleichen([person(0, "Max Mustermann", klasse="7b", geburtsdatum=d, email="m@x.de")],
                           [person(0, "Erika Beispiel", klasse="7b", geburtsdatum=d, email="m@x.de")]).zeilen_a[0]
    assert z.status is Status.NUR_A


def test_schwellen_einstellbar() -> None:
    streng = Matcher(replace(E, schwelle_pruefen=85), Spitznamen())
    z = streng.abgleichen([person(0, "Anna")], [person(0, "Anna Schulz")]).zeilen_a[0]
    assert z.status is Status.NUR_A


# --- Kandidaten, Determinismus ---------------------------------------------------

def test_kandidaten_top3(matcher: Matcher) -> None:
    erg = abgleich(matcher, ["Anna Schulz"], ["Anna Schulz", "Anna Schultz", "Anne Schulz", "Hanna Schulze", "Tom Becker"])
    kand = erg.kandidaten[0]
    assert len(kand) == 3
    assert kand[0] == (0, 100)
    assert [s for _, s in kand] == sorted((s for _, s in kand), reverse=True)


def test_deterministisch(matcher: Matcher) -> None:
    a = ["Anna", "Max Mustermann", "Jens Meier", "Anna Schulz", "Petra Lang", "Mustermann, Max"]
    b = ["Anna Weber", "Anna Schulz", "Jens Meyer", "Max Mustermann", "Tom Becker", "Jens Maier"]
    e1, e2 = abgleich(matcher, a, b), abgleich(matcher, a, b)
    assert e1 == e2
    e3 = Matcher(E, Spitznamen.laden(E.spitznamen_datei)).abgleichen(
        [person(i, x) for i, x in enumerate(a)], [person(i, x) for i, x in enumerate(b)])
    assert e3 == e1


def test_fortschritt_callback(matcher: Matcher) -> None:
    meldungen: list[tuple[str, float]] = []
    matcher.abgleichen([person(0, "Anna")], [person(0, "Anna Schulz")],
                       fortschritt=lambda text, anteil: meldungen.append((text, anteil)))
    assert meldungen
    assert all(0.0 <= anteil <= 1.0 for _, anteil in meldungen)


def test_klasse_entscheidet_bei_gleichen_namen_in_a(matcher: Matcher) -> None:
    a = [person(0, "Paul Wagner", klasse="5a"), person(1, "Paul Wagner", klasse="6b")]
    b = [person(0, "Paul Wagner", klasse="6b")]
    erg = matcher.abgleichen(a, b)
    assert erg.zeilen_a[1].b == 0
    assert erg.zeilen_a[1].status is Status.MEHRDEUTIG  # gleicher Name zweimal → Sichtprüfung
    assert erg.zeilen_a[0].status is Status.NUR_A
