"""Grafische Oberfläche (tkinter) – dünne Schicht über :mod:`namematch.gui_logik`.

Start: ``python -m namematch.gui`` bzw. ``namematch-gui.exe``.
Alles läuft lokal; die Vorschau zeigt Daten nur auf dem Bildschirm, nichts wird protokolliert.
"""

from __future__ import annotations

import os
import queue
import subprocess  # nur zum Öffnen der Ergebnisdatei mit dem Standardprogramm (macOS/Linux)
import sys
import threading
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .errors import NamematchError
from .gui_logik import KEINE, KODIERUNGEN, TRENNZEICHEN, Liste, Sitzung
from .io import Einleseoptionen
from .pipeline import Laufergebnis

TITEL = "namematch – Personenlisten zusammenführen"
DATEITYPEN = [("Tabellen (Excel, CSV)", "*.xlsx *.xlsm *.xls *.csv *.txt *.tsv"), ("Alle Dateien", "*.*")]
WARNFARBE = "#B00020"
HINWEISFARBE = "#555555"


def datei_oeffnen(pfad: Path) -> None:
    """Öffnet eine Datei oder einen Ordner mit dem Standardprogramm des Betriebssystems."""
    if sys.platform.startswith("win"):
        os.startfile(str(pfad))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(pfad)])  # noqa: S603, S607 – fester Befehl, keine Shell
    else:
        subprocess.Popen(["xdg-open", str(pfad)])  # noqa: S603, S607


def _fehlertext(fehler: BaseException) -> str:
    """Deutsche Meldung; bei unerwarteten Fehlern nur der Typ (Meldung könnte Zellinhalte enthalten)."""
    if isinstance(fehler, NamematchError):
        return str(fehler)
    return (f"Unerwarteter Fehler ({fehler.__class__.__name__}). Bitte die Eingabedateien prüfen "
            "oder das Programm erneut starten.")


class ListenRahmen(ttk.LabelFrame):
    """Bereich für eine Liste: Datei, Einleseoptionen, Spaltenwahl, Warnungen, Vorschau."""

    def __init__(self, master: tk.Misc, liste: Liste, titel: str, geaendert: Callable[[], None]) -> None:
        super().__init__(master, text=titel, padding=8)
        self.liste = liste
        self.geaendert = geaendert
        self._aktualisiert = False  # verhindert Rückkopplung beim Befüllen der Auswahllisten
        self.columnconfigure(0, weight=1)

        # Datei
        zeile = ttk.Frame(self)
        zeile.grid(row=0, column=0, sticky="ew")
        zeile.columnconfigure(1, weight=1)
        ttk.Label(zeile, text="Datei:").grid(row=0, column=0, sticky="w")
        self.var_datei = tk.StringVar(value="(noch keine Datei gewählt)")
        ttk.Entry(zeile, textvariable=self.var_datei, state="readonly").grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(zeile, text="Auswählen …", command=self.datei_waehlen).grid(row=0, column=2)

        # Einleseoptionen – eine Zeile; je nach Dateityp nur die passenden Felder
        optionen = ttk.Frame(self)
        optionen.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.var_blatt = tk.StringVar()
        self.var_kopf = tk.StringVar(value="1")
        self.var_kodierung = tk.StringVar(value="automatisch")
        self.var_trenn = tk.StringVar(value="automatisch")
        self.lbl_blatt = ttk.Label(optionen, text="Blatt:")
        self.cb_blatt = ttk.Combobox(optionen, textvariable=self.var_blatt, state="readonly", width=18)
        self.lbl_kodierung = ttk.Label(optionen, text="Kodierung:")
        self.cb_kodierung = ttk.Combobox(optionen, textvariable=self.var_kodierung, values=list(KODIERUNGEN),
                                         state="readonly", width=15)
        self.lbl_trenn = ttk.Label(optionen, text="Trennzeichen:")
        self.cb_trenn = ttk.Combobox(optionen, textvariable=self.var_trenn, values=list(TRENNZEICHEN),
                                     state="readonly", width=15)
        self.lbl_kopf = ttk.Label(optionen, text="Überschriften in Zeile:")
        self.sp_kopf = ttk.Spinbox(optionen, from_=1, to=99, width=4, textvariable=self.var_kopf,
                                   command=self._optionen_geaendert)
        self._excel_felder = [(self.lbl_blatt, 0), (self.cb_blatt, 1)]
        self._csv_felder = [(self.lbl_kodierung, 0), (self.cb_kodierung, 1), (self.lbl_trenn, 2), (self.cb_trenn, 3)]
        for widget, spalte in self._excel_felder + self._csv_felder:
            widget.grid(row=0, column=spalte, sticky="w", padx=(0, 4 if spalte % 2 == 0 else 12))
            widget.grid_remove()
        self.lbl_kopf.grid(row=0, column=4, sticky="w")
        self.sp_kopf.grid(row=0, column=5, sticky="w", padx=4)
        self.lbl_kopf.grid_remove()
        self.sp_kopf.grid_remove()
        for widget in (self.cb_blatt, self.cb_kodierung, self.cb_trenn):
            widget.bind("<<ComboboxSelected>>", lambda _e: self._optionen_geaendert())
        self.sp_kopf.bind("<Return>", lambda _e: self._optionen_geaendert())
        self.sp_kopf.bind("<FocusOut>", lambda _e: self._optionen_geaendert())
        self.var_info = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.var_info, foreground=HINWEISFARBE).grid(row=2, column=0, sticky="w",
                                                                                  pady=(2, 0))

        # Namensspalten (zwei Zeilen)
        name = ttk.LabelFrame(self, text="Wo steht der Name?", padding=(6, 2))
        name.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.var_modus = tk.StringVar(value="voll")
        self.var_voll, self.var_vorname, self.var_nachname = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Radiobutton(name, text="Voller Name in einer Spalte:", variable=self.var_modus, value="voll",
                        command=self._modus_geaendert).grid(row=0, column=0, sticky="w")
        self.cb_voll = self._auswahl(name, self.var_voll, 0, 1, breite=22)
        ttk.Label(name, text="(z. B. „Mustermann, Max“)", foreground=HINWEISFARBE).grid(row=0, column=2,
                                                                                       columnspan=3, sticky="w")
        ttk.Radiobutton(name, text="Zwei Spalten – Vorname:", variable=self.var_modus, value="getrennt",
                        command=self._modus_geaendert).grid(row=1, column=0, sticky="w")
        self.cb_vorname = self._auswahl(name, self.var_vorname, 1, 1, breite=22)
        ttk.Label(name, text="Nachname:").grid(row=1, column=2, sticky="w")
        self.cb_nachname = self._auswahl(name, self.var_nachname, 1, 3, breite=22)

        # Zusatzmerkmale (eine Zeile)
        zusatz = ttk.LabelFrame(self, text="Zusatzmerkmale (nur genutzt, wenn in beiden Listen gewählt)",
                                padding=(6, 2))
        zusatz.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.var_klasse, self.var_geburt, self.var_mail = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(zusatz, text="Klasse:").grid(row=0, column=0, sticky="w")
        self.cb_klasse = self._auswahl(zusatz, self.var_klasse, 0, 1, breite=13)
        ttk.Label(zusatz, text="Geburtsdatum:").grid(row=0, column=2, sticky="w")
        self.cb_geburt = self._auswahl(zusatz, self.var_geburt, 0, 3, breite=13)
        ttk.Label(zusatz, text="E-Mail:").grid(row=0, column=4, sticky="w")
        self.cb_mail = self._auswahl(zusatz, self.var_mail, 0, 5, breite=13)

        # Warnungen
        self.var_warnung = tk.StringVar(value="")
        self.lbl_warnung = ttk.Label(self, textvariable=self.var_warnung, foreground=WARNFARBE, justify="left")
        self.lbl_warnung.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        self.bind("<Configure>", lambda e: self.lbl_warnung.configure(wraplength=max(200, e.width - 30)))

        # Vorschau
        vorschau = ttk.LabelFrame(self, text="Vorschau (erste 10 Zeilen)", padding=4)
        vorschau.grid(row=6, column=0, sticky="nsew", pady=(6, 0))
        self.rowconfigure(6, weight=1)
        vorschau.columnconfigure(0, weight=1)
        vorschau.rowconfigure(0, weight=1)
        self.baum = ttk.Treeview(vorschau, show="headings", height=10)
        self.baum.grid(row=0, column=0, sticky="nsew")
        quer = ttk.Scrollbar(vorschau, orient="horizontal", command=self.baum.xview)
        quer.grid(row=1, column=0, sticky="ew")
        hoch = ttk.Scrollbar(vorschau, orient="vertical", command=self.baum.yview)
        hoch.grid(row=0, column=1, sticky="ns")
        self.baum.configure(xscrollcommand=quer.set, yscrollcommand=hoch.set)

    def _auswahl(self, master: tk.Misc, var: tk.StringVar, zeile: int, spalte: int, breite: int) -> ttk.Combobox:
        auswahl = ttk.Combobox(master, textvariable=var, state="disabled", width=breite)
        auswahl.grid(row=zeile, column=spalte, sticky="w", padx=(2, 10), pady=2)
        auswahl.bind("<<ComboboxSelected>>", lambda _e: self._spalten_geaendert())
        return auswahl

    # --- Aktionen ---------------------------------------------------------------------

    def datei_waehlen(self) -> None:
        pfad = filedialog.askopenfilename(parent=self, title=f"{self.cget('text')} auswählen", filetypes=DATEITYPEN)
        if pfad:
            self.laden(Path(pfad))

    def laden(self, pfad: Path) -> bool:
        """Lädt eine Datei; zeigt Fehler verständlich an. Gibt True bei Erfolg zurück."""
        try:
            self.liste.laden(pfad)
        except Exception as fehler:  # noqa: BLE001 – jede Meldung soll im Fenster erscheinen
            messagebox.showerror("Datei kann nicht gelesen werden", _fehlertext(fehler), parent=self)
            return False
        self.var_kopf.set("1")
        self.var_kodierung.set("automatisch")
        self.var_trenn.set("automatisch")
        self.aktualisieren()
        self.geaendert()
        return True

    def _optionen_geaendert(self) -> None:
        if self._aktualisiert or not self.liste.geladen:
            return
        try:
            kopfzeile = int(self.var_kopf.get())
        except ValueError:
            kopfzeile = 1
        optionen = Einleseoptionen(
            blatt=self.var_blatt.get() or None if self.liste.ist_excel else None,
            kopfzeile=max(1, kopfzeile),
            trennzeichen=None if self.liste.ist_excel else TRENNZEICHEN.get(self.var_trenn.get()),
            kodierung=None if self.liste.ist_excel else KODIERUNGEN.get(self.var_kodierung.get()),
        )
        if optionen == self.liste.optionen:
            return
        try:
            self.liste.optionen_setzen(optionen)
        except Exception as fehler:  # noqa: BLE001
            messagebox.showerror("Datei kann nicht gelesen werden", _fehlertext(fehler), parent=self)
            return
        self.aktualisieren()
        self.geaendert()

    def _modus_geaendert(self) -> None:
        if self.var_modus.get() == "voll":
            self.var_vorname.set(KEINE)
            self.var_nachname.set(KEINE)
        else:
            self.var_voll.set(KEINE)
        self._spalten_geaendert()

    def _spalten_geaendert(self) -> None:
        if self._aktualisiert or not self.liste.geladen:
            return
        if self.var_modus.get() == "voll":
            self.liste.namen_setzen(voll=self.var_voll.get(), vorname=None, nachname=None)
        else:
            self.liste.namen_setzen(voll=None, vorname=self.var_vorname.get(), nachname=self.var_nachname.get())
        self.liste.zusatz_setzen(self.var_klasse.get(), self.var_geburt.get(), self.var_mail.get())
        self._zustand_auswahl()
        self._warnungen_zeigen()
        self._vorschau_zeigen()
        self.geaendert()

    # --- Anzeige ----------------------------------------------------------------------

    def aktualisieren(self) -> None:
        """Überträgt den Zustand der Liste in die Bedienelemente."""
        self._aktualisiert = True
        try:
            liste = self.liste
            self.var_datei.set(str(liste.pfad) if liste.pfad else "(noch keine Datei gewählt)")
            self.var_info.set(liste.info())
            sichtbar = self._excel_felder if liste.ist_excel else self._csv_felder if liste.geladen else []
            for widget, _spalte in self._excel_felder + self._csv_felder:
                widget.grid() if (widget, _spalte) in sichtbar else widget.grid_remove()
            for widget in (self.lbl_kopf, self.sp_kopf):
                widget.grid() if liste.geladen else widget.grid_remove()
            if liste.ist_excel:
                self.cb_blatt.configure(values=liste.blaetter)
                self.var_blatt.set(liste.tabelle.blatt if liste.tabelle and liste.tabelle.blatt else "")
            werte = liste.spalten_auswahl()
            for auswahl in (self.cb_voll, self.cb_vorname, self.cb_nachname, self.cb_klasse, self.cb_geburt,
                            self.cb_mail):
                auswahl.configure(values=werte)
            namen, zusatz = liste.namen, liste.zusatz
            self.var_modus.set("getrennt" if namen.art in ("getrennt", "nur_vorname", "nur_nachname") else "voll")
            self.var_voll.set(namen.voll or KEINE)
            self.var_vorname.set(namen.vorname or KEINE)
            self.var_nachname.set(namen.nachname or KEINE)
            self.var_klasse.set(zusatz.klasse or KEINE)
            self.var_geburt.set(zusatz.geburtsdatum or KEINE)
            self.var_mail.set(zusatz.email or KEINE)
            self._zustand_auswahl()
            self._warnungen_zeigen()
            self._vorschau_zeigen()
        finally:
            self._aktualisiert = False

    def _zustand_auswahl(self) -> None:
        if not self.liste.geladen:
            return
        voll = self.var_modus.get() == "voll"
        self.cb_voll.configure(state="readonly" if voll else "disabled")
        self.cb_vorname.configure(state="disabled" if voll else "readonly")
        self.cb_nachname.configure(state="disabled" if voll else "readonly")
        for auswahl in (self.cb_klasse, self.cb_geburt, self.cb_mail):
            auswahl.configure(state="readonly")

    def _warnungen_zeigen(self) -> None:
        if self.liste.geladen and self.liste.namen.art == "keine":
            self.var_warnung.set("Keine Namensspalte gefunden – bitte oben auswählen.")
            return
        self.var_warnung.set("\n".join(f"• {w}" for w in self.liste.warnungen()))

    def _vorschau_zeigen(self) -> None:
        kopf, zeilen = self.liste.vorschau(10)
        self.baum.delete(*self.baum.get_children())
        rollen = {self.liste.namen.voll: "Name", self.liste.namen.vorname: "Vorname",
                  self.liste.namen.nachname: "Nachname", self.liste.zusatz.klasse: "Klasse",
                  self.liste.zusatz.geburtsdatum: "Geburtsdatum", self.liste.zusatz.email: "E-Mail"}
        kennungen = [f"s{k}" for k in range(len(kopf))]
        self.baum.configure(columns=kennungen)
        for kennung, spalte in zip(kennungen, kopf):
            rolle = rollen.get(spalte)
            self.baum.heading(kennung, text=f"[{rolle}] {spalte}" if rolle else spalte)
            self.baum.column(kennung, width=150 if rolle else 110, minwidth=60, stretch=False)
        for zeile in zeilen:
            self.baum.insert("", "end", values=zeile)


class Hauptfenster:
    """Hauptfenster mit zwei Listenbereichen und dem Bereich „Zusammenführen“."""

    def __init__(self, wurzel: tk.Tk, sitzung: Sitzung | None = None) -> None:
        self.wurzel = wurzel
        self.sitzung = sitzung or Sitzung()
        self.ergebnis: Laufergebnis | None = None
        self._warteschlange: queue.Queue[tuple] = queue.Queue()
        self._laeuft = False
        self._ausgabe_von_hand = False
        self._ersetzen_bestaetigt: Path | None = None

        wurzel.title(f"{TITEL} (Version {__version__})")
        wurzel.protocol("WM_DELETE_WINDOW", self.schliessen)
        wurzel.columnconfigure(0, weight=1)
        wurzel.rowconfigure(0, weight=1)
        haupt = ttk.Frame(wurzel, padding=8)
        haupt.grid(row=0, column=0, sticky="nsew")
        haupt.columnconfigure(0, weight=1, uniform="listen")
        haupt.columnconfigure(1, weight=1, uniform="listen")
        haupt.rowconfigure(0, weight=1)

        self.rahmen_a = ListenRahmen(haupt, self.sitzung.a, "Liste A – Hauptliste (bestimmt die Reihenfolge)",
                                     self._listen_geaendert)
        self.rahmen_a.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.rahmen_b = ListenRahmen(haupt, self.sitzung.b, "Liste B – wird angehängt", self._listen_geaendert)
        self.rahmen_b.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        unten = ttk.LabelFrame(haupt, text="Zusammenführen", padding=8)
        unten.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        unten.columnconfigure(1, weight=1)

        regler = ttk.Frame(unten)
        regler.grid(row=0, column=0, columnspan=4, sticky="w")
        self.var_sicher = tk.IntVar(value=self.sitzung.sicher)
        self.var_pruefen = tk.IntVar(value=self.sitzung.pruefen)
        self.var_sicher_text = tk.StringVar(value=str(self.sitzung.sicher))
        self.var_pruefen_text = tk.StringVar(value=str(self.sitzung.pruefen))
        ttk.Label(regler, text="„Sicher“ ab:").grid(row=0, column=0, sticky="w")
        ttk.Scale(regler, from_=50, to=100, orient="horizontal", length=170, variable=self.var_sicher,
                  command=lambda _w: self._schwellen_angleichen("sicher")).grid(row=0, column=1, padx=4)
        ttk.Label(regler, textvariable=self.var_sicher_text, width=4).grid(row=0, column=2, sticky="w")
        ttk.Label(regler, text="„Prüfen“ ab:").grid(row=0, column=3, sticky="w", padx=(12, 0))
        ttk.Scale(regler, from_=30, to=100, orient="horizontal", length=170, variable=self.var_pruefen,
                  command=lambda _w: self._schwellen_angleichen("pruefen")).grid(row=0, column=4, padx=4)
        ttk.Label(regler, textvariable=self.var_pruefen_text, width=4).grid(row=0, column=5, sticky="w")
        self.var_nach_status = tk.BooleanVar(value=self.sitzung.sortierung == "status")
        self.var_kandidaten = tk.BooleanVar(value=self.sitzung.kandidaten)
        ttk.Checkbutton(regler, text="Prüfen-Zeilen oben (nach Status sortieren)",
                        variable=self.var_nach_status).grid(row=0, column=6, sticky="w", padx=(12, 0))
        ttk.Checkbutton(regler, text="Blatt „Kandidaten“ anlegen",
                        variable=self.var_kandidaten).grid(row=0, column=7, sticky="w", padx=(12, 0))

        ttk.Label(unten, text="Ergebnisdatei:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_ausgabe = tk.StringVar()
        eingabe = ttk.Entry(unten, textvariable=self.var_ausgabe)
        eingabe.grid(row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=(6, 0))
        eingabe.bind("<KeyRelease>", lambda _e: setattr(self, "_ausgabe_von_hand", True))
        ttk.Button(unten, text="Speichern unter …", command=self.ausgabe_waehlen).grid(row=1, column=3, pady=(6, 0))

        aktion = ttk.Frame(unten)
        aktion.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        aktion.columnconfigure(1, weight=1)
        self.knopf_start = ttk.Button(aktion, text="Zusammenführen", command=self.zusammenfuehren)
        self.knopf_start.grid(row=0, column=0, sticky="w")
        self.fortschritt = ttk.Progressbar(aktion, mode="determinate", maximum=100)
        self.fortschritt.grid(row=0, column=1, sticky="ew", padx=8)
        self.knopf_oeffnen = ttk.Button(aktion, text="Ergebnis öffnen", state="disabled",
                                        command=lambda: self._oeffnen(datei=True))
        self.knopf_oeffnen.grid(row=0, column=2)
        self.knopf_ordner = ttk.Button(aktion, text="Ordner öffnen", state="disabled",
                                       command=lambda: self._oeffnen(datei=False))
        self.knopf_ordner.grid(row=0, column=3, padx=(4, 0))
        self.var_status = tk.StringVar(value="Bitte beide Listen auswählen. Alles läuft offline auf diesem Rechner.")
        self.lbl_status = ttk.Label(unten, textvariable=self.var_status, justify="left")
        self.lbl_status.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.var_warnung = tk.StringVar(value="")
        self.lbl_warnung = ttk.Label(unten, textvariable=self.var_warnung, foreground=WARNFARBE, justify="left")
        self.lbl_warnung.grid(row=4, column=0, columnspan=4, sticky="w")
        unten.bind("<Configure>", lambda e: (self.lbl_status.configure(wraplength=e.width - 20),
                                              self.lbl_warnung.configure(wraplength=e.width - 20)))

    # --- Hilfen -------------------------------------------------------------------------

    def schliessen(self) -> None:
        """Fenster schließen – nicht während eines Laufs (sonst bliebe der Arbeitsordner liegen)."""
        if self._laeuft:
            messagebox.showinfo("Bitte warten", "Das Zusammenführen läuft noch. Bitte warten, bis es fertig ist.",
                                parent=self.wurzel)
            return
        self.wurzel.destroy()

    def _listen_geaendert(self) -> None:
        if not self._ausgabe_von_hand:
            vorschlag = self.sitzung.ausgabe_vorschlag()
            self.var_ausgabe.set(str(vorschlag) if vorschlag else "")
        self.knopf_oeffnen.configure(state="disabled")
        self.knopf_ordner.configure(state="disabled")
        self.var_warnung.set("")

    def _schwellen_angleichen(self, geaendert: str) -> None:
        """Ganze Zahlen; „Prüfen“ nie über „Sicher“."""
        sicher, pruefen = round(float(self.var_sicher.get())), round(float(self.var_pruefen.get()))
        if pruefen > sicher:
            if geaendert == "sicher":
                pruefen = sicher
            else:
                sicher = pruefen
        self.var_sicher.set(sicher)
        self.var_pruefen.set(pruefen)
        self.var_sicher_text.set(str(sicher))
        self.var_pruefen_text.set(str(pruefen))

    def ausgabe_waehlen(self) -> None:
        vorschlag = Path(self.var_ausgabe.get()) if self.var_ausgabe.get() else self.sitzung.ausgabe_vorschlag()
        pfad = filedialog.asksaveasfilename(
            parent=self.wurzel, title="Ergebnisdatei speichern unter", defaultextension=".xlsx",
            filetypes=[("Excel-Arbeitsmappe", "*.xlsx")],
            initialdir=str(vorschlag.parent) if vorschlag else None,
            initialfile=vorschlag.name if vorschlag else "ergebnis.xlsx",
        )
        if pfad:
            self.var_ausgabe.set(pfad)
            self._ausgabe_von_hand = True
            self._ersetzen_bestaetigt = Path(pfad) if Path(pfad).exists() else None  # Dialog hat schon gefragt

    def _oeffnen(self, datei: bool) -> None:
        if self.sitzung.ausgabe is None:
            return
        try:
            datei_oeffnen(self.sitzung.ausgabe if datei else self.sitzung.ausgabe.parent)
        except Exception as fehler:  # noqa: BLE001
            messagebox.showerror("Öffnen nicht möglich", _fehlertext(fehler), parent=self.wurzel)

    def _bedienung_sperren(self, gesperrt: bool) -> None:
        self.knopf_start.configure(state="disabled" if gesperrt else "normal")
        self.wurzel.configure(cursor="watch" if gesperrt else "")

    # --- Lauf ---------------------------------------------------------------------------

    def zusammenfuehren(self, nachfragen: bool = True) -> bool:
        """Startet den Abgleich im Hintergrund. Gibt False zurück, wenn noch etwas fehlt."""
        if self._laeuft:
            return False
        s = self.sitzung
        s.sicher, s.pruefen = round(float(self.var_sicher.get())), round(float(self.var_pruefen.get()))
        s.sortierung = "status" if self.var_nach_status.get() else "original"
        s.kandidaten = bool(self.var_kandidaten.get())
        s.ausgabe = Path(self.var_ausgabe.get().strip()) if self.var_ausgabe.get().strip() else None
        fehler = s.pruefen_vor_lauf()
        if fehler:
            messagebox.showwarning("Noch nicht bereit", "\n".join(fehler), parent=self.wurzel)
            return False
        warnungen = s.a.warnungen() + s.b.warnungen()
        if nachfragen and warnungen and not messagebox.askyesno(
                "Warnungen zur Spaltenwahl",
                "\n\n".join(warnungen) + "\n\nTrotzdem zusammenführen?", parent=self.wurzel):
            return False
        ueberschreiben = False
        if s.ausgabe is not None and s.ausgabe.exists():
            if self._ersetzen_bestaetigt == s.ausgabe or not nachfragen:
                ueberschreiben = True
            elif messagebox.askyesno("Datei ersetzen?", f"Die Datei „{s.ausgabe.name}“ gibt es schon. Ersetzen?",
                                     parent=self.wurzel):
                ueberschreiben = True
            else:
                return False
        self._laeuft = True
        self.ergebnis = None
        self._bedienung_sperren(True)
        self.knopf_oeffnen.configure(state="disabled")
        self.knopf_ordner.configure(state="disabled")
        self.var_warnung.set("")
        self.var_status.set("Vergleiche …")
        self.fortschritt.configure(value=0)
        threading.Thread(target=self._arbeit, args=(ueberschreiben,), daemon=True).start()
        self.wurzel.after(100, self._abfragen)
        return True

    def _arbeit(self, ueberschreiben: bool) -> None:
        """Läuft im Hintergrund-Thread: keine tkinter-Aufrufe, nur Nachrichten in die Warteschlange."""
        try:
            ergebnis = self.sitzung.ausfuehren(
                lambda text, anteil: self._warteschlange.put(("fortschritt", text, anteil)), ueberschreiben)
            self._warteschlange.put(("fertig", ergebnis))
        except Exception as fehler:  # noqa: BLE001
            self._warteschlange.put(("fehler", _fehlertext(fehler)))

    def _abfragen(self) -> None:
        try:
            while True:
                nachricht = self._warteschlange.get_nowait()
                art = nachricht[0]
                if art == "fortschritt":
                    _art, text, anteil = nachricht
                    self.fortschritt.configure(value=round(anteil * 100))
                    self.var_status.set(f"{text} … {round(anteil * 100)} %")
                elif art == "fertig":
                    self._fertig(nachricht[1])
                    return
                elif art == "fehler":
                    self._laeuft = False
                    self._bedienung_sperren(False)
                    self.fortschritt.configure(value=0)
                    self.var_status.set("Abgebrochen.")
                    messagebox.showerror("Zusammenführen nicht möglich", nachricht[1], parent=self.wurzel)
                    return
        except queue.Empty:
            pass
        self.wurzel.after(100, self._abfragen)

    def _fertig(self, ergebnis: Laufergebnis) -> None:
        self._laeuft = False
        self.ergebnis = ergebnis
        self._bedienung_sperren(False)
        self.fortschritt.configure(value=100)
        self.var_status.set(f"Fertig – gespeichert als „{self.sitzung.ausgabe.name}“ im Ordner "
                            f"„{self.sitzung.ausgabe.parent}“.\n{Sitzung.zusammenfassung(ergebnis)}")
        self.var_warnung.set("\n".join(f"• {w}" for w in ergebnis.warnungen))
        self.knopf_oeffnen.configure(state="normal")
        self.knopf_ordner.configure(state="normal")


def _hohe_aufloesung() -> None:
    """Unter Windows scharfe Schrift auf hochauflösenden Bildschirmen."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def fenster_erzeugen() -> tuple[tk.Tk, Hauptfenster]:
    """Erzeugt das Hauptfenster in passender Größe."""
    _hohe_aufloesung()
    wurzel = tk.Tk()
    if sys.platform.startswith("linux"):
        stil = ttk.Style(wurzel)
        stil.theme_use("clam")
        stil.configure("Horizontal.TProgressbar", background="#4A7FC1")  # sonst kaum vom Hintergrund zu unterscheiden
    breite = min(1440, wurzel.winfo_screenwidth() - 40)
    hoehe = min(940, wurzel.winfo_screenheight() - 80)
    wurzel.geometry(f"{breite}x{hoehe}")
    wurzel.minsize(900, 600)
    return wurzel, Hauptfenster(wurzel)


def _selbsttest(argumente: Sequence[str], zeitlimit_s: float = 120) -> int:
    """Automatischer Probelauf für die CI: Fenster öffnen, zwei Dateien laden, zusammenführen, schließen.

    Meldungsfenster werden in diesem Modus nicht angezeigt (sonst bliebe die CI hängen),
    sondern führen zum Fehlschlag (Rückgabewert 1).
    """
    import time

    datei_a, datei_b, ausgabe = (Path(a) for a in argumente)
    probleme: list[str] = []
    messagebox.showerror = lambda titel, text, **_k: probleme.append(titel)  # type: ignore[assignment]
    messagebox.showwarning = lambda titel, text, **_k: probleme.append(titel)  # type: ignore[assignment]
    messagebox.showinfo = lambda titel, text, **_k: None  # type: ignore[assignment]
    messagebox.askyesno = lambda titel, text, **_k: True  # type: ignore[assignment]
    wurzel, fenster = fenster_erzeugen()
    ende = time.monotonic() + zeitlimit_s
    erfolg = {"ok": False}

    def ablauf() -> None:
        if not (fenster.rahmen_a.laden(datei_a) and fenster.rahmen_b.laden(datei_b)):
            wurzel.destroy()
            return
        fenster.var_ausgabe.set(str(ausgabe))
        fenster._ausgabe_von_hand = True
        if not fenster.zusammenfuehren(nachfragen=False):
            wurzel.destroy()
            return
        warten()

    def warten() -> None:
        if fenster._laeuft and time.monotonic() < ende:
            wurzel.after(200, warten)
            return
        erfolg["ok"] = not fenster._laeuft and fenster.ergebnis is not None and ausgabe.exists() and not probleme
        wurzel.destroy()

    wurzel.after(300, ablauf)
    wurzel.mainloop()
    return 0 if erfolg["ok"] else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Startet die Oberfläche. ``--selbsttest A B AUSGABE`` führt einen automatischen Probelauf aus."""
    argumente = list(sys.argv[1:] if argv is None else argv)
    if argumente[:1] == ["--selbsttest"] and len(argumente) == 4:
        return _selbsttest(argumente[1:])
    wurzel, _fenster = fenster_erzeugen()
    wurzel.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
