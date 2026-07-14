# Build (on Windows, inside the project's venv with pyinstaller installed):
#   pyinstaller packaging/pyinstaller/retention.spec --distpath dist --workpath build
#
# Produces dist/sylo-retention.exe -- see receiver.spec's header comment for
# the no-arg-vs-args dual-mode explanation and the win32timezone caveat;
# identical reasoning applies here.

a = Analysis(
    ["../../sylo/retention/winservice.py"],
    pathex=[],
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
