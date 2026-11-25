# namematch – Personenlisten offline zusammenführen

Führt zwei Personenlisten (Excel oder CSV) über den Namen zusammen, ohne Spalten oder Zeilen zu
verlieren, und macht jeden Treffer per Auge prüfbar. **Läuft vollständig offline** – die Daten
verlassen den Rechner nie (keine Netzwerkzugriffe, keine Telemetrie, keine Cloud, keine KI-Dienste).

Anforderungen: [`ANFORDERUNGEN.md`](ANFORDERUNGEN.md) · Projektregeln: [`CLAUDE.md`](CLAUDE.md)

## Installation

Python 3.11 oder neuer. Einmalig (mit Internet):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Unter Windows: `.venv\Scripts\pip install -r requirements.txt`.

### Installation ohne Internet auf dem Zielrechner

Auf einem Rechner **mit gleichem Betriebssystem und gleicher Python-Version** die Pakete herunterladen:

```bash
pip download -r requirements.txt -d wheels
```

Projektordner und `wheels/` auf den Zielrechner kopieren und dort installieren:

```bash
python3 -m venv .venv
.venv/bin/pip install --no-index --find-links wheels -r requirements.txt
```

## Bedienung (Kommandozeile)

```bash
.venv/bin/python -m namematch liste_a.xlsx liste_b.csv -o ergebnis.xlsx
```

- **A** ist die Hauptliste und bestimmt die Reihenfolge, **B** wird angehängt.
- Die Namens- und Zusatzspalten (Klasse, Geburtsdatum, E-Mail) werden anhand der Überschriften
  erkannt und angezeigt; vor dem Lauf kommt eine Rückfrage. `--ja` übernimmt den Vorschlag ohne Rückfrage.
- `--dry-run` zeigt nur erkannte Spalten und Statistik und schreibt nichts.

Spalten selbst festlegen (dann entfällt die Rückfrage):

```bash
.venv/bin/python -m namematch a.xlsx b.csv -o ergebnis.xlsx --name-a "Name" --vorname-b "Vorname" --nachname-b "Nachname"
```

Wichtige Optionen (vollständig: `python -m namematch --help`):

| Option | Bedeutung |
| --- | --- |
| `--name-a/-b`, `--vorname-a/-b`, `--nachname-a/-b` | Namensspalten (voller Name **oder** Vor-/Nachname, auch nur eins davon) |
| `--klasse-a/-b`, `--geburtsdatum-a/-b`, `--email-a/-b` | Zusatzmerkmale; `--ohne-zusatzmerkmale` vergleicht nur Namen |
| `--sheet-a/-b` | Tabellenblatt (Standard: erstes Blatt) |
| `--kopfzeile-a/-b N` | Überschriften stehen in Zeile N (bei Titelzeilen darüber) |
| `--trennzeichen-a/-b`, `--kodierung-a/-b` | CSV-Trennzeichen (`;` `,` `tab` `\|`) und Kodierung (z. B. `cp1252`) – Standard: automatisch |
| `--sicher 90`, `--pruefen 70` | Schwellen |
| `--sortierung status` | Prüfen-/Mehrdeutig-Zeilen stehen oben zusammen |
| `--config einstellungen.toml` | Einstellungsdatei, Vorlage: [`einstellungen.beispiel.toml`](einstellungen.beispiel.toml) |
| `--ohne-kandidaten`, `--ueberschreiben`, `-v` | kein Blatt „Kandidaten“ · vorhandene Ergebnisdatei ersetzen · Protokollmeldungen |

Exit-Codes: 0 = OK, 1 = Fehler, 2 = Bedienfehler (z. B. fehlendes `-o`), 3 = abgebrochen.

## Ergebnisdatei

**Blatt „Zusammengeführt“** – jede Zeile aus A und jede Zeile aus B genau einmal, alle Spalten:

| Match_Status | Match_Score | Match_Hinweis | A_… (alle Spalten aus A) | B_… (alle Spalten aus B) |
| --- | --- | --- | --- | --- |

| Status | Farbe | Bedeutung |
| --- | --- | --- |
| Sicher | grün | Score ≥ 90: Name nach Vereinheitlichung gleich (oder Tippfehler + gleiches Geburtsdatum/E-Mail) |
| Prüfen | gelb | Score 70–89: ähnlich, Sichtprüfung nötig |
| Mehrdeutig | gelb | zwei Kandidaten liegen weniger als 5 Punkte auseinander; der 2. Kandidat steht im Hinweis |
| Nur in A | rot | kein Treffer (Hinweis nennt ggf. den besten Kandidaten unter der Schwelle) |
| Nur in B | grau | Zeile aus B ohne Treffer, unten angehängt |

Werte werden unverändert übernommen: Excel-Werte mit Typ und Zahlenformat (ein Datum bleibt ein Datum),
CSV-Werte als Text (führende Nullen bleiben). Kopfzeile fixiert, Autofilter, passende Spaltenbreiten.

**Blatt „Protokoll“**: Eingabedateien, Kodierung/Trennzeichen, gewählte Spalten, Schwellen, Anzahl je Status,
doppelte Namen innerhalb einer Datei, Zeitpunkt, Tool-Version.
**Blatt „Kandidaten“**: je Person aus A die drei besten Kandidaten aus B mit Score und Zeilennummer.

## So wird verglichen

1. **Vereinheitlichen** (nur intern): klein, ä=ae, ö=oe, ü=ue, ß=ss, Akzente weg (José=Jose), Titel weg
   (Dr., Prof., Herr, Frau, Dipl.-Ing., jun., sen. …), „Nachname, Vorname“ erkannt, Bindestriche/Doppelnamen
   als Teile, von/van/de gehören zum Nachnamen.
2. **Score 0–100**: Vor- und Nachname getrennt (Nachname wiegt stärker) plus reihenfolgeunabhängiger
   Gesamtvergleich, Tippfehler-Toleranz (Levenshtein). Fehlt die Reihenfolge („Mustermann Max“), werden
   beide Lesarten probiert.
3. **Regeln**: „Sicher“ nur, wenn die Namen nach Vereinheitlichung gleich sind; jede echte Abweichung
   (Tippfehler, Kurzform Alex/Alexander, Doppelname teilweise) bleibt in „Prüfen“. Steht auf einer Seite nur
   ein Vor- oder Nachname, ist der Score auf 80 gedeckelt.
4. **Zusatzmerkmale**: Klasse gleich +5 (abweichend nur Hinweis, „7 b“ = „07B“); Geburtsdatum/E-Mail gleich
   +10, abweichend −10. Merkmale allein erzeugen nie einen Treffer; die Klasse allein hebt nie auf „Sicher“.
5. **Zuordnung** global 1:1 nach höchstem Score (jede Zeile aus B höchstens einmal), deterministisch.

## Datenschutz

- Kein Netzwerkcode (automatisch geprüft), alle Tests laufen mit gesperrten Sockets (`pytest-socket`).
- Eingabedateien werden nur gelesen. Zwischendateien beim Speichern entstehen in einem versteckten Ordner
  im Ausgabeordner und werden sofort gelöscht – nicht im System-Temp-Verzeichnis.
- Konsolen- und Protokollmeldungen enthalten nur Zahlen, Spaltennamen und Dateinamen, keine Zellinhalte.
  Unerwartete Fehler zeigen nur den Fehlertyp (Details nur mit `--debug`).
- Echte Listen gehören **nicht** in dieses Repository. Lokal kann der Ordner `echte_daten/` genutzt werden
  (per `.gitignore` und `.claude/settings.json` gesperrt).

## Entwicklung

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                      # alle Tests, Netzwerk gesperrt
.venv/bin/python -m pytest -m "not langsam"     # ohne 5.000×5.000-Lasttest
.venv/bin/python -m tests.fixtures.erzeuge_fixtures   # synthetische Testdateien neu erzeugen
```

```
namematch/
  io.py          Einlesen CSV/Excel, Kodierung, Trennzeichen
  columns.py     Erkennung der Namens- und Zusatzspalten
  normalize.py   Namensnormalisierung, Klasse/Datum/E-Mail vereinheitlichen
  matcher.py     Scoring, Einstufung, 1:1-Zuordnung
  output.py      Excel-Ausgabe, Farben, Protokoll- und Kandidatenblatt
  pipeline.py    Gesamtablauf als Bibliotheksfunktionen (für CLI und GUI)
  cli.py         Kommandozeile
  config.py      Standardwerte + TOML laden
  daten/spitznamen.txt   editierbare Kurzformliste
tests/
  fixtures/      synthetische Testdateien + Generator (keine echten Daten!)
```
