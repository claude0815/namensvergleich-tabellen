"""Zustand und Abläufe der grafischen Oberfläche – ohne tkinter, damit überall testbar.

Die Oberfläche (:mod:`namematch.gui`) zeigt nur an, was diese Klassen liefern, und gibt
Eingaben weiter. Die eigentliche Arbeit erledigt :mod:`namematch.pipeline`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .columns import Namensspalten, Zusatzspalten, namensspalten_pruefen, vorschlagen
from .config import Einstellungen, laden
from .errors import NamematchError
from .io import Einleseoptionen, Tabelle, blattnamen, einlesen, zelltext
from .matcher import Status
from .pipeline import Laufergebnis, Spaltenwahl, abgleichen, ergebnis_schreiben

#: Eintrag in Auswahllisten für „keine Spalte“
KEINE = "— keine —"

#: Anzeige → Kodierung (None = automatisch)
KODIERUNGEN: dict[str, str | None] = {
    "automatisch": None,
    "UTF-8": "utf-8",
    "UTF-8 mit BOM": "utf-8-sig",
    "Windows (cp1252)": "cp1252",
    "Mac (mac_roman)": "mac_roman",
    "DOS (cp850)": "cp850",
}

#: Anzeige → Trennzeichen (None = automatisch)
TRENNZEICHEN: dict[str, str | None] = {
    "automatisch": None,
    "Semikolon ;": ";",
    "Komma ,": ",",
    "Tabulator": "\t",
    "Senkrechter Strich |": "|",
}

_TRENNZEICHEN_TEXT = {";": "Semikolon", ",": "Komma", "\t": "Tabulator", "|": "senkrechter Strich"}


def _spalte(wert: str | None) -> str | None:
    """Auswahl aus einer Liste → Spaltenname oder None."""
    return None if wert in (None, "", KEINE) else wert


def _anzeigetext(wert: Any) -> str:
    """Text für die Vorschau: Datumsangaben wie in Excel üblich (TT.MM.JJJJ)."""
    if isinstance(wert, dt.datetime):
        if (wert.hour, wert.minute, wert.second) == (0, 0, 0):
            return wert.strftime("%d.%m.%Y")
        return wert.strftime("%d.%m.%Y %H:%M")
    if isinstance(wert, dt.date):
        return wert.strftime("%d.%m.%Y")
    return zelltext(wert)


@dataclass
class Liste:
    """Eine Eingabeliste (A oder B): Datei, Einleseoptionen, Tabelle und Spaltenwahl."""

    kennung: str
    pfad: Path | None = None
    optionen: Einleseoptionen = field(default_factory=Einleseoptionen)
    tabelle: Tabelle | None = None
    blaetter: list[str] = field(default_factory=list)
    namen: Namensspalten = field(default_factory=Namensspalten)
    zusatz: Zusatzspalten = field(default_factory=Zusatzspalten)

    @property
    def ist_excel(self) -> bool:
        return self.pfad is not None and self.pfad.suffix.lower() in (".xlsx", ".xlsm", ".xls")

    @property
    def geladen(self) -> bool:
        return self.tabelle is not None

    def laden(self, pfad: Path | str, optionen: Einleseoptionen | None = None) -> None:
        """Liest eine neue Datei und übernimmt den Spaltenvorschlag. Fehler: :class:`NamematchError`."""
        pfad = Path(pfad)
        optionen = optionen or Einleseoptionen()
        tabelle = einlesen(pfad, optionen)
        self.blaetter = blattnamen(pfad) if pfad.suffix.lower() in (".xlsx", ".xlsm", ".xls") else []
        self.pfad, self.optionen, self.tabelle = pfad, optionen, tabelle
        vorschlag = vorschlagen(tabelle.spalten)
        self.namen, self.zusatz = vorschlag.namen, vorschlag.zusatz

    def optionen_setzen(self, optionen: Einleseoptionen) -> None:
        """Liest die Datei mit neuen Optionen (Blatt, Kopfzeile, Kodierung, Trennzeichen) erneut.

        Die bisherige Spaltenwahl bleibt erhalten, solange alle gewählten Spalten noch existieren.
        """
        if self.pfad is None:
            return
        alte_namen, alte_zusatz = self.namen, self.zusatz
        alte_spalten = set(self.tabelle.spalten) if self.tabelle else set()
        self.laden(self.pfad, optionen)
        neue_spalten = set(self.tabelle.spalten) if self.tabelle else set()
        gewaehlt = set(alte_namen.spalten()) | {s for s in vars(alte_zusatz).values() if s}
        if alte_spalten == neue_spalten and gewaehlt <= neue_spalten:
            self.namen, self.zusatz = alte_namen, alte_zusatz

    def spalten_auswahl(self) -> list[str]:
        """Einträge für die Auswahllisten der Spalten."""
        return [KEINE, *(self.tabelle.spalten if self.tabelle else [])]

    def namen_setzen(self, voll: str | None, vorname: str | None, nachname: str | None) -> None:
        """Namensspalten aus der Oberfläche übernehmen (voller Name ODER Vor-/Nachname)."""
        voll, vorname, nachname = _spalte(voll), _spalte(vorname), _spalte(nachname)
        if voll:
            self.namen = Namensspalten(voll=voll)
        else:
            self.namen = Namensspalten(vorname=vorname, nachname=nachname)

    def zusatz_setzen(self, klasse: str | None, geburtsdatum: str | None, email: str | None) -> None:
        """Zusatzspalten aus der Oberfläche übernehmen."""
        self.zusatz = Zusatzspalten(klasse=_spalte(klasse), geburtsdatum=_spalte(geburtsdatum), email=_spalte(email))

    def vorschau(self, anzahl: int = 10) -> tuple[list[str], list[list[str]]]:
        """Überschriften und die ersten Zeilen als Text (nur zur Anzeige auf dem Bildschirm)."""
        if self.tabelle is None:
            return [], []
        return list(self.tabelle.spalten), [[_anzeigetext(w) for w in z] for z in self.tabelle.zeilen[:anzahl]]

    def info(self) -> str:
        """Kurzinfo ohne Zellinhalte, z. B. „cp1252, Semikolon, 44 Zeilen, 8 Spalten“."""
        tab = self.tabelle
        if tab is None:
            return "keine Datei gewählt"
        teile = []
        if tab.kodierung:
            teile.append(f"Kodierung {tab.kodierung}")
        if tab.trennzeichen:
            teile.append(f"Trennzeichen {_TRENNZEICHEN_TEXT.get(tab.trennzeichen, tab.trennzeichen)}")
        teile.append(f"{len(tab.zeilen)} Zeilen")
        teile.append(f"{len(tab.spalten)} Spalten")
        if tab.leere_zeilen:
            teile.append(f"{tab.leere_zeilen} leere Zeile{'n' if tab.leere_zeilen != 1 else ''} übersprungen")
        return ", ".join(teile)

    def warnungen(self) -> list[str]:
        """Plausibilitätswarnungen zur Namensspalte (nur Spaltennamen und Prozentwerte)."""
        if self.tabelle is None or self.namen.art == "keine":
            return []
        return namensspalten_pruefen(self.tabelle, self.namen, self.kennung)


@dataclass
class Sitzung:
    """Alles, was die Oberfläche für einen Lauf braucht."""

    a: Liste = field(default_factory=lambda: Liste("A"))
    b: Liste = field(default_factory=lambda: Liste("B"))
    sicher: int = 90
    pruefen: int = 70
    sortierung: str = "original"
    kandidaten: bool = True
    ausgabe: Path | None = None
    einstellungsdatei: Path | None = None

    def einstellungen(self) -> Einstellungen:
        """Einstellungen aus Datei (optional) plus Werten der Oberfläche."""
        basis = laden(self.einstellungsdatei)
        return replace(basis, schwelle_sicher=self.sicher, schwelle_pruefen=self.pruefen,
                       sortierung=self.sortierung, kandidaten_blatt=self.kandidaten).validieren()

    def ausgabe_vorschlag(self) -> Path | None:
        """Vorschlag für die Ergebnisdatei: neben Liste A, „<Name>_zusammengefuehrt.xlsx“."""
        if self.a.pfad is None:
            return None
        return self.a.pfad.with_name(f"{self.a.pfad.stem}_zusammengefuehrt.xlsx")

    def spaltenwahl(self) -> Spaltenwahl:
        return Spaltenwahl(self.a.namen, self.b.namen, self.a.zusatz, self.b.zusatz)

    def pruefen_vor_lauf(self) -> list[str]:
        """Verständliche Hinweise, was vor dem Zusammenführen noch fehlt (leer = alles bereit)."""
        fehler: list[str] = []
        for liste, rolle in ((self.a, "Hauptliste"), (self.b, "anzuhängende Liste")):
            if not liste.geladen:
                fehler.append(f"Bitte Liste {liste.kennung} ({rolle}) auswählen.")
            elif liste.namen.art == "keine":
                fehler.append(f"Bitte in Liste {liste.kennung} die Namensspalte(n) auswählen.")
        if self.ausgabe is None:
            fehler.append("Bitte festlegen, wo die Ergebnisdatei gespeichert werden soll.")
        else:
            if self.ausgabe.suffix.lower() != ".xlsx":
                fehler.append("Die Ergebnisdatei muss die Endung .xlsx haben.")
            for liste in (self.a, self.b):
                if liste.pfad is not None and self.ausgabe.resolve() == liste.pfad.resolve():
                    fehler.append(f"Die Ergebnisdatei darf nicht die Eingabedatei {liste.kennung} sein.")
        if not 0 <= self.pruefen <= self.sicher <= 100:
            fehler.append("Die Schwelle für „Prüfen“ muss kleiner oder gleich der Schwelle für „Sicher“ sein.")
        return fehler

    def ausfuehren(self, fortschritt: Callable[[str, float], None] | None,
                   ueberschreiben: bool = False) -> Laufergebnis:
        """Abgleich und Ergebnisdatei. Fehler als :class:`NamematchError` mit deutscher Meldung."""
        fehler = self.pruefen_vor_lauf()
        if fehler:
            raise NamematchError(" ".join(fehler))
        assert self.a.tabelle is not None and self.b.tabelle is not None and self.ausgabe is not None
        ergebnis = abgleichen(self.a.tabelle, self.b.tabelle, self.spaltenwahl(), self.einstellungen(), fortschritt)
        ergebnis_schreiben(ergebnis, self.ausgabe, ueberschreiben=ueberschreiben)
        return ergebnis

    @staticmethod
    def zusammenfassung(ergebnis: Laufergebnis) -> str:
        """Ergebnis in wenigen Zeilen (nur Zahlen, keine Namen)."""
        zaehlung = ergebnis.zaehlung()
        zeilen = ["   ".join(f"{s.value}: {zaehlung[s]}" for s in Status)]
        verteilung = ", ".join(f"{bereich}: {anzahl}" for bereich, anzahl in ergebnis.verteilung().items())
        zeilen.append(f"Bester Kandidat je Person aus A – {verteilung}")
        if ergebnis.duplikate_a or ergebnis.duplikate_b:
            zeilen.append(f"Doppelte Namen: {len(ergebnis.duplikate_a)} Gruppe(n) in A, "
                          f"{len(ergebnis.duplikate_b)} in B (siehe Blatt „Protokoll“)")
        return "\n".join(zeilen)
