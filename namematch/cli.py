"""Kommandozeile: ``python -m namematch datei_a datei_b -o ergebnis.xlsx [Optionen]``.

Dünne Schicht über :mod:`namematch.pipeline`. Bildschirmausgaben enthalten nur Dateinamen,
Spaltennamen und Zahlen – niemals Namen oder andere Zellinhalte.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from . import __version__
from .columns import Namensspalten, Zusatzspalten
from .config import laden
from .errors import NamematchError, SpaltenFehler
from .io import Einleseoptionen, Tabelle, einlesen
from .matcher import Status
from .pipeline import (
    MERKMALE,
    Spaltenwahl,
    abgleichen,
    ergebnis_schreiben,
    spalten_vorschlagen,
    spalten_warnungen,
    spaltenwahl_pruefen,
)

EXIT_OK, EXIT_FEHLER, EXIT_BEDIENUNG, EXIT_ABBRUCH = 0, 1, 2, 3

_TRENNZEICHEN = {";": ";", "semikolon": ";", ",": ",", "komma": ",", "tab": "\t", "\\t": "\t", "\t": "\t",
                 "|": "|"}
_MERKMAL_NAMEN = {"klasse": "Klasse", "geburtsdatum": "Geburtsdatum", "email": "E-Mail"}


def _trennzeichen(wert: str) -> str:
    try:
        return _TRENNZEICHEN[wert.lower()]
    except KeyError:
        raise argparse.ArgumentTypeError("erlaubt sind ; , tab |") from None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m namematch",
        description="Führt zwei Personenlisten (Excel/CSV) über den Namen zusammen – vollständig offline.",
        epilog="Beispiel: python -m namematch liste_a.xlsx liste_b.csv -o ergebnis.xlsx",
    )
    p.add_argument("datei_a", type=Path, help="Hauptliste A (.xlsx, .xls, .csv) – bestimmt die Reihenfolge")
    p.add_argument("datei_b", type=Path, help="Liste B (.xlsx, .xls, .csv) – wird angehängt")
    p.add_argument("-o", "--ausgabe", type=Path, help="Ergebnisdatei (.xlsx)")

    g = p.add_argument_group("Namensspalten (ohne Angabe: automatische Erkennung mit Rückfrage)")
    for k in ("a", "b"):
        g.add_argument(f"--name-{k}", metavar="SPALTE", help=f"Spalte mit vollem Namen in Datei {k.upper()}")
        g.add_argument(f"--vorname-{k}", metavar="SPALTE", help=f"Vornamensspalte in Datei {k.upper()}")
        g.add_argument(f"--nachname-{k}", metavar="SPALTE", help=f"Nachnamensspalte in Datei {k.upper()}")

    z = p.add_argument_group("Zusatzmerkmale (ohne Angabe: automatische Erkennung)")
    for k in ("a", "b"):
        z.add_argument(f"--klasse-{k}", metavar="SPALTE", help=f"Klassenspalte in Datei {k.upper()}")
        z.add_argument(f"--geburtsdatum-{k}", metavar="SPALTE", help=f"Geburtsdatumsspalte in Datei {k.upper()}")
        z.add_argument(f"--email-{k}", metavar="SPALTE", help=f"E-Mail-Spalte in Datei {k.upper()}")
    z.add_argument("--ohne-zusatzmerkmale", action="store_true", help="nur Namen vergleichen")

    e = p.add_argument_group("Einlesen")
    for k in ("a", "b"):
        e.add_argument(f"--sheet-{k}", f"--blatt-{k}", dest=f"sheet_{k}", metavar="BLATT",
                       help=f"Tabellenblatt in Datei {k.upper()} (Standard: erstes Blatt)")
        e.add_argument(f"--kopfzeile-{k}", type=int, default=1, metavar="N",
                       help=f"Zeile mit den Überschriften in Datei {k.upper()} (Standard: 1)")
        e.add_argument(f"--trennzeichen-{k}", type=_trennzeichen, metavar="ZEICHEN",
                       help=f"CSV-Trennzeichen in Datei {k.upper()}: ; , tab | (Standard: automatisch)")
        e.add_argument(f"--kodierung-{k}", metavar="KODIERUNG",
                       help=f"CSV-Kodierung in Datei {k.upper()}, z. B. utf-8, cp1252 (Standard: automatisch)")

    m = p.add_argument_group("Abgleich und Ausgabe")
    m.add_argument("--sicher", type=int, metavar="N", help="Schwelle für „Sicher“ (Standard: 90)")
    m.add_argument("--pruefen", type=int, metavar="N", help="Schwelle für „Prüfen“ (Standard: 70)")
    m.add_argument("--config", type=Path, metavar="DATEI", help="Einstellungsdatei (TOML)")
    m.add_argument("--sortierung", choices=("original", "status"),
                   help="Reihenfolge: original (wie A, Standard) oder status (Prüfen-Zeilen zusammen)")
    m.add_argument("--ohne-kandidaten", action="store_true", help="kein Blatt „Kandidaten“ anlegen")
    m.add_argument("--ueberschreiben", action="store_true", help="vorhandene Ergebnisdatei ersetzen")

    s = p.add_argument_group("Ablauf")
    s.add_argument("--dry-run", "--probelauf", dest="dry_run", action="store_true",
                   help="nur erkannte Spalten und Statistik zeigen, nichts schreiben")
    s.add_argument("-j", "-y", "--ja", dest="ja", action="store_true", help="Spaltenvorschlag ohne Rückfrage übernehmen")
    s.add_argument("-v", "--ausfuehrlich", action="store_true", help="Protokollmeldungen anzeigen (nur Zahlen/Spaltennamen)")
    s.add_argument("--debug", action="store_true",
                   help="bei unerwarteten Fehlern vollständige Fehlermeldung zeigen (kann Zellinhalte enthalten!)")
    s.add_argument("--version", action="version", version=f"namematch {__version__}")
    return p


def _namensspalten(args: argparse.Namespace, k: str, vorschlag: Namensspalten) -> tuple[Namensspalten, bool]:
    voll, vor, nach = getattr(args, f"name_{k}"), getattr(args, f"vorname_{k}"), getattr(args, f"nachname_{k}")
    if not (voll or vor or nach):
        return vorschlag, False
    try:
        return Namensspalten(voll=voll, vorname=vor, nachname=nach), True
    except ValueError:
        raise SpaltenFehler(f"Datei {k.upper()}: entweder --name-{k} oder --vorname-{k}/--nachname-{k} angeben, "
                            "nicht beides.") from None


def _zusatzspalten(args: argparse.Namespace, k: str, vorschlag: Zusatzspalten) -> Zusatzspalten:
    if args.ohne_zusatzmerkmale:
        return Zusatzspalten()
    werte = {m: getattr(args, f"{m}_{k}") or getattr(vorschlag, m) for m in MERKMALE}
    return Zusatzspalten(**werte)


def _datei_info(kennung: str, tab: Tabelle) -> str:
    teile = []
    if tab.blatt:
        teile.append(f"Blatt „{tab.blatt}“")
    if tab.kodierung:
        teile.append(tab.kodierung)
    if tab.trennzeichen:
        teile.append("Trennzeichen " + {"\t": "Tab"}.get(tab.trennzeichen, tab.trennzeichen))
    teile.append(f"{len(tab.zeilen)} Zeilen")
    teile.append(f"{len(tab.spalten)} Spalten")
    if tab.leere_zeilen:
        teile.append(f"{tab.leere_zeilen} leere Zeile{'n' if tab.leere_zeilen != 1 else ''} ignoriert")
    return f"Datei {kennung}: {tab.quelle.name} ({', '.join(teile)})"


def _zusatz_text(zusatz: Zusatzspalten) -> str:
    teile = [f"{_MERKMAL_NAMEN[m]} „{getattr(zusatz, m)}“" for m in MERKMALE if getattr(zusatz, m)]
    return ", ".join(teile) or "keine"


def _spaltenwahl_anzeigen(wahl: Spaltenwahl, tab_a: Tabelle, tab_b: Tabelle, aus: TextIO) -> None:
    for kennung, tab, namen, zusatz in (("A", tab_a, wahl.namen_a, wahl.zusatz_a),
                                        ("B", tab_b, wahl.namen_b, wahl.zusatz_b)):
        print(_datei_info(kennung, tab), file=aus)
        print(f"  Namensspalten:  {namen.beschreibung()}", file=aus)
        print(f"  Zusatzmerkmale: {_zusatz_text(zusatz)}", file=aus)
    merkmale = wahl.merkmale()
    genutzt = ", ".join(_MERKMAL_NAMEN[m] for m in merkmale) or "keine (nur Namen)"
    print(f"Verglichene Zusatzmerkmale (in beiden Dateien vorhanden): {genutzt}", file=aus)


def _fortschritt_anzeige(fehler: TextIO) -> Callable[[str, float], None] | None:
    if not getattr(fehler, "isatty", lambda: False)():
        return None
    letzte = [-1]

    def melden(text: str, anteil: float) -> None:
        prozent = int(anteil * 100)
        if prozent != letzte[0]:
            letzte[0] = prozent
            print(f"\r{text:<12} {prozent:3d} %", end="", file=fehler, flush=True)
            if prozent >= 100:
                print(file=fehler)
    return melden


def _logging_einrichten(ausfuehrlich: bool, fehler: TextIO) -> logging.Handler:
    logger = logging.getLogger("namematch")
    handler = logging.StreamHandler(fehler)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO if ausfuehrlich else logging.WARNING)
    logger.propagate = False
    return handler


def main(argv: Sequence[str] | None = None, eingabe: Callable[[str], str] = input,
         aus: TextIO | None = None, fehler: TextIO | None = None,
         ist_terminal: Callable[[], bool] | None = None) -> int:
    """Einstiegspunkt der Kommandozeile. Gibt den Exit-Code zurück."""
    aus = aus or sys.stdout
    fehler = fehler or sys.stderr
    ist_terminal = ist_terminal or (lambda: sys.stdin.isatty())
    args = _parser().parse_args(argv)
    handler = _logging_einrichten(args.ausfuehrlich, fehler)
    try:
        return _ausfuehren(args, eingabe, aus, fehler, ist_terminal)
    except NamematchError as f:
        print(f"Fehler: {f}", file=fehler)
        return EXIT_FEHLER
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=fehler)
        return EXIT_ABBRUCH
    except Exception as f:  # unerwartet: Meldung kann Zellinhalte enthalten → nur mit --debug zeigen
        if args.debug:
            raise
        print(f"Unerwarteter Fehler ({f.__class__.__name__}). Details mit --debug "
              "(Achtung: kann Zellinhalte enthalten).", file=fehler)
        return EXIT_FEHLER
    finally:
        logging.getLogger("namematch").removeHandler(handler)


def _ausfuehren(args: argparse.Namespace, eingabe: Callable[[str], str], aus: TextIO, fehler: TextIO,
                ist_terminal: Callable[[], bool]) -> int:
    if not args.dry_run and args.ausgabe is None:
        print("Fehler: Bitte die Ergebnisdatei mit -o angeben (oder --dry-run für einen Probelauf).", file=fehler)
        return EXIT_BEDIENUNG
    einstellungen = laden(
        args.config, schwelle_sicher=args.sicher, schwelle_pruefen=args.pruefen, sortierung=args.sortierung,
        kandidaten_blatt=False if args.ohne_kandidaten else None,
    )
    start = time.perf_counter()
    tab_a = einlesen(args.datei_a, Einleseoptionen(args.sheet_a, args.kopfzeile_a, args.trennzeichen_a,
                                                   args.kodierung_a))
    tab_b = einlesen(args.datei_b, Einleseoptionen(args.sheet_b, args.kopfzeile_b, args.trennzeichen_b,
                                                   args.kodierung_b))
    vorschlag = spalten_vorschlagen(tab_a, tab_b)
    namen_a, fest_a = _namensspalten(args, "a", vorschlag.namen_a)
    namen_b, fest_b = _namensspalten(args, "b", vorschlag.namen_b)
    wahl = Spaltenwahl(namen_a, namen_b, _zusatzspalten(args, "a", vorschlag.zusatz_a),
                       _zusatzspalten(args, "b", vorschlag.zusatz_b))
    _spaltenwahl_anzeigen(wahl, tab_a, tab_b, aus)
    spaltenwahl_pruefen(wahl, tab_a, tab_b)
    vorab = spalten_warnungen(tab_a, tab_b, wahl)
    for warnung in vorab:
        print(f"WARNUNG: {warnung}", file=aus)

    if not (fest_a and fest_b) and not args.ja and not args.dry_run:
        if not ist_terminal():
            print("Fehler: Die Namensspalten wurden automatisch erkannt. Bitte prüfen und mit --ja bestätigen "
                  "oder die Spalten angeben (--name-a, --vorname-b, …).", file=fehler)
            return EXIT_BEDIENUNG
        antwort = eingabe("Mit dieser Spaltenwahl fortfahren? [j/N] ").strip().lower()
        if antwort not in ("j", "ja", "y", "yes"):
            print("Abgebrochen – es wurde nichts geschrieben.", file=aus)
            return EXIT_ABBRUCH

    ergebnis = abgleichen(tab_a, tab_b, wahl, einstellungen, _fortschritt_anzeige(fehler))
    zaehlung = ergebnis.zaehlung()
    print("Ergebnis:", file=aus)
    for status in Status:
        print(f"  {status.value:<11} {zaehlung[status]:>6}", file=aus)
    print(f"  Doppelte Namen: in A {len(ergebnis.duplikate_a)}, in B {len(ergebnis.duplikate_b)} "
          "(Gruppen gleicher Namen, siehe Blatt „Protokoll“)", file=aus)
    print("Bester Kandidat je Person aus A (Score):", file=aus)
    for bereich, anzahl in ergebnis.verteilung().items():
        print(f"  {bereich:<13} {anzahl:>6}", file=aus)
    for warnung in ergebnis.warnungen:
        if warnung not in vorab:
            print(f"WARNUNG: {warnung}", file=aus)
    if args.dry_run:
        print(f"Probelauf ({time.perf_counter() - start:.1f} s) – es wurde nichts geschrieben.", file=aus)
        return EXIT_OK
    pfad = ergebnis_schreiben(ergebnis, args.ausgabe, ueberschreiben=args.ueberschreiben)
    print(f"Ergebnis gespeichert: {pfad} ({time.perf_counter() - start:.1f} s)", file=aus)
    return EXIT_OK
