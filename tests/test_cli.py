"""Tests der Kommandozeile (python -m namematch …)."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest

from namematch.cli import EXIT_ABBRUCH, EXIT_BEDIENUNG, EXIT_FEHLER, EXIT_OK, main

FIX = Path(__file__).parent / "fixtures"
A, B = str(FIX / "schueler_a.xlsx"), str(FIX / "schueler_b_semikolon_cp1252.csv")


def lauf(*args: str, eingabe=None, terminal: bool = False) -> tuple[int, str, str]:
    aus, fehler = io.StringIO(), io.StringIO()

    def keine_eingabe(_frage: str) -> str:
        raise AssertionError("Rückfrage nicht erwartet")

    code = main(list(args), eingabe=eingabe or keine_eingabe, aus=aus, fehler=fehler, ist_terminal=lambda: terminal)
    return code, aus.getvalue(), fehler.getvalue()


def test_kompletter_lauf(tmp_path: Path) -> None:
    ziel = tmp_path / "ergebnis.xlsx"
    code, aus, _ = lauf(A, B, "-o", str(ziel), "--ja")
    assert code == EXIT_OK
    assert ziel.exists()
    assert "Ergebnis gespeichert" in aus
    assert "voller Name in „Name“" in aus


def test_dry_run_schreibt_nichts(tmp_path: Path) -> None:
    code, aus, _ = lauf(A, B, "--dry-run")
    assert code == EXIT_OK
    assert "Probelauf" in aus
    assert "Sicher" in aus
    code, _, _ = lauf(A, B, "-o", str(tmp_path / "e.xlsx"), "--dry-run")
    assert code == EXIT_OK
    assert list(tmp_path.iterdir()) == []


def test_ohne_ausgabe_fehler() -> None:
    code, _, fehler = lauf(A, B, "--ja")
    assert code == EXIT_BEDIENUNG
    assert "-o" in fehler


def test_rueckfrage_ohne_terminal(tmp_path: Path) -> None:
    code, _, fehler = lauf(A, B, "-o", str(tmp_path / "e.xlsx"))
    assert code == EXIT_BEDIENUNG
    assert "--ja" in fehler
    assert not (tmp_path / "e.xlsx").exists()


def test_rueckfrage_nein_und_ja(tmp_path: Path) -> None:
    code, aus, _ = lauf(A, B, "-o", str(tmp_path / "e.xlsx"), terminal=True, eingabe=lambda _f: "n")
    assert code == EXIT_ABBRUCH
    assert not (tmp_path / "e.xlsx").exists()
    code, _, _ = lauf(A, B, "-o", str(tmp_path / "e.xlsx"), terminal=True, eingabe=lambda _f: "j")
    assert code == EXIT_OK
    assert (tmp_path / "e.xlsx").exists()


def test_feste_spalten_ohne_rueckfrage(tmp_path: Path) -> None:
    code, _, _ = lauf(A, B, "-o", str(tmp_path / "e.xlsx"), "--name-a", "Name",
                      "--vorname-b", "Vorname", "--nachname-b", "Nachname")
    assert code == EXIT_OK


def test_spaltenfehler(tmp_path: Path) -> None:
    code, _, fehler = lauf(A, B, "-o", str(tmp_path / "e.xlsx"), "--name-a", "Name", "--vorname-a", "X", "--ja")
    assert code == EXIT_FEHLER
    assert "nicht beides" in fehler
    code, _, fehler = lauf(A, B, "-o", str(tmp_path / "e.xlsx"), "--name-a", "Gibtsnicht", "--ja")
    assert code == EXIT_FEHLER
    assert "„Gibtsnicht“" in fehler


def test_ungueltige_schwelle() -> None:
    code, _, fehler = lauf(A, B, "--dry-run", "--sicher", "60", "--pruefen", "70")
    assert code == EXIT_FEHLER
    assert "Schwellen" in fehler


def test_optionen_sortierung_kandidaten_config(tmp_path: Path) -> None:
    cfg = tmp_path / "einstellungen.toml"
    cfg.write_text('[schwellen]\nsicher = 95\n\n[farben]\nsicher = "00FF00"\n', encoding="utf-8")
    ziel = tmp_path / "e.xlsx"
    code, _, _ = lauf(A, B, "-o", str(ziel), "--ja", "--sortierung", "status", "--ohne-kandidaten",
                      "--config", str(cfg))
    assert code == EXIT_OK
    mappe = openpyxl.load_workbook(ziel)
    assert mappe.sheetnames == ["Zusammengeführt", "Protokoll"]
    status = [r[0] for r in mappe["Zusammengeführt"].iter_rows(min_row=2, values_only=True)]
    assert status[0] == "Mehrdeutig"
    assert status[-1] == "Nur in B"
    protokoll = {r[0]: r[1] for r in mappe["Protokoll"].iter_rows(values_only=True)}
    assert protokoll["Schwelle Sicher (ab)"] == 95


def test_einleseoptionen(tmp_path: Path) -> None:
    code, aus, _ = lauf(A, str(FIX / "schueler_b_tab_utf8bom.csv"), "--dry-run", "--trennzeichen-b", "tab",
                        "--kodierung-b", "utf-8-sig")
    assert code == EXIT_OK
    code, aus, _ = lauf(A, str(FIX / "mit_titelzeilen.csv"), "--dry-run", "--kopfzeile-b", "4")
    assert code == EXIT_OK
    code, _, fehler = lauf(A, B, "--dry-run", "--sheet-a", "Gibtsnicht")
    assert code == EXIT_FEHLER
    assert "Blatt" in fehler


def test_vorhandene_ergebnisdatei(tmp_path: Path) -> None:
    ziel = tmp_path / "e.xlsx"
    ziel.write_bytes(b"x")
    code, _, fehler = lauf(A, B, "-o", str(ziel), "--ja")
    assert code == EXIT_FEHLER
    assert "existiert bereits" in fehler
    code, _, _ = lauf(A, B, "-o", str(ziel), "--ja", "--ueberschreiben")
    assert code == EXIT_OK


def test_als_modul_aufrufbar(tmp_path: Path) -> None:
    """Echter Prozessstart mit python -m namematch (ohne Netzwerk)."""
    ziel = tmp_path / "e.xlsx"
    ergebnis = subprocess.run([sys.executable, "-m", "namematch", A, B, "-o", str(ziel), "--ja"],
                              capture_output=True, text=True, cwd=Path(__file__).parent.parent, check=False)
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ziel.exists()
    version = subprocess.run([sys.executable, "-m", "namematch", "--version"], capture_output=True, text=True,
                             cwd=Path(__file__).parent.parent, check=False)
    assert version.stdout.startswith("namematch ")


def test_unerwarteter_fehler_ohne_details(monkeypatch: pytest.MonkeyPatch) -> None:
    import namematch.cli as cli

    def kaputt(*_a, **_k):
        raise RuntimeError("Geheimer Zellinhalt")

    monkeypatch.setattr(cli, "abgleichen", kaputt)
    code, aus, fehler = lauf(A, B, "--dry-run")
    assert code == EXIT_FEHLER
    assert "RuntimeError" in fehler
    assert "Geheimer Zellinhalt" not in fehler + aus
