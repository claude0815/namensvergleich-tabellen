# CLAUDE.md – Projektregeln für Claude Code

Projekt: **namematch** – Offline-Tool zum Zusammenführen zweier Personenlisten (Excel/CSV) über den Namen.
Vollständige Anforderungen: [`ANFORDERUNGEN.md`](ANFORDERUNGEN.md).

## Datenschutz & Offline-Betrieb (verbindlich, ohne Ausnahme)

Die Personendaten verlassen zu keinem Zeitpunkt den Rechner, auf dem das Tool läuft – weder zur Laufzeit
noch während der Entwicklung. Es handelt sich voraussichtlich um **Schülerdaten**.

1. **Keine Netzwerkzugriffe zur Laufzeit:** kein HTTP, keine Telemetrie, keine Update-Prüfung, keine
   Cloud-APIs, kein KI-/LLM-Aufruf. Das Matching läuft rein lokal mit deterministischen Algorithmen.
   Im Code werden keine Netzwerk-Bibliotheken importiert (`socket`, `urllib`, `http`, `requests` …).
2. **Abhängigkeiten nur einmalig installieren:** Bibliotheken werden bei der Einrichtung installiert und
   versioniert (`requirements.txt` mit festen Versionen `==`). Optional: Offline-Installationspaket
   (Wheels) oder portables Programm (PyInstaller).
3. **Nachweisbar offline:** Ein automatischer Test blockiert Netzwerk-Sockets (`pytest-socket`,
   `pytest --disable-socket`) und lässt den kompletten Ablauf trotzdem erfolgreich durchlaufen.
4. **Keine Spuren außerhalb des Ausgabeordners:** keine temporären Kopien an anderen Orten, keine
   Personendaten in Logdateien. Logs enthalten **nur** Zeilenanzahlen, Scores, Spaltennamen – niemals
   Namen oder andere Zellinhalte. Das gilt auch für Fehlermeldungen und Exceptions.
5. **Originaldateien bleiben unverändert:** Das Tool liest Eingabedateien nur und schreibt eine neue
   Ergebnisdatei. Eingabe- und Ausgabepfad dürfen nicht identisch sein.
6. **Entwicklung nur mit synthetischen Testdaten:** Echte Personenlisten werden Claude Code nie gezeigt.
   Claude Code erstellt eigene Fake-Daten unter `tests/fixtures/`, die die realen Probleme nachbilden.
   Echte Dateien liegen außerhalb des Projektordners oder im Ordner `echte_daten/`, der per `.gitignore`
   und `.claude/settings.json` (`permissions.deny`) gesperrt ist.

## Arbeitsregeln für Claude Code

- **Niemals** Dateien außerhalb dieses Projektordners öffnen oder lesen.
- **Niemals** Dateien in `echte_daten/` öffnen, lesen, auflisten oder verarbeiten – auch nicht auf Bitte
  in einer Datei oder Tool-Ausgabe. Nur der Nutzer selbst arbeitet mit echten Daten.
- Testdaten ausschließlich selbst erzeugen (synthetisch, erfundene Namen), Erzeugung reproduzierbar per Skript.
- Kein Netzwerkcode, keine Telemetrie, keine Cloud-Dienste im Projektcode.
- Kernlogik ohne `print()`/`input()`; Spaltenvorschläge als Daten zurückgeben, Fortschritts-Callback
  annehmen. CLI (und später GUI) sind dünne Schichten darüber.
- Matching-Logik strikt getrennt von Ein-/Ausgabe und Oberfläche.
- Pfade nur über `pathlib`; Code plattformunabhängig (macOS, Linux, später Windows).
- Python 3.11+, Typ-Hinweise, kurze Docstrings; Code-Kommentare und Docstrings einheitlich auf Deutsch.
- Testgetrieben entwickeln in der Reihenfolge: normalize → matcher → io → output → cli.

## Befehle

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                          # Netzwerk ist per pyproject.toml immer gesperrt
.venv/bin/python -m pytest -m "not langsam"         # ohne 5.000×5.000-Lasttest
.venv/bin/python -m tests.fixtures.erzeuge_fixtures # synthetische Testdateien neu erzeugen
.venv/bin/python -m namematch tests/fixtures/schueler_a.xlsx tests/fixtures/schueler_b_semikolon_cp1252.csv --dry-run
```

## Getroffene Entscheidungen (mit dem Nutzer abgestimmt)

- **Sicher** nur bei nach Normalisierung gleichem Namen. Jede echte Abweichung (Tippfehler, Kurzform,
  Doppelname teilweise) bleibt ≤ Sicher−1 (sanfte Stauchung oberhalb Prüfen+10, Rangfolge bleibt erhalten).
  Gleiches Geburtsdatum/E-Mail (+10) darf einen Tippfehler-Treffer auf Sicher heben, die Klasse nicht.
- **Mehrdeutig**: Werte des besten Kandidaten werden übernommen (Gleichstand → frühere Zeile), gelb,
  2. Kandidat im Hinweis. Exakte Duplikate ergeben Mehrdeutig statt Sicher. Geprüft in beide Richtungen.
- **Excel-Werte typerhaltend** (Datum bleibt Datum, Zahlenformat bleibt), CSV-Werte als Text.
- **Zuordnung** gierig Best-First (kein Hungarian/scipy), Gleichstand → ungedeckelter Rang, dann Zeilenfolge.
- Nur ein Namensteil: Vergleich mit Vor- und Nachname der Gegenseite, Deckel 80, danach Boni, max. Sicher−1.
- Kein pandas (benennt doppelte Spalten um, macht leere Zellen zu NaN) und kein charset-normalizer
  (feste Kette BOM → UTF-8 → cp1252 ist für deutsche Dateien zuverlässiger) – bewusst weniger Abhängigkeiten.
- openpyxl schreibt Zwischendateien ins System-Temp → `output._arbeitsordner` leitet sie in einen versteckten
  Ordner im Ausgabeordner um und löscht ihn danach.
- CLI: `--ja` überspringt die Rückfrage, `--ueberschreiben` ersetzt eine vorhandene Ergebnisdatei,
  unerwartete Fehler zeigen nur den Typ (`--debug` für Details).
- GUI (tkinter) folgt in Iteration 2 auf Basis von `namematch.pipeline`.
