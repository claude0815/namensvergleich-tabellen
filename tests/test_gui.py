"""Tests der tkinter-Oberfläche (übersprungen ohne tkinter oder ohne Bildschirm)."""

from __future__ import annotations

import gc
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from namematch import gui  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fenster(monkeypatch: pytest.MonkeyPatch):
    meldungen: list[tuple[str, str]] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda titel, text, **_k: meldungen.append((titel, text)))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda titel, text, **_k: meldungen.append((titel, text)))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda titel, text, **_k: meldungen.append((titel, text)))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda titel, text, **_k: True)
    try:
        wurzel, hauptfenster = gui.fenster_erzeugen()
    except tk.TclError:
        pytest.skip("kein Bildschirm verfügbar")
    hauptfenster.meldungen = meldungen
    yield hauptfenster
    _warten(hauptfenster)
    wurzel.destroy()
    del hauptfenster, wurzel
    gc.collect()  # Tk-Objekte hier im Haupt-Thread aufräumen, nicht zufällig später in einem anderen Thread


def _warten(fenster, sekunden: float = 60) -> None:
    ende = time.monotonic() + sekunden
    while fenster._laeuft and time.monotonic() < ende:
        fenster.wurzel.update()
        time.sleep(0.02)
    fenster.wurzel.update()


def test_laden_mit_vorschlag_und_vorschau(fenster) -> None:
    assert fenster.rahmen_a.laden(FIX / "schueler_a.xlsx")
    a = fenster.rahmen_a
    assert a.var_modus.get() == "voll"
    assert a.var_voll.get() == "Name"
    assert a.cb_vorname.instate(["disabled"])
    assert a.var_blatt.get() == "Klassenliste"
    assert len(a.baum.get_children()) == 10
    assert a.baum.heading("s1")["text"] == "[Name] Name"
    assert fenster.var_ausgabe.get().endswith("schueler_a_zusammengefuehrt.xlsx")
    assert fenster.rahmen_b.laden(FIX / "schueler_b_semikolon_cp1252.csv")
    b = fenster.rahmen_b
    assert b.var_modus.get() == "getrennt"
    assert (b.var_vorname.get(), b.var_nachname.get()) == ("Vorname", "Nachname")
    assert b.cb_kodierung.instate(["!disabled"])
    assert "cp1252" in b.var_info.get()


def test_warnung_bei_falscher_spalte(fenster) -> None:
    rahmen = fenster.rahmen_a
    rahmen.laden(FIX / "webuntis_a.csv")
    assert rahmen.var_warnung.get() == ""
    rahmen.var_nachname.set("name")
    rahmen._spalten_geaendert()
    assert "Kurz" in rahmen.var_warnung.get()


def test_kopfzeile_aendern(fenster) -> None:
    rahmen = fenster.rahmen_b
    rahmen.laden(FIX / "mit_titelzeilen.csv")
    assert "Keine Namensspalte" in rahmen.var_warnung.get()
    rahmen.var_kopf.set("4")
    rahmen._optionen_geaendert()
    assert (rahmen.var_vorname.get(), rahmen.var_nachname.get()) == ("Vorname", "Nachname")
    assert rahmen.var_warnung.get() == ""


def test_noch_nicht_bereit(fenster) -> None:
    assert fenster.zusammenfuehren() is False
    assert any("Liste A" in text for _titel, text in fenster.meldungen)


def test_zusammenfuehren_im_hintergrund(fenster, tmp_path: Path) -> None:
    fenster.rahmen_a.laden(FIX / "schueler_a.xlsx")
    fenster.rahmen_b.laden(FIX / "schueler_b_semikolon_cp1252.csv")
    ziel = tmp_path / "ergebnis.xlsx"
    fenster.var_ausgabe.set(str(ziel))
    fenster.var_nach_status.set(True)
    assert fenster.zusammenfuehren() is True
    fenster.schliessen()  # während des Laufs: wird verweigert
    assert any("Bitte warten" in titel for titel, _t in fenster.meldungen) or not fenster._laeuft
    _warten(fenster)
    assert ziel.exists()
    assert "Fertig" in fenster.var_status.get()
    assert "Sicher: 28" in fenster.var_status.get()
    assert fenster.knopf_oeffnen.instate(["!disabled"])
    assert fenster.ergebnis is not None and fenster.ergebnis.einstellungen.sortierung == "status"


def test_lesefehler_als_meldung(fenster, tmp_path: Path) -> None:
    kaputt = tmp_path / "kaputt.xlsx"
    kaputt.write_bytes(b"keine Excel-Datei")
    assert fenster.rahmen_a.laden(kaputt) is False
    assert any("Excel" in text for _titel, text in fenster.meldungen)


def test_selbsttest(tmp_path: Path) -> None:
    try:
        code = gui.main(["--selbsttest", str(FIX / "webuntis_a_mac.csv"), str(FIX / "schuelerliste_b.xlsx"),
                         str(tmp_path / "e.xlsx")])
    except tk.TclError:
        pytest.skip("kein Bildschirm verfügbar")
    assert code == 0
    assert (tmp_path / "e.xlsx").exists()


def test_hintergrund_thread_haelt_keine_fensterobjekte() -> None:
    """Der Hintergrund-Thread bekommt nur Daten; so werden Tk-Objekte nie im falschen Thread aufgeräumt."""
    import inspect

    quelle = inspect.getsource(gui.Hauptfenster.zusammenfuehren)
    assert "target=_hintergrund_arbeit" in quelle
    assert "self._arbeit" not in quelle
    parameter = list(inspect.signature(gui._hintergrund_arbeit).parameters)
    assert parameter == ["sitzung", "ueberschreiben", "warteschlange"]
