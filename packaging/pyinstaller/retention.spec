# Build (on Windows, inside the project's venv with pyinstaller installed):
#   pyinstaller packaging/pyinstaller/retention.spec --distpath dist --workpath build
#
# Produces dist/sylo-retention.exe -- see receiver.spec's header comment for
# the no-arg-vs-args dual-mode explanation, the win32timezone caveat, and
# why source paths are built from SPECPATH rather than left relative.
# entry_retention.py is the Analysis script rather than winservice.py
# directly for the same reason as entry_receiver.py (see its docstring):
# relative imports need a real parent package, which the frozen entry
# script itself doesn't have.

import os

_root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

a = Analysis(
    [os.path.join(SPECPATH, "entry_retention.py")],
    pathex=[_root],
    binaries=[],
    datas=[],
    hiddenimports=["win32timezone"],
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="sylo-retention",
    console=True,
)
