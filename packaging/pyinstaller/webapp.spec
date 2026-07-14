# Build (on Windows, inside the project's venv with pyinstaller installed):
#   pyinstaller packaging/pyinstaller/webapp.spec --distpath dist --workpath build
#
# Produces dist/sylo-webapp.exe -- see receiver.spec's header comment for the
# no-arg-vs-args dual-mode explanation and the win32timezone caveat;
# identical reasoning applies here.
#
# templates/ and static/ are bundled as datas at the same relative path
# (sylo/webapp/templates, sylo/webapp/static) that app.py's
# `Path(__file__).parent / "templates"` / `.../"static"` resolve to at
# runtime -- PyInstaller's onefile extraction preserves __file__'s location
# relative to the bundle root, so no code changes were needed in app.py to
# find them when frozen.

a = Analysis(
    ["../../sylo/webapp/winservice.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("../../sylo/webapp/templates", "sylo/webapp/templates"),
        ("../../sylo/webapp/static", "sylo/webapp/static"),
    ],
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
    name="sylo-webapp",
    console=True,
)
