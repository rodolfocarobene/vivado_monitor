# PyInstaller spec: one-file vmon executable. Run from the repository root:
#   pyinstaller tools/vmon.spec --distpath dist-bin --workpath build-bin
# VMON_BINARY_NAME sets the output file name (default: vmon).
import os
from pathlib import Path

root = Path(SPECPATH).parent
name = os.environ.get("VMON_BINARY_NAME", "vmon")

# Destinations mirror the package layout: the code finds these through Path(__file__).parent,
# which inside a one-file bundle is <_MEIPASS>/vmon.
datas = [
    (str(root / "vmon" / "static"), "vmon/static"),      # includes static/mock
    (str(root / "vmon" / "catalog"), "vmon/catalog"),
    (str(root / "vmon" / "flows.toml"), "vmon"),
]

a = Analysis([str(root / "tools" / "vmon_entry.py")], pathex=[str(root)], datas=datas,
             excludes=["tkinter", "unittest", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=name, console=True, upx=False)
