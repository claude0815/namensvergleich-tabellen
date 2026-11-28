# PyInstaller-Spezifikation für namematch.
#
# Ordner-Build (kein Einzeldatei-Build): startet schneller, entpackt beim Start nichts ins
# Temp-Verzeichnis und löst seltener Fehlalarme von Virenscannern aus.
# Bauen (auf dem Zielbetriebssystem, kein Cross-Build):
#   python -m PyInstaller --noconfirm --clean packaging/namematch.spec
from pathlib import Path

PROJEKT = Path(SPECPATH).parent  # noqa: F821 (von PyInstaller bereitgestellt)

a = Analysis(  # noqa: F821
    [str(PROJEKT / "packaging" / "namematch_cli.py")],
    pathex=[str(PROJEKT)],
    datas=[(str(PROJEKT / "namematch" / "daten"), "namematch/daten")],
    excludes=["tkinter", "_tkinter", "pytest", "_pytest", "pytest_socket", "xlwt"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="namematch", console=True, upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="namematch", upx=False)  # noqa: F821
