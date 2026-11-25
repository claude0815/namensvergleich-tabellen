"""Scoring (0–100), Einstufung und globale 1:1-Zuordnung.

Ablauf:
1. Vorauswahl: schneller Vergleich aller Paare mit ``rapidfuzz.process.cdist`` (C, mehrere Kerne),
   damit auch 5.000 × 5.000 Zeilen in Sekunden verarbeitet werden.
2. Bewertung: genauer Score für die Kandidatenpaare (Vor-/Nachname getrennt, Tippfehler,
   Teilinformation, Kurzformen, Zusatzmerkmale).
3. Zuordnung: gierig nach höchstem Score („Best-First“), jede Zeile aus A und B höchstens einmal.
4. Einstufung: Sicher / Prüfen / Mehrdeutig / Nur in A / Nur in B mit Hinweisen.

Alles ist deterministisch: Gleichstände werden immer nach Zeilenreihenfolge aufgelöst.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

from .config import Einstellungen
from .normalize import Art, Name, Spitznamen

log = logging.getLogger(__name__)

#: Fortschritts-Callback: (Beschreibung, Anteil 0.0–1.0)
Fortschritt = Callable[[str, float], None]

VORFILTER_SCHWELLE = 50          # Mindestähnlichkeit in der Vorauswahl
VORFILTER_TEILE_SCHWELLE = 70    # Mindestähnlichkeit einzelner Namensteile in der Vorauswahl
MAX_KANDIDATEN_JE_ZEILE = 100    # höchstens so viele B-Kandidaten je A-Zeile genau bewerten
ANTEIL_TEILE = 0.75              # Gewicht Vor-/Nachnamen-Vergleich ggü. reihenfolgeunabhängigem Gesamtvergleich
_BLOCKGROESSE = 1000


class Status(StrEnum):
    """Einstufung einer Ergebniszeile."""

    SICHER = "Sicher"
    PRUEFEN = "Prüfen"
    MEHRDEUTIG = "Mehrdeutig"
    NUR_A = "Nur in A"
    NUR_B = "Nur in B"


@dataclass(frozen=True)
class Person:
    """Vergleichsdaten einer Zeile. ``anzeige`` erscheint nur in der Ergebnisdatei, nie im Log."""

    index: int
    name: Name
    anzeige: str
    zeile: int = 0
    klasse: str | None = None
    klasse_original: str | None = None
    geburtsdatum: dt.date | None = None
    email: str | None = None


@dataclass(frozen=True)
class Bewertung:
    """Score eines Paares (A, B)."""

    score: int
    namensscore: int
    teilweise: bool
    hinweise: tuple[str, ...] = ()
    rang: float = 0.0  # ungedeckelter Wert, nur zur Auflösung von Gleichständen


@dataclass
class Zeilenergebnis:
    """Eine Zeile der Ergebnistabelle."""

    status: Status
    a: int | None = None
    b: int | None = None
    score: int | None = None
    hinweise: list[str] = field(default_factory=list)


@dataclass
class Abgleich:
    """Gesamtergebnis: eine Zeile je Person aus A (in A-Reihenfolge) plus nicht zugeordnete B-Zeilen."""

    zeilen_a: list[Zeilenergebnis]
    nur_b: list[Zeilenergebnis]
    kandidaten: dict[int, list[tuple[int, int]]]  # A-Index → [(B-Index, Score)] (Top 3)
    anzahl_paare: int = 0

    def zaehlung(self) -> dict[Status, int]:
        """Anzahl Zeilen je Status."""
        anzahl = {status: 0 for status in Status}
        for zeile in self.zeilen_a:
            anzahl[zeile.status] += 1
        anzahl[Status.NUR_B] += len(self.nur_b)
        return anzahl


@dataclass(frozen=True)
class _Namensvergleich:
    score: float
    gleich: bool              # nach Normalisierung identisch
    teilweise: str | None     # Hinweis, wenn nur ein Namensteil verglichen wurde
    kurzform: bool


def _runden(wert: float) -> int:
    """Kaufmännisch runden (deterministisch, ohne Banker's Rounding)."""
    return int(math.floor(wert + 0.5))


def _keine_meldung(_text: str, _anteil: float) -> None:
    return None


class Matcher:
    """Vergleicht Personen aus A und B und ordnet sie einander zu."""

    def __init__(self, einstellungen: Einstellungen, spitznamen: Spitznamen | None = None) -> None:
        self.e = einstellungen
        self.spitznamen = spitznamen or Spitznamen()
        summe = einstellungen.gewicht_vorname + einstellungen.gewicht_nachname
        self._gv = einstellungen.gewicht_vorname / summe
        self._gn = einstellungen.gewicht_nachname / summe
        self._teil_cache: dict[tuple[tuple[str, ...], tuple[str, ...], bool], tuple[float, str]] = {}
        self._namen_cache: dict[tuple[Name, Name], _Namensvergleich] = {}

    # --- Namensvergleich ----------------------------------------------------------

    def _teil(self, a: tuple[str, ...], b: tuple[str, ...], kurzform: bool) -> tuple[float, str]:
        """Vergleicht einen Namensteil (Vorname oder Nachname). Liefert (Score, Art)."""
        schluessel = (a, b, kurzform)
        treffer = self._teil_cache.get(schluessel)
        if treffer is not None:
            return treffer
        if not a or not b:
            ergebnis = (0.0, "leer")
        else:
            ja, jb = "".join(a), "".join(b)
            if ja == jb:
                ergebnis = (100.0, "gleich")
            else:
                score = Levenshtein.normalized_similarity(ja, jb) * 100
                art = "aehnlich"
                ma, mb = set(a), set(b)
                if (ma <= mb or mb <= ma) and self.e.score_namensteil > score:
                    score, art = float(self.e.score_namensteil), "teilweise"
                if kurzform and self.e.score_kurzform > score and self.spitznamen.gleichwertig(a, b):
                    score, art = float(self.e.score_kurzform), "kurzform"
                ergebnis = (score, art)
        self._teil_cache[schluessel] = ergebnis
        return ergebnis

    @staticmethod
    def _lesarten(name: Name) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
        """(Vorname, Nachname)-Lesarten eines vollen Namens; zwei bei unsicherer Reihenfolge."""
        lesarten = [(name.vorname, name.nachname)]
        if not name.reihenfolge_sicher and name.alternativ is not None:
            lesarten.append(name.alternativ)
        return lesarten

    def _namen(self, a: Name, b: Name) -> _Namensvergleich:
        schluessel = (a, b)
        treffer = self._namen_cache.get(schluessel)
        if treffer is None:
            treffer = self._namen_berechnen(a, b)
            self._namen_cache[schluessel] = treffer
        return treffer

    def _namen_berechnen(self, a: Name, b: Name) -> _Namensvergleich:
        if a.art is Art.LEER or b.art is Art.LEER:
            return _Namensvergleich(0.0, False, None, False)

        if a.art is Art.VOLL and b.art is Art.VOLL:
            beste, kurz = -1.0, False
            for vor_a, nach_a in self._lesarten(a):
                for vor_b, nach_b in self._lesarten(b):
                    s_vor, art_vor = self._teil(vor_a, vor_b, kurzform=True)
                    s_nach, art_nach = self._teil(nach_a, nach_b, kurzform=False)
                    if art_vor == "gleich" and art_nach == "gleich":
                        return _Namensvergleich(100.0, True, None, False)
                    teile = self._gv * s_vor + self._gn * s_nach
                    if teile > beste:
                        beste, kurz = teile, art_vor == "kurzform"
            gesamt = fuzz.token_sort_ratio(" ".join(a.teile), " ".join(b.teile))
            roh = ANTEIL_TEILE * beste + (1 - ANTEIL_TEILE) * gesamt
            return _Namensvergleich(roh, False, None, kurz)

        # Mindestens eine Seite hat nur einen Namensteil → nur diesen vergleichen, Score deckeln.
        if a.art is Art.VOLL:
            teil, voll = b, a
        else:
            teil, voll = a, b
        ziele: list[tuple[tuple[str, ...], str]] = []
        if voll.art is Art.VOLL:
            if teil.art in (Art.VORNAME, Art.EINZELN):
                ziele += [(vor, "vor") for vor, _ in self._lesarten(voll)]
            if teil.art in (Art.NACHNAME, Art.EINZELN):
                ziele += [(nach, "nach") for _, nach in self._lesarten(voll)]
        else:
            if Art.VORNAME in (teil.art, voll.art):
                rolle = "vor"
            elif Art.NACHNAME in (teil.art, voll.art):
                rolle = "nach"
            else:
                rolle = "einzeln"
            ziele.append((voll.einzeln, rolle))
        beste, beste_rolle, beste_art = -1.0, "einzeln", ""
        for tokens, rolle in ziele:
            score, art = self._teil(teil.einzeln, tokens, kurzform=rolle in ("vor", "einzeln"))
            if score > beste:
                beste, beste_rolle, beste_art = score, rolle, art
        hinweis = {
            "vor": "nur Vorname verglichen",
            "nach": "nur Nachname verglichen",
        }.get(beste_rolle, "nur ein Namensteil verglichen")
        return _Namensvergleich(min(beste, float(self.e.deckel_teilname)), False, hinweis, beste_art == "kurzform")

    # --- Paarbewertung -------------------------------------------------------------

    def _stauchen(self, roh: float) -> float:
        """Bildet nicht identische Namen auf höchstens „Sicher − 1“ ab.

        Bis zum Knick (Prüfen-Schwelle + 10) bleibt der Score unverändert, darüber wird er
        gleichmäßig in den Bereich bis „Sicher − 1“ gestaucht. So bleibt die Rangfolge
        ähnlicher Kandidaten erhalten, statt dass alle auf dem Deckel landen.
        """
        oben = self.e.schwelle_sicher - 1
        knick = min(oben, self.e.schwelle_pruefen + 10)
        if roh <= knick:
            return roh
        return knick + (roh - knick) * (oben - knick) / (100 - knick)

    def bewerten(self, a: Person, b: Person) -> Bewertung:
        """Score eines Paares inklusive Zusatzmerkmalen (0–100)."""
        e = self.e
        nv = self._namen(a.name, b.name)
        hinweise: list[str] = []
        if nv.teilweise:
            hinweise.append(nv.teilweise)
        if nv.kurzform:
            hinweise.append("Kurzform des Vornamens")
        obergrenze = e.schwelle_sicher - 1  # „Sicher“ nur bei gleichem Namen (oder zuverlässigem Merkmal)
        basis = 100.0 if nv.gleich else self._stauchen(nv.score)
        bonus_erlaubt = nv.score >= e.min_namensscore_bonus

        # Klasse (unzuverlässig): gleich → kleiner Bonus, abweichend → kein Abzug, nur Hinweis
        bonus_klasse = 0.0
        if a.klasse and b.klasse:
            if a.klasse == b.klasse:
                bonus_klasse = e.bonus_klasse if bonus_erlaubt else 0.0
            else:
                hinweise.append(f"Klasse abweichend: {a.klasse_original} / {b.klasse_original}")

        # Geburtsdatum, E-Mail (zuverlässig): gleich → Bonus, abweichend → Abzug
        bonus_zuverlaessig = 0.0
        for wert_a, wert_b, bonus, abzug, text in (
            (a.geburtsdatum, b.geburtsdatum, e.bonus_geburtsdatum, e.abzug_geburtsdatum, "Geburtsdatum abweichend"),
            (a.email, b.email, e.bonus_email, e.abzug_email, "E-Mail abweichend"),
        ):
            if wert_a is None or wert_b is None:
                continue
            if wert_a == wert_b:
                bonus_zuverlaessig += bonus if bonus_erlaubt else 0.0
            else:
                bonus_zuverlaessig -= abzug
                hinweise.append(text)

        score = basis + bonus_klasse
        if not nv.gleich:
            score = min(score, obergrenze)  # die Klasse allein hebt nie auf „Sicher“
        score += bonus_zuverlaessig
        if nv.teilweise:
            score = min(score, obergrenze)  # Deckel für Teilinformation bleibt
        score = max(0.0, min(100.0, score))
        rang = basis + bonus_klasse + bonus_zuverlaessig  # ohne Deckel, nur für Gleichstände
        return Bewertung(_runden(score), _runden(nv.score), nv.teilweise is not None, tuple(hinweise), rang)

    # --- Vorauswahl ----------------------------------------------------------------

    def _schluessel(self, name: Name) -> str:
        tokens = set(name.teile)
        for token in name.teile:
            tokens |= self.spitznamen.erweiterungen(token)
        return " ".join(sorted(tokens))

    @staticmethod
    def _teilschluessel(name: Name) -> tuple[str, str]:
        if name.art is Art.VOLL:
            return "".join(name.vorname), "".join(name.nachname)
        einzeln = "".join(name.einzeln)
        vor = einzeln if name.art in (Art.VORNAME, Art.EINZELN) else ""
        nach = einzeln if name.art in (Art.NACHNAME, Art.EINZELN) else ""
        return vor, nach

    def _vorauswahl(self, personen_a: Sequence[Person], personen_b: Sequence[Person],
                    melden: Fortschritt) -> list[tuple[int, int]]:
        """Liefert Kandidatenpaare (Position in A, Position in B) für die genaue Bewertung."""
        gueltig_a = [i for i, p in enumerate(personen_a) if p.name.art is not Art.LEER]
        gueltig_b = [j for j, p in enumerate(personen_b) if p.name.art is not Art.LEER]
        if not gueltig_a or not gueltig_b:
            return []
        schluessel_b = [self._schluessel(personen_b[j].name) for j in gueltig_b]
        teile_b = [self._teilschluessel(personen_b[j].name) for j in gueltig_b]
        vor_b = [t[0] for t in teile_b]
        nach_b = [t[1] for t in teile_b]
        leer_vor_b = np.array([not v for v in vor_b])
        leer_nach_b = np.array([not n for n in nach_b])
        spalten_b = np.array(gueltig_b)

        paare: list[tuple[int, int]] = []
        for start in range(0, len(gueltig_a), _BLOCKGROESSE):
            block = gueltig_a[start:start + _BLOCKGROESSE]
            schluessel_a = [self._schluessel(personen_a[i].name) for i in block]
            teile_a = [self._teilschluessel(personen_a[i].name) for i in block]
            matrix = process.cdist(schluessel_a, schluessel_b, scorer=fuzz.token_set_ratio,
                                   score_cutoff=VORFILTER_SCHWELLE, dtype=np.uint8, workers=-1)
            for k, (liste_b, leer_b) in enumerate(((vor_b, leer_vor_b), (nach_b, leer_nach_b))):
                liste_a = [t[k] for t in teile_a]
                teil = process.cdist(liste_a, liste_b, scorer=fuzz.ratio,
                                     score_cutoff=VORFILTER_TEILE_SCHWELLE, dtype=np.uint8, workers=-1)
                teil[np.array([not x for x in liste_a]), :] = 0
                teil[:, leer_b] = 0
                # Teil-Treffer zählen etwas weniger als Treffer im ganzen Namen (Rangfolge)
                np.maximum(matrix, (teil.astype(np.uint16) * 4 // 5).astype(np.uint8), out=matrix)
            for zeile, i in enumerate(block):
                werte = matrix[zeile]
                spalten = np.flatnonzero(werte >= VORFILTER_SCHWELLE)
                if len(spalten) > MAX_KANDIDATEN_JE_ZEILE:
                    reihenfolge = np.argsort(-werte[spalten].astype(np.int16), kind="stable")
                    spalten = np.sort(spalten[reihenfolge[:MAX_KANDIDATEN_JE_ZEILE]])
                paare.extend((i, int(j)) for j in spalten_b[spalten])
            melden("Vorauswahl", 0.4 * min(1.0, (start + len(block)) / len(gueltig_a)))
        return paare

    # --- Zuordnung -----------------------------------------------------------------

    def abgleichen(self, personen_a: Sequence[Person], personen_b: Sequence[Person],
                   fortschritt: Fortschritt | None = None) -> Abgleich:
        """Vergleicht alle Personen und ordnet global 1:1 nach höchstem Score zu."""
        melden = fortschritt or _keine_meldung
        e = self.e
        melden("Vorauswahl", 0.0)
        paare = self._vorauswahl(personen_a, personen_b, melden)
        log.info("Vorauswahl: %d Kandidatenpaare", len(paare))

        bewertungen: dict[tuple[int, int], Bewertung] = {}
        schritt = max(1, len(paare) // 20)
        for nummer, (i, j) in enumerate(paare):
            bewertungen[(i, j)] = self.bewerten(personen_a[i], personen_b[j])
            if nummer % schritt == 0:
                melden("Bewertung", 0.4 + 0.5 * nummer / max(1, len(paare)))
        melden("Zuordnung", 0.9)

        kand_a: dict[int, list[tuple[int, int]]] = {}
        kand_b: dict[int, list[tuple[int, int]]] = {}
        for (i, j), bew in bewertungen.items():
            kand_a.setdefault(i, []).append((bew.score, j))
            kand_b.setdefault(j, []).append((bew.score, i))
        for k, liste in kand_a.items():
            liste.sort(key=lambda x: (-x[0], -bewertungen[(k, x[1])].rang, x[1]))
        for k, liste in kand_b.items():
            liste.sort(key=lambda x: (-x[0], -bewertungen[(x[1], k)].rang, x[1]))

        # Gierig nach höchstem Score; Gleichstand → höherer ungedeckelter Wert (z. B. passende
        # Klasse bei zwei gleichen Namen), dann frühere Zeile in A, dann in B
        reihenfolge = sorted((-bew.score, -bew.rang, i, j) for (i, j), bew in bewertungen.items()
                             if bew.score >= e.schwelle_pruefen)
        zu_b: dict[int, int] = {}
        zu_a: dict[int, int] = {}
        for _minus_score, _minus_rang, i, j in reihenfolge:
            if i not in zu_b and j not in zu_a:
                zu_b[i] = j
                zu_a[j] = i

        zeilen_a = [self._zeile_a(i, personen_a, personen_b, zu_b, bewertungen, kand_a, kand_b)
                    for i in range(len(personen_a))]
        nur_b = [self._zeile_nur_b(j, personen_a, personen_b, kand_b)
                 for j in range(len(personen_b)) if j not in zu_a]
        kandidaten = {i: [(j, s) for s, j in kand_a.get(i, [])[:3]] for i in range(len(personen_a))}
        melden("Fertig", 1.0)
        ergebnis = Abgleich(zeilen_a, nur_b, kandidaten, len(paare))
        log.info("Zuordnung: %s", ", ".join(f"{s.value}={n}" for s, n in ergebnis.zaehlung().items()))
        return ergebnis

    def _bester_rivale(self, liste: list[tuple[int, int]], ausser: int) -> tuple[int, int] | None:
        for score, index in liste:
            if index == ausser:
                continue
            if score < self.e.schwelle_pruefen:
                return None
            return score, index
        return None

    def _zeile_a(self, i: int, personen_a: Sequence[Person], personen_b: Sequence[Person],
                 zu_b: dict[int, int], bewertungen: dict[tuple[int, int], Bewertung],
                 kand_a: dict[int, list[tuple[int, int]]], kand_b: dict[int, list[tuple[int, int]]]
                 ) -> Zeilenergebnis:
        e = self.e
        person = personen_a[i]
        if person.name.art is Art.LEER:
            return Zeilenergebnis(Status.NUR_A, a=i, hinweise=["kein Name vorhanden"])
        j = zu_b.get(i)
        if j is None:
            hinweise: list[str] = []
            liste = kand_a.get(i, [])
            if liste:
                score, j2 = liste[0]
                if score >= e.schwelle_pruefen:
                    hinweise.append(f"Kandidat {personen_b[j2].anzeige} ({score}) bereits einer anderen Zeile zugeordnet")
                elif score > 0:
                    hinweise.append(f"bester Kandidat unter Schwelle: {personen_b[j2].anzeige} ({score})")
            return Zeilenergebnis(Status.NUR_A, a=i, hinweise=hinweise)

        bew = bewertungen[(i, j)]
        hinweise = list(bew.hinweise)
        mehrdeutig = False
        rivale_b = self._bester_rivale(kand_a.get(i, []), ausser=j)
        if rivale_b is not None and bew.score - rivale_b[0] < 2 * e.mehrdeutig_abstand:
            mehrdeutig |= bew.score - rivale_b[0] < e.mehrdeutig_abstand
            hinweise.append(f"2. Kandidat: {personen_b[rivale_b[1]].anzeige} ({rivale_b[0]})")
        rivale_a = self._bester_rivale(kand_b.get(j, []), ausser=i)
        if rivale_a is not None and bew.score - rivale_a[0] < e.mehrdeutig_abstand:
            mehrdeutig = True
            hinweise.append(f"passt ebenso zu A: {personen_a[rivale_a[1]].anzeige} ({rivale_a[0]})")
        if mehrdeutig:
            status = Status.MEHRDEUTIG
        elif bew.score >= e.schwelle_sicher:
            status = Status.SICHER
        else:
            status = Status.PRUEFEN
        return Zeilenergebnis(status, a=i, b=j, score=bew.score, hinweise=hinweise)

    def _zeile_nur_b(self, j: int, personen_a: Sequence[Person], personen_b: Sequence[Person],
                     kand_b: dict[int, list[tuple[int, int]]]) -> Zeilenergebnis:
        if personen_b[j].name.art is Art.LEER:
            return Zeilenergebnis(Status.NUR_B, b=j, hinweise=["kein Name vorhanden"])
        hinweise: list[str] = []
        liste = kand_b.get(j, [])
        if liste:
            score, i2 = liste[0]
            if score >= self.e.schwelle_pruefen:
                hinweise.append(f"Kandidat {personen_a[i2].anzeige} ({score}) bereits einer anderen Zeile zugeordnet")
            elif score > 0:
                hinweise.append(f"bester Kandidat unter Schwelle: {personen_a[i2].anzeige} ({score})")
        return Zeilenergebnis(Status.NUR_B, b=j, hinweise=hinweise)
