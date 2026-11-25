"""Erzeugt synthetische Testdateien für namematch (KEINE echten Personendaten!).

Alle Namen sind erfunden bzw. aus Listen häufiger Vor- und Nachnamen zufällig kombiniert.
Die Dateien bilden typische Probleme realer Listen nach: verschiedene Namensformate,
Titel, Umlaute/Umschrift, Tippfehler, nur Vorname, Doppelnamen, Klassen-Schreibweisen,
führende Nullen, Datumsangaben, leere Zeilen und Spalten, Spalten ohne Überschrift,
CSV mit ; / , / Tab in Windows-1252 / UTF-8 / UTF-8 mit BOM, Excel .xlsx und .xls.

Aufruf (aus dem Projektordner):  python -m tests.fixtures.erzeuge_fixtures
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import random
from pathlib import Path

ORDNER = Path(__file__).parent

# --------------------------------------------------------------------------------
# Datei A: Hauptliste (eine Namensspalte „Name“, verschiedene Formate)
# --------------------------------------------------------------------------------
SPALTEN_A = ["Nr", "Name", "Klasse", "Geburtsdatum", "PLZ", None, "Bemerkung", "Telefon"]

# (Nr, Name, Klasse, Geburtsdatum, PLZ, Notiz (Spalte ohne Überschrift), Telefon)
ZEILEN_A: list[tuple] = [
    ("001", "Max Mustermann", "7b", dt.datetime(2012, 3, 14), "01067", None, "0123 456"),
    ("002", "Schneider, Lisa", "7b", dt.datetime(2012, 7, 1), "04109", None, "0123 457"),
    ("003", "Dr. Jürgen Müller", "8a", None, "80331", None, None),
    ("004", "Jens Meier", "8a", dt.datetime(2011, 2, 2), "01069", None, "0123 789"),
    ("005", "Anna", "6c", None, "01067", "nur Vorname bekannt", None),
    ("006", "Tim Kowalski", "7b", None, "09111", None, None),
    ("007", "Sabine Müller-Lang", "9a", None, "01307", None, None),
    ("008", "Petra Lang", "9a", None, "01309", None, "0123 999"),
    ("009", "Peter Schmidt", "10c", None, "01326", None, None),
    ("010", "Özlem Yılmaz", "7a", dt.datetime(2012, 11, 30), "01097", None, None),
    None,  # komplett leere Zeile
    ("011", "José García", "8b", None, "01099", "=1+1", None),
    ("012", "Ludwig van Beethoven", "10a", None, "53111", None, None),
    ("013", "Hans-Peter Groß", "6a", None, "01157", None, None),
    ("014", "Leonie", "5a", None, "01159", None, None),
    ("015", "Paul Wagner", "5a", None, "01169", None, None),
    ("016", "Paul Wagner", "6b", None, "01169", None, None),
    ("017", None, "9c", None, "01187", "Name fehlt", None),
    ("018", "Mustermann Erika", "7b", None, "01067", None, None),
    ("019", "Kathi Neumann", "6a", None, "01189", None, None),
    ("020", "Lukas Hoffmann", "8b", dt.datetime(2011, 9, 9), "01217", None, None),
]

# --------------------------------------------------------------------------------
# Datei B: zwei Namensspalten (Nachname vor Vorname!), Klasse oft anders geschrieben
# --------------------------------------------------------------------------------
SPALTEN_B = ["Schüler-ID", "Nachname", "Vorname", "Klasse", "Geburtsdatum", "Telefon", "E-Mail", "", "PLZ"]

# (ID, Nachname, Vorname, Klasse, Geburtsdatum (Text), Telefon, E-Mail, Notiz, PLZ)
ZEILEN_B: list[tuple] = [
    ("B-001", "Mustermann", "Max", "7b", "14.03.2012", "0123 456", "max.m@example.org", "", "01067"),
    ("B-002", "Schneider", "Lisa", "7 b", "01.07.2012", "", "", "", "04109"),
    ("B-003", "Mueller", "Juergen", "8A", "", "", "", "", "80331"),
    ("B-004", "Meyer", "Jens", "8a", "", "0123 789", "", "", "01069"),
    ("B-005", "Weber", "Anna", "7a", "", "", "", "", "01067"),
    ("B-006", "Schulz", "Anna", "06c", "", "0123 111", "", "", "01067"),
    ("B-007", "Kowalski", "Tim", "8b", "", "", "", "", "09111"),
    ("B-008", "Müller", "Sabine", "9a", "", "", "", "", "01307"),
    ("B-009", "Becker", "Tom", "5b", "", "0123 222", "", "", "01309"),
    ("B-010", "Schmitt", "Petra", "10c", "", "", "", "", "01326"),
    None,  # komplett leere Zeile
    ("B-011", "Yilmaz", "Oezlem", "7a", "30.11.2012", "", "", "", "01097"),
    ("B-012", "Garcia", "Jose", "8b", "", "", "", "=SUMME(A1:A3)", "01099"),
    ("B-013", "van Beethoven", "Ludwig", "10a", "", "", "", "", "53111"),
    ("B-014", "Gross", "Hans-Peter", "6a", "", "", "", "", "01157"),
    ("B-015", "Hartmann", "Leonie", "5a", "", "", "", "", "01159"),
    ("B-016", "Wagner", "Paul", "6b", "", "", "", "", "01169"),
    ("B-017", "Mustermann", "Erika", "7b", "", "", "", "", "01067"),
    ("B-018", "Neumann", "Katharina", "6a", "", "", "", "", "01189"),
    ("B-019", "Hoffmann", "Lucas", "8b", "09.09.2011", "", "", "", "01217"),
]

# Erwartetes Ergebnis je A-Nr: (Status, B-ID oder None). „nicht Sicher“ = alles außer Sicher.
ERWARTUNG: dict[str, tuple[str, str | None]] = {
    "001": ("Sicher", "B-001"),
    "002": ("Sicher", "B-002"),
    "003": ("Sicher", "B-003"),
    "004": ("Prüfen", "B-004"),
    "005": ("Prüfen", "B-006"),
    "006": ("Sicher", "B-007"),
    "007": ("Prüfen", "B-008"),
    "008": ("Nur in A", None),
    "009": ("nicht Sicher", None),
    "010": ("Sicher", "B-011"),
    "011": ("Sicher", "B-012"),
    "012": ("Sicher", "B-013"),
    "013": ("Sicher", "B-014"),
    "014": ("Prüfen", "B-015"),
    "015": ("Nur in A", None),
    "016": ("Mehrdeutig", "B-016"),
    "017": ("Nur in A", None),
    "018": ("Sicher", "B-017"),
    "019": ("Prüfen", "B-018"),
    "020": ("Sicher", "B-019"),
}
NUR_IN_B_ERWARTET = {"B-009", "B-005"}

# Häufige Vor- und Nachnamen für zusätzliche, zufällig kombinierte Personen
VORNAMEN = [
    "Mia", "Emilia", "Hannah", "Emma", "Sofia", "Lina", "Ella", "Mila", "Clara", "Lea", "Marie", "Luisa",
    "Noah", "Leon", "Paul", "Ben", "Finn", "Elias", "Felix", "Henry", "Jonas", "Luis", "Emil", "Theo",
    "Matteo", "Anton", "Karl", "Oskar", "Ida", "Frieda", "Greta", "Mathilda", "Jakob", "Moritz", "Ole",
    "Nele", "Johanna", "Charlotte", "Maximilian", "Alexander", "Sophie", "Amelie", "Leni", "Lotta",
]
NACHNAMEN = [
    "Fischer", "Wagner", "Becker", "Schulz", "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Schröder",
    "Neumann", "Schwarz", "Braun", "Zimmermann", "Krüger", "Hofmann", "Hartmann", "Lange", "Werner",
    "Krause", "Lehmann", "Köhler", "Herrmann", "König", "Walter", "Huber", "Kaiser", "Fuchs", "Peters",
    "Scholz", "Möller", "Weiß", "Jung", "Hahn", "Schubert", "Vogel", "Friedrich", "Keller", "Günther",
    "Frank", "Berger", "Winkler", "Roth", "Beck", "Lorenz", "Baumann", "Franke", "Albrecht", "Schuster",
    "Simon", "Ludwig", "Böhm", "Winter", "Kraus", "Martin", "Schumacher", "Krämer", "Vogt", "Stein",
    "Jäger", "Otto", "Sommer", "Groß", "Seidel", "Heinrich", "Brandt", "Haas", "Schreiber", "Graf",
]
KLASSEN = ["5a", "5b", "6a", "6b", "7a", "7b", "8a", "8b", "9a", "9b", "10a", "10b"]


def _zusatzpersonen(seed: int = 4711, anzahl: int = 24) -> list[tuple[str, str, str]]:
    """Zufällige, eindeutige (Vorname, Nachname, Klasse), ohne Überschneidung mit den Sonderfällen."""
    belegt = {"paul wagner", "anna schulz", "anna weber", "tom becker", "leonie hartmann", "lukas hoffmann",
              "katharina neumann", "erika mustermann", "max mustermann"}
    zufall = random.Random(seed)
    personen: list[tuple[str, str, str]] = []
    while len(personen) < anzahl:
        vor, nach = zufall.choice(VORNAMEN), zufall.choice(NACHNAMEN)
        schluessel = f"{vor} {nach}".lower()
        if schluessel in belegt:
            continue
        belegt.add(schluessel)
        personen.append((vor, nach, zufall.choice(KLASSEN)))
    return personen


def daten() -> tuple[list[list], list[list]]:
    """Liefert die Zeilen für A und B (inkl. Zusatzpersonen); None = leere Zeile."""
    zeilen_a: list = [None if z is None else [z[0], z[1], z[2], z[3], z[4], z[5], None, z[6]] for z in ZEILEN_A]
    zeilen_b: list = [None if z is None else list(z) for z in ZEILEN_B]
    zusatz = _zusatzpersonen()
    for k, (vor, nach, klasse) in enumerate(zusatz):
        nr = f"{21 + k:03d}"
        zeilen_a.append([nr, f"{vor} {nach}", klasse, None, f"0{1000 + k}", None, None, None])
        if k % 4 != 3:  # drei Viertel stehen auch in B
            zeilen_b.append([f"B-{20 + k:03d}", nach, vor, klasse, "", "", "", "", f"0{1000 + k}"])
            ERWARTUNG[nr] = ("Sicher", f"B-{20 + k:03d}")
        else:
            ERWARTUNG[nr] = ("Nur in A", None)
    return zeilen_a, zeilen_b


# --------------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------------

def _csv_text(kopf: list, zeilen: list, trennzeichen: str, zeilenende: str = "\n") -> str:
    puffer = io.StringIO(newline="")
    schreiber = csv.writer(puffer, delimiter=trennzeichen, lineterminator=zeilenende)
    schreiber.writerow(["" if k is None else k for k in kopf])
    for zeile in zeilen:
        schreiber.writerow([] if zeile is None else ["" if w is None else w for w in zeile])
    return puffer.getvalue()


def _xlsx_schreiben(pfad: Path, blaetter: list[tuple[str, list, list]], datumsformat: str = "DD.MM.YYYY") -> None:
    import openpyxl

    mappe = openpyxl.Workbook()
    mappe.remove(mappe.active)
    for titel, kopf, zeilen in blaetter:
        blatt = mappe.create_sheet(titel)
        blatt.append(kopf)
        for zeile in zeilen:
            if zeile is None:
                blatt.append([])
                continue
            blatt.append(zeile)
            for zelle in blatt[blatt.max_row]:
                if isinstance(zelle.value, dt.datetime):
                    zelle.number_format = datumsformat
                elif isinstance(zelle.value, str) and zelle.value.startswith("="):
                    zelle.data_type = "s"  # Text, keine Formel
    mappe.properties.creator = "namematch-Testdaten"
    mappe.properties.created = dt.datetime(2025, 1, 1)
    mappe.properties.modified = dt.datetime(2025, 1, 1)
    mappe.save(pfad)


def _xls_schreiben(pfad: Path, kopf: list, zeilen: list) -> None:
    import xlwt

    mappe = xlwt.Workbook(encoding="utf-8")
    blatt = mappe.add_sheet("Tabelle1")
    for spalte, wert in enumerate(kopf):
        blatt.write(0, spalte, wert)
    for nummer, zeile in enumerate(zeilen, start=1):
        if zeile is None:
            continue
        for spalte, wert in enumerate(zeile):
            if wert not in (None, ""):
                blatt.write(nummer, spalte, wert)
    mappe.save(str(pfad))


def alle_schreiben(ordner: Path = ORDNER) -> list[Path]:
    """Schreibt alle Testdateien und gibt ihre Pfade zurück."""
    zeilen_a, zeilen_b = daten()
    kopf_a = ["" if k is None else k for k in SPALTEN_A]
    pfade: list[Path] = []

    # A als Excel mit zwei Blättern (erstes Blatt ist die Liste)
    info = [["Synthetische Testdaten – keine echten Personen"], ["Erzeugt von erzeuge_fixtures.py"]]
    _xlsx_schreiben(ordner / "schueler_a.xlsx", [("Klassenliste", kopf_a, zeilen_a), ("Info", ["Hinweis"], info)])
    pfade.append(ordner / "schueler_a.xlsx")

    # B in mehreren Formaten mit gleichem Inhalt
    varianten = [
        ("schueler_b_semikolon_cp1252.csv", ";", "cp1252", "\r\n"),
        ("schueler_b_komma_utf8.csv", ",", "utf-8", "\n"),
        ("schueler_b_tab_utf8bom.csv", "\t", "utf-8-sig", "\r\n"),
        ("schueler_b_semikolon_macroman.csv", ";", "mac_roman", "\r"),  # Excel für Mac, Format „CSV“
    ]
    for name, trennzeichen, kodierung, ende in varianten:
        (ordner / name).write_bytes(_csv_text(SPALTEN_B, zeilen_b, trennzeichen, ende).encode(kodierung))
        pfade.append(ordner / name)
    _xlsx_schreiben(ordner / "schueler_b.xlsx", [("Tabelle1", SPALTEN_B, zeilen_b)])
    pfade.append(ordner / "schueler_b.xlsx")
    _xls_schreiben(ordner / "schueler_b.xls", SPALTEN_B, zeilen_b)
    pfade.append(ordner / "schueler_b.xls")

    # Titelzeilen oberhalb der Kopfzeile (Kopfzeile in Zeile 4)
    titel = "Klassenliste Schuljahr 2025/26;;\nStand: 01.09.2025;;\n;;\n"
    rumpf = _csv_text(["Vorname", "Nachname", "Klasse"],
                      [["Max", "Mustermann", "7b"], ["Lisa", "Schneider", "7b"], ["Tom", "Becker", "5b"]], ";")
    (ordner / "mit_titelzeilen.csv").write_bytes((titel + rumpf).encode("utf-8"))
    pfade.append(ordner / "mit_titelzeilen.csv")

    # Nur Vornamen
    (ordner / "nur_vornamen.csv").write_bytes(_csv_text(
        ["Vorname", "Klasse"], [["Anna", "6c"], ["Leonie", "5a"], ["Max", "7b"]], ";").encode("utf-8"))
    pfade.append(ordner / "nur_vornamen.csv")

    # Gemischte Namensformate in einer Spalte
    (ordner / "gemischt_teilnehmer.csv").write_bytes(_csv_text(
        ["Teilnehmer", "Kurs"],
        [["Anna", "Chor"], ["Max Mustermann", "Theater"], ["Schneider, Lisa", "Chor"], ["Herr Dr. Jürgen Müller", "AG"]],
        ",").encode("utf-8"))
    pfade.append(ordner / "gemischt_teilnehmer.csv")
    pfade += webuntis_schreiben(ordner)
    return pfade


# --------------------------------------------------------------------------------
# WebUntis-ähnlicher Export: „name“ = Kurzname (NICHT der Nachname!), „longName“ = Nachname,
# „foreName“ = Vorname. Gegenliste mit „SchülerIn“ im Format „Nachname, Vorname“.
# --------------------------------------------------------------------------------
WEBUNTIS_SONDERFAELLE = [
    ("Max", "Mustermann", "7b"), ("Anna-Lena", "Schulz", "6c"), ("Jürgen", "Müller", "8a"),
    ("Sabine", "Müller-Lang", "9a"), ("Özlem", "Yılmaz", "7a"), ("Ludwig", "van Beethoven", "10a"),
    ("Emil", "Bülüköz", "7a"), ("Jürgen", "Größmüller", "9b"), ("Ömer", "Çağlayan", "8b"),
]
#: steht in B als „Vorname, Nachname“ (vertauscht) – erwartet: Prüfen mit Hinweis
WEBUNTIS_VERTAUSCHT = ("Mila", "Kühnöl", "6a")


def _kurzname(vorname: str, nachname: str) -> str:
    """Erfundener Kurzname im Stil „MustMax“ (vier Buchstaben Nachname + drei Buchstaben Vorname)."""
    nach = nachname.replace(" ", "").replace("-", "")
    return nach[:4].capitalize() + vorname.replace("-", "")[:3].capitalize()


def webuntis_daten() -> tuple[list[list], list[list], int]:
    """Zeilen für A (WebUntis-ähnlich) und B („Nachname, Vorname“) sowie die Anzahl gemeinsamer Personen."""
    personen = WEBUNTIS_SONDERFAELLE + _zusatzpersonen(seed=815, anzahl=24)
    a_zeilen, b_zeilen = [], []
    gemeinsam = 0
    for k, (vor, nach, klasse) in enumerate(personen):
        geburt = f"{2010 + k % 4}-{1 + k % 12:02d}-{1 + k % 27:02d}"
        a_zeilen.append([_kurzname(vor, nach), nach, vor, "m" if k % 2 else "w", geburt, klasse])
        if k % 5 != 4:
            b_zeilen.append([f"{nach}, {vor}", klasse])
            gemeinsam += 1
    vor, nach, klasse = WEBUNTIS_VERTAUSCHT
    a_zeilen.append([_kurzname(vor, nach), nach, vor, "w", "2012-12-12", klasse])
    b_zeilen.append([f"{vor}, {nach}", klasse])
    b_zeilen.append(["Becker, Tom", "5b"])
    return a_zeilen, b_zeilen, gemeinsam


def webuntis_schreiben(ordner: Path = ORDNER) -> list[Path]:
    """Schreibt webuntis_a.csv, webuntis_a_mac.csv und schuelerliste_b.xlsx.

    webuntis_a_mac.csv bildet nach, was passiert, wenn man die Spalte „name“ löscht und die Datei
    in Excel für Mac im Format „CSV“ speichert: Mac-Roman-Kodierung, nicht darstellbare Zeichen („ı“,
    „ğ“) werden zu „?“.
    """
    a_zeilen, b_zeilen, _ = webuntis_daten()
    kopf_a = ["name", "longName", "foreName", "gender", "birthDate", "klasse.name"]
    (ordner / "webuntis_a.csv").write_bytes(_csv_text(kopf_a, a_zeilen, ";", "\r\n").encode("utf-8-sig"))
    mac = _csv_text(kopf_a[1:], [z[1:] for z in a_zeilen], ";", "\r").encode("mac_roman", errors="replace")
    (ordner / "webuntis_a_mac.csv").write_bytes(mac)
    _xlsx_schreiben(ordner / "schuelerliste_b.xlsx", [("Schüler", ["SchülerIn", "Klasse"], b_zeilen)])
    return [ordner / "webuntis_a.csv", ordner / "webuntis_a_mac.csv", ordner / "schuelerliste_b.xlsx"]


def grosse_listen(ordner: Path, anzahl: int = 5000, seed: int = 2025) -> tuple[Path, Path]:
    """Erzeugt zwei große CSV-Listen (A: ein Namensfeld, B: Vor-/Nachname) für Lasttests."""
    zufall = random.Random(seed)
    vornamen = VORNAMEN + ["Lukas", "Laura", "Tim", "Jan", "David", "Erik", "Maja", "Clara", "Jana", "Nina",
                           "Tobias", "Fabian", "Julian", "Lars", "Sven", "Katrin", "Sandra", "Melanie", "Tanja"]
    nachnamen = NACHNAMEN + ["Müller", "Schmidt", "Schneider", "Meyer", "Weber", "Meier", "Mayer", "Schmitt",
                             "Lang", "Kühn", "Pohl", "Engel", "Horn", "Busch", "Bergmann", "Thomas", "Voigt"]
    a_zeilen, b_zeilen = [], []
    for k in range(anzahl):
        vor, nach = zufall.choice(vornamen), zufall.choice(nachnamen)
        klasse = zufall.choice(KLASSEN)
        form = zufall.random()
        name = f"{nach}, {vor}" if form < 0.3 else f"{vor} {nach}"
        a_zeilen.append([f"{k + 1:05d}", name, klasse, f"0{zufall.randint(1000, 9999)}"])
        if zufall.random() < 0.75:
            if zufall.random() < 0.1:  # Tippfehler
                nach = nach[:-1] + zufall.choice("aeiouyx")
            b_zeilen.append([vor, nach, klasse, f"0151 {zufall.randint(100000, 999999)}"])
    while len(b_zeilen) < anzahl:
        b_zeilen.append([zufall.choice(vornamen), zufall.choice(nachnamen), zufall.choice(KLASSEN),
                         f"0151 {zufall.randint(100000, 999999)}"])
    zufall.shuffle(b_zeilen)
    pfad_a, pfad_b = ordner / "gross_a.csv", ordner / "gross_b.csv"
    pfad_a.write_bytes(_csv_text(["Nr", "Name", "Klasse", "PLZ"], a_zeilen, ";", "\r\n").encode("cp1252"))
    pfad_b.write_bytes(_csv_text(["Vorname", "Nachname", "Klasse", "Telefon"], b_zeilen, ",").encode("utf-8"))
    return pfad_a, pfad_b


if __name__ == "__main__":
    for pfad in alle_schreiben():
        print(pfad.relative_to(ORDNER.parent.parent))
