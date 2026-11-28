# PyInstaller-Spezifikation für namematch: zwei Programme in einem Ordner.
#   namematch.exe      – Kommandozeile (mit Konsolenfenster)
#   namematch-gui.exe  – grafische Oberfläche (ohne Konsolenfenster)
#
# Ordner-Build (kein Einzeldatei-Build): startet schneller, entpackt beim Start nichts ins
# Temp-Verzeichnis und löst seltener Fehlalarme von Virenscannern aus.
# Bauen (auf dem Zielbetriebssystem, kein Cross-Build):
#   python -m PyInstaller --noconfirm --clean packaging/namematch.spec
from pathlib import Path

PROJEKT = Path(SPECPATH).parent  # noqa: F821 (von PyInstaller bereitgestellt)
DATEN = [(str(PROJEKT / "namematch" / "daten"), "namematch/daten")]
NICHT_NOETIG = ["pytest", "_pytest", "pytest_socket", "xlwt"]

kommandozeile = Analysis(  # noqa: F821
    [str(PROJEKT / "packaging" / "namematch_cli.py")],
    pathex=[str(PROJEKT)],
    datas=DATEN,
    excludes=NICHT_NOETIG + ["tkinter", "_tkinter"],
)
oberflaeche = Analysis(  # noqa: F821
    [str(PROJEKT / "packaging" / "namematch_gui.py")],
    pathex=[str(PROJEKT)],
    datas=DATEN,
    excludes=NICHT_NOETIG,
)

exe_kommandozeile = EXE(  # noqa: F821
    PYZ(kommandozeile.pure), kommandozeile.scripts, [],  # noqa: F821
    exclude_binaries=True, name="namematch", console=True, upx=False,
)
exe_oberflaeche = EXE(  # noqa: F821
    PYZ(oberflaeche.pure), oberflaeche.scripts, [],  # noqa: F821
    exclude_binaries=True, name="namematch-gui", console=False, upx=False,
)
coll = COLLECT(  # noqa: F821
    exe_kommandozeile, exe_oberflaeche,
    kommandozeile.binaries, oberflaeche.binaries,
    kommandozeile.datas, oberflaeche.datas,
    name="namematch", upx=False,
)
