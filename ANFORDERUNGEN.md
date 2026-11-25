# Auftrag an Claude Code

Wir entwickeln das unten beschriebene Tool. Lies die Anforderungen vollständig, bevor du beginnst.

**Verbindliche Regeln:**
- Lege zuerst eine `CLAUDE.md` an, die den Abschnitt „Datenschutz & Offline-Betrieb“ als verbindliche Projektregeln festhält, und speichere diese Anforderungen als `ANFORDERUNGEN.md` im Projekt.
- Verwende ausschließlich synthetische Testdaten, die du selbst erzeugst. Öffne oder lies niemals Dateien außerhalb dieses Projektordners.
- Keine Netzwerkzugriffe im Code, keine Telemetrie, keine Cloud-Dienste.

**Vorgehen:**
1. Stelle Rückfragen, falls etwas unklar oder widersprüchlich ist.
2. Schlage die Projektstruktur vor und richte sie mit `requirements.txt` (feste Versionen) ein.
3. Erzeuge synthetische Testdateien (CSV mit `;` und `,`, Excel, verschiedene Namensformate, Klassen-Spalte) unter `tests/fixtures`.
4. Implementiere testgetrieben: normalize → matcher → io → output → cli.
5. Prüfe am Ende alle Akzeptanzkriterien und berichte, welche erfüllt sind.

Die GUI kommt erst in der zweiten Iteration, wenn die Kommandozeile stabil läuft.

---

# Anforderungen: Offline-Tool zum Zusammenführen von Personenlisten

## Ziel & Kontext

Das Tool führt zwei Personenlisten (Excel oder CSV) über den Namen zusammen, ohne Spalten zu verlieren, und macht jeden Treffer per Auge prüfbar.

- **Ausgangslage:** Datei A und Datei B enthalten jeweils Personen. Die Mengen überschneiden sich nur teilweise: manche Personen stehen in beiden Dateien, manche nur in einer.
- **Hauptschlüssel:** der Name. Es gibt keine ID, die zuverlässig in beiden Dateien vorkommt. Zusatzspalten (Klasse, Geburtsdatum, E-Mail) können den Abgleich unterstützen.
- **Uneinheitliche Namen:** Vor- und Nachname mal in einer Spalte, mal in zwei; mal nur ein Vorname; unterschiedliche Reihenfolge, Schreibweisen, Umlaute, Titel.
- **Ergebnis:** eine Tabelle, in der zu jeder Person aus A die Werte aus B danebenstehen, die Namen aus beiden Quellen sichtbar bleiben, jeder Treffer einen Score hat und nicht gefundene Personen markiert sind.
- **Nicht-Ziel:** Das Tool entscheidet nicht endgültig. Unsichere Treffer werden zur manuellen Prüfung markiert, nicht still übernommen.

## Getroffene Entscheidungen

| Thema | Entscheidung |
| --- | --- |
| Basisdatei | A ist immer die Hauptliste und bestimmt die Reihenfolge; B wird angehängt |
| Zuordnung | strikt 1:1, jede Zeile aus B höchstens einmal |
| Zusatzmerkmale | Klasse kommt häufig vor, ist in B aber oft falsch; Geburtsdatum/E-Mail gelegentlich |
| Betriebssysteme | alle drei; macOS und Linux zuerst, Windows danach |
| Bedienung | zuerst Kommandozeile; GUI in Iteration 2, Architektur von Anfang an darauf vorbereitet |
| Mengen | bis ca. 5.000 Zeilen pro Datei |
| Schwellen | Sicher ab 90, Prüfen 70–89, darunter kein Treffer |
| Spaltenpräfixe | `A_` und `B_` |
| Ausgabeformat | .xlsx |

## Datenschutz & Offline-Betrieb (harte Anforderungen)

Die Personendaten verlassen zu keinem Zeitpunkt den Rechner, auf dem das Tool läuft – weder zur Laufzeit noch während der Entwicklung. Es handelt sich voraussichtlich um Schülerdaten.

1. **Keine Netzwerkzugriffe zur Laufzeit:** kein HTTP, keine Telemetrie, keine Update-Prüfung, keine Cloud-APIs, kein KI-/LLM-Aufruf. Das Matching läuft rein lokal mit deterministischen Algorithmen.
2. **Abhängigkeiten nur einmalig installieren:** Bibliotheken werden bei der Einrichtung installiert und versioniert (`requirements.txt` mit festen Versionen). Optional: Offline-Installationspaket (Wheels) oder ein portables Programm, damit auf dem Zielrechner gar kein Internet nötig ist.
3. **Nachweisbar offline:** Ein automatischer Test blockiert Netzwerk-Sockets (z. B. per `pytest-socket`) und lässt den kompletten Ablauf trotzdem erfolgreich durchlaufen.
4. **Keine Spuren außerhalb des Ausgabeordners:** keine temporären Kopien an anderen Orten, keine Personendaten in Logdateien (Logs enthalten nur Zeilenanzahlen, Scores, Spaltennamen).
5. **Originaldateien bleiben unverändert:** Das Tool liest nur und schreibt eine neue Ergebnisdatei.
6. **Entwicklung nur mit synthetischen Testdaten:** Echte Personenlisten werden Claude Code nie gezeigt. Claude Code erstellt eigene Fake-Daten, die die realen Probleme nachbilden. Echte Dateien liegen außerhalb des Projektordners oder in einem per `.gitignore` und Claude-Code-Berechtigungen (`permissions.deny`) gesperrten Ordner.

## Eingaben

Das Tool akzeptiert je eine Datei A und B in den Formaten .xlsx, .xls und .csv, in beliebiger Kombination.

### Dateiformate

| Thema | Anforderung |
| --- | --- |
| Excel | .xlsx (openpyxl), .xls optional; bei mehreren Arbeitsblättern wird das Blatt ausgewählt (Standard: erstes Blatt) |
| CSV-Trennzeichen | automatisch erkennen: `;` (deutsches Excel), `,`, Tab; manuell überschreibbar |
| CSV-Kodierung | automatisch erkennen: UTF-8, UTF-8 mit BOM, Windows-1252; manuell überschreibbar |
| Kopfzeile | erste Zeile als Standard; Startzeile wählbar, falls oberhalb Titelzeilen stehen |
| Datentypen | alles als Text einlesen, damit führende Nullen, Datumsangaben und PLZ unverändert bleiben |
| Leere Zeilen | komplett leere Zeilen ignorieren, aber im Protokoll zählen |

### Namensspalten

Pro Datei wird festgelegt, wo der Name steht. Unterstützte Varianten:

1. **Eine Spalte, voller Name:** „Max Mustermann“, „Mustermann, Max“, „Dr. Max Mustermann“
2. **Zwei Spalten:** Vorname + Nachname (auch in umgekehrter Spaltenreihenfolge)
3. **Nur Vorname oder nur Nachname** in einer der Dateien
4. **Gemischt innerhalb einer Datei:** einzelne Zeilen nur mit Vornamen, andere mit vollem Namen

Die Namensspalten werden anhand typischer Überschriften vorgeschlagen (Name, Vorname, Nachname, Familienname, First Name, Last Name, Surname, Teilnehmer, Person …). Der Vorschlag wird angezeigt und kann vor dem Lauf korrigiert werden.

## Normalisierung & Matching

Jeder Name wird zuerst in eine einheitliche Form gebracht und dann mit einem Score von 0–100 gegen alle Namen der anderen Datei verglichen; der Score entscheidet über sicher, prüfen oder kein Treffer.

Ablauf: Einlesen (als Text) → Namensspalten erkennen und bestätigen → Normalisieren → Score und globale 1:1-Zuordnung → Einstufung in Sicher / Prüfen / Kein Treffer.

### Normalisierung (nur für den Vergleich, Originalwerte bleiben erhalten)

- Klein schreiben, Leerzeichen trimmen, mehrfache Leerzeichen zusammenfassen
- Umlaute und ß vereinheitlichen: ä/ae, ö/oe, ü/ue, ß/ss gelten als gleich
- Akzente entfernen (José → jose, Renée → renee)
- Titel und Zusätze entfernen: Dr., Prof., Herr, Frau, Dipl.-Ing., jun., sen. (Liste konfigurierbar)
- „Nachname, Vorname“ erkennen und umdrehen
- Bindestriche und Doppelnamen als Tokens behandeln (Müller-Lüdenscheidt passt teilweise auf Müller)
- Namenszusätze wie von, van, de als Teil des Nachnamens behandeln
- Ergebnis: Menge von Tokens + soweit erkennbar Vorname/Nachname

### Score

Der Score kombiniert mehrere Vergleiche (Bibliothek `rapidfuzz`, lokal):

1. **Reihenfolgeunabhängiger Vollnamen-Vergleich** (token_sort / token_set ratio)
2. **Vorname und Nachname getrennt**, wenn beide Seiten beide Teile haben; der Nachname wiegt stärker als der Vorname
3. **Tippfehler-Toleranz** über Jaro-Winkler bzw. Levenshtein (Meier/Meyer/Maier, Schmitt/Schmidt)
4. **Teilinformation:** Steht auf einer Seite nur ein Vorname, wird nur dieser verglichen; der Score wird gedeckelt (Standard max. 80), damit solche Treffer immer in „Prüfen“ landen
5. Optional: Spitznamen-/Kurzformliste (Alex/Alexander, Kathi/Katharina) als lokale, editierbare Datei

### Einstufung

| Score | Status | Bedeutung |
| --- | --- | --- |
| ≥ 90 | Sicher | Werte werden übernommen, grün markiert |
| 70–89 | Prüfen | Werte werden übernommen, gelb markiert, Sichtprüfung nötig |
| < 70 | Kein Treffer | keine Übernahme, Zeile rot markiert |

Die Schwellen sind Startwerte und über die Konfiguration einstellbar.

### Zuordnungsregeln

- **Eins-zu-eins:** Jede Person aus B wird höchstens einer Person aus A zugeordnet. Die Zuordnung erfolgt global nach höchstem Score (z. B. Hungarian-Algorithmus oder gieriges Best-First), nicht zeilenweise.
- **Mehrdeutigkeit:** Liegen zwei Kandidaten weniger als 5 Punkte auseinander (z. B. zweimal „Anna“), wird der Treffer als „Mehrdeutig“ gekennzeichnet und der zweitbeste Kandidat in `Match_Hinweis` genannt.
- **Doppelte Namen innerhalb einer Datei** werden erkannt und im Protokoll gemeldet.
- **Deterministisch:** Gleiche Eingabe und gleiche Einstellungen liefern immer dasselbe Ergebnis.

### Zusatzmerkmale (Klasse, Geburtsdatum, E-Mail)

Zusatzspalten bestärken einen Namenstreffer, können ihn aber nie allein erzeugen und blockieren ihn nicht.

- **Auswahl:** Welche Spalten in A und B einander entsprechen, wird wie die Namensspalten vorgeschlagen und bestätigt (Erkennung u. a. über Klasse, Geburtsdatum, E-Mail). Alles optional.
- **Klasse (unzuverlässig):** gleich → kleiner Bonus (Standard +5); abweichend → kein Abzug, nur Hinweis „Klasse abweichend: 7b / 8b“ in `Match_Hinweis`. Vergleich normalisiert („7 b“ = „7b“ = „07B“).
- **Geburtsdatum, E-Mail (zuverlässig):** exakt gleich → großer Bonus (Standard +10); abweichend → Abzug (Standard −10). Datumsformate werden vor dem Vergleich vereinheitlicht.
- **Deckel bleibt:** Ein Treffer, der nur über den Vornamen läuft, kommt auch mit Bonus nicht über „Prüfen“ hinaus.
- **Mehrdeutigkeit auflösen:** Bei zweimal „Anna“ darf die passende Klasse den Ausschlag für den Kandidaten geben; der Status bleibt aber „Prüfen“.
- Bonus- und Abzugswerte sind in der Konfiguration einstellbar.

## Ausgabe

Das Ergebnis ist eine neue .xlsx-Datei, in der jede Zeile aus A und jede Zeile aus B genau einmal vorkommt und alle Originalspalten beider Dateien erhalten sind.

### Aufbau des Blatts „Zusammengeführt“

Von links nach rechts:

1. **Match-Spalten:** `Match_Status` (Sicher / Prüfen / Mehrdeutig / Nur in A / Nur in B), `Match_Score`, `Match_Hinweis` (z. B. „nur Vorname verglichen“, „2. Kandidat: Anna Schulz (86)“, „Klasse abweichend: 7b / 8b“)
2. **Alle Spalten aus A** in Originalreihenfolge, Spaltennamen mit Präfix `A_`
3. **Alle Spalten aus B** in Originalreihenfolge, Spaltennamen mit Präfix `B_` – die Namensspalten aus B also direkt neben denen aus A sichtbar, damit der Abgleich per Auge geht

Beispiel:

| Match_Status | Match_Score | A_Name | A_Klasse | B_Vorname | B_Nachname | B_Klasse | B_Telefon |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Sicher | 100 | Max Mustermann | 7b | Max | Mustermann | 7b | 0123 456 |
| Prüfen | 84 | Jens Meier | 8a | Jens | Meyer | 8a | 0123 789 |
| Prüfen | 80 | Anna | 6c | Anna | Schulz | 6c | 0123 111 |
| Nur in A |  | Petra Lang | 9a |  |  |  |  |
| Nur in B |  |  |  | Tom | Becker | 5b | 0123 222 |

### Regeln

- **Keine Spaltenverluste:** auch leere Spalten, gleichnamige Spalten in A und B (durch Präfix getrennt) und Spalten ohne Überschrift („Spalte_7“) bleiben erhalten
- **Keine Zeilenverluste:** Zeilen aus B ohne Treffer werden unten als „Nur in B“ angehängt
- **Werte unverändert:** Zellinhalte werden 1:1 übernommen, nur die Normalisierung für den Vergleich ist intern
- **Farbmarkierung der ganzen Zeile:** grün = sicher, gelb = prüfen/mehrdeutig, rot = nur in A, grau = nur in B
- **Bedienbarkeit in Excel:** Autofilter auf der Kopfzeile, Kopfzeile fixiert, sinnvolle Spaltenbreiten
- **Sortierung:** Standard nach Originalreihenfolge von A; optional nach Status, damit alle „Prüfen“-Zeilen zusammenstehen

### Weitere Blätter

- **„Protokoll“:** Eingabedateien, gewählte Namens- und Zusatzspalten, Schwellenwerte, Anzahl Zeilen je Status, Duplikate innerhalb einer Datei, Zeitpunkt, Tool-Version
- **„Kandidaten“ (optional):** für jede Person aus A die Top-3-Kandidaten aus B mit Score, als Hilfe bei der Sichtprüfung

## Bedienung & Konfiguration

Das Tool bekommt zuerst eine Kommandozeile und in Iteration 2 eine einfache grafische Oberfläche, die ohne Programmierkenntnisse bedienbar ist.

### Kommandozeile (Iteration 1)

```
python -m namematch datei_a.xlsx datei_b.csv -o ergebnis.xlsx
    [--name-a "Name"] [--vorname-b "Vorname" --nachname-b "Nachname"]
    [--sheet-a "Tabelle1"] [--sicher 90] [--pruefen 70]
    [--config einstellungen.toml]
```

- Ohne Angabe der Namensspalten: automatische Erkennung, Ausgabe des Vorschlags, Rückfrage vor dem Lauf
- `--dry-run`: zeigt nur erkannte Spalten und Statistik, schreibt nichts

### Grafische Oberfläche (Iteration 2)

- Technik: `tkinter` (Teil der Python-Standardbibliothek, offline, keine Browser-Komponente)
- Ablauf: Datei A wählen → Datei B wählen → Namens- und Zusatzspalten per Dropdown bestätigen → Schwellen per Schieberegler → „Zusammenführen“ → Ergebnis öffnen
- Vorschau der ersten 10 Zeilen jeder Datei, damit die Spaltenwahl leicht fällt
- Klare Fehlermeldungen auf Deutsch (Datei gesperrt, weil in Excel geöffnet; Kodierung unbekannt; keine Namensspalte gefunden)

Die GUI wird von Anfang an mitgedacht: Die Kernlogik ist eine Bibliotheksfunktion ohne `print()` und `input()`, die Spaltenvorschläge als Daten zurückgibt und einen Fortschritts-Callback annimmt. Kommandozeile und GUI sind nur dünne Schichten darüber.

### Konfigurationsdatei

Eine lokale `einstellungen.toml` mit Schwellenwerten, Gewichtung Vor-/Nachname, Bonus-/Abzugswerten der Zusatzmerkmale, Titel-Liste, Spitznamen-Datei und Farbschema. Sinnvolle Standardwerte sind eingebaut, die Datei ist optional.

## Technik

Python 3.11+ mit wenigen, etablierten Bibliotheken, die alle vollständig lokal arbeiten.

| Zweck | Bibliothek | Hinweis |
| --- | --- | --- |
| Tabellen einlesen/verarbeiten | pandas | alles als `str` einlesen |
| Excel lesen/schreiben, Farben | openpyxl | .xls nur bei Bedarf über xlrd |
| Unscharfer Namensvergleich | rapidfuzz | schnell, C-Implementierung, offline |
| Kodierung erkennen | charset-normalizer | Fallback-Kette UTF-8 → cp1252 |
| Akzente entfernen | unicodedata (Standardbibliothek) | kein Zusatzpaket nötig |
| GUI | tkinter (Standardbibliothek) | Iteration 2 |
| Tests | pytest, pytest-socket | Socket-Sperre für Offline-Nachweis |
| Verteilung (optional) | PyInstaller | portables Programm ohne Python-Installation |

### Projektstruktur (Vorschlag)

```
namematch/
  io.py          # Einlesen CSV/Excel, Kodierung, Trennzeichen
  columns.py     # Erkennung der Namens- und Zusatzspalten
  normalize.py   # Namensnormalisierung
  matcher.py     # Scoring, Einstufung, 1:1-Zuordnung
  output.py      # Excel-Ausgabe, Farben, Protokollblatt
  cli.py         # Kommandozeile
  gui.py         # tkinter-Oberfläche (Iteration 2)
  config.py      # Standardwerte + TOML laden
tests/
  fixtures/      # synthetische Testdateien (keine echten Daten!)
requirements.txt # feste Versionen
CLAUDE.md        # Regeln für Claude Code (Offline, keine echten Daten)
```

- Matching-Logik strikt von Ein-/Ausgabe und Oberfläche getrennt, damit sie einzeln testbar ist
- Typ-Hinweise und kurze Docstrings, Code-Kommentare einheitlich in einer Sprache

### Plattformen

Reihenfolge: macOS und Linux zuerst, Windows danach; der Code ist von Beginn an plattformunabhängig.

- Pfade nur über `pathlib`, keine fest verdrahteten Trennzeichen
- CSV-Dateien aus Windows-Excel (Semikolon, Windows-1252) werden auch unter macOS/Linux korrekt gelesen
- Ausgabe-xlsx öffnet sich in Excel (Windows/macOS) und LibreOffice
- tkinter: unter macOS die Python-Version von python.org nutzen, weil manchen Homebrew-Installationen tkinter fehlt
- Portable Programme baut PyInstaller nur auf dem jeweiligen System (kein Cross-Build): je ein Build auf macOS, Linux, Windows
- Unsignierte macOS-Programme blockiert Gatekeeper beim ersten Start (Rechtsklick → Öffnen); für den Eigengebrauch ausreichend

## Tests & Akzeptanzkriterien

Das Tool gilt als fertig, wenn alle folgenden Punkte mit synthetischen Testdaten automatisch geprüft sind.

### Testfälle für das Matching

| Datei A | Datei B | Erwartung |
| --- | --- | --- |
| Max Mustermann | Max / Mustermann (2 Spalten) | Sicher |
| Mustermann, Max | Max Mustermann | Sicher |
| Dr. Jürgen Müller | Juergen Mueller | Sicher |
| Jens Meier | Jens Meyer | Prüfen |
| Anna | Anna Schulz | Prüfen (Score gedeckelt) |
| Anna | Anna Schulz + Anna Weber | Mehrdeutig |
| Anna (6c) | Anna Schulz (6c) + Anna Weber (7a) | Anna Schulz, Status Prüfen |
| Max Mustermann (7b) | Max Mustermann (8b) | Sicher, Hinweis „Klasse abweichend“ |
| Sabine Müller-Lang | Sabine Müller | Prüfen |
| Petra Lang | – | Nur in A |
| – | Tom Becker | Nur in B |
| Peter Schmidt | Petra Schmitt | Kein sicherer Treffer |

### Akzeptanzkriterien

- [ ] Zeilenanzahl Ergebnis = Treffer + nur in A + nur in B; keine Zeile geht verloren oder wird doppelt verwendet
- [ ] Spaltenanzahl Ergebnis = Spalten A + Spalten B + Match-Spalten
- [ ] Alle Zellwerte stimmen mit den Originalen überein (Test vergleicht zellweise)
- [ ] Führende Nullen, Datumsangaben, Umlaute bleiben unverändert
- [ ] CSV mit `;` und Windows-1252 sowie CSV mit `,` und UTF-8 werden korrekt gelesen
- [ ] Kompletter Lauf besteht mit gesperrtem Netzwerk (`pytest --disable-socket`)
- [ ] Logs enthalten keine Namen oder andere Zellinhalte
- [ ] Zwei Läufe mit gleicher Eingabe erzeugen identische Ergebnisse
- [ ] 5.000 × 5.000 Zeilen werden auf einem normalen Laptop in unter 1 Minute verarbeitet
- [ ] Originaldateien sind nach dem Lauf unverändert (Prüfsumme vorher/nachher)
- [ ] Tests laufen unter macOS und Linux
