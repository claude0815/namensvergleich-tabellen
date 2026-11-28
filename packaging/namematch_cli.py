"""Startpunkt des portablen Programms (PyInstaller): ``namematch.exe``.

Wird das Programm ohne Angaben gestartet (z. B. per Doppelklick), erscheint eine kurze
Anleitung, und das Fenster bleibt offen, bis eine Taste gedrückt wird.
"""

import sys

from namematch.cli import main

if len(sys.argv) == 1:
    print("namematch – Personenlisten offline zusammenführen\n")
    print("Bedienung mit Fenster: bitte „namematch-gui.exe“ in diesem Ordner starten.\n")
    print("Diese Datei ist die Kommandozeilen-Version.")
    print("Bitte über die Eingabeaufforderung oder PowerShell starten, zum Beispiel:\n")
    print("  .\\namematch.exe liste_a.xlsx liste_b.csv -o ergebnis.xlsx\n")
    print("Alle Optionen:  .\\namematch.exe --help")
    print("Ausführliche Anleitung: LIESMICH.txt in diesem Ordner.")
    if sys.stdin is not None and sys.stdin.isatty():
        input("\nZum Beenden Eingabetaste drücken …")
    raise SystemExit(2)

raise SystemExit(main())
