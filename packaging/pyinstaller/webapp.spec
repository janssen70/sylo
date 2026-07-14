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
#
# Source paths are built from SPECPATH (this spec file's own absolute
# directory, injected by PyInstaller) rather than left relative, so the
# build works regardless of the caller's current directory.
# entry_webapp.py is the Analysis script rather than winservice.py directly
# for the same reason as entry_receiver.py (see its docstring): relative
# imports need a real parent package, which the frozen entry script itself
# doesn't have.

import os

_root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

a = Analysis(
    [os.path.join(SPECPATH, "entry_webapp.py")],
    pathex=[_root],
    binaries=[],
    datas=[
        (os.path.join(_root, "sylo", "webapp", "templates"), os.path.join("sylo", "webapp", "templates")),
        (os.path.join(_root, "sylo", "webapp", "static"), os.path.join("sylo", "webapp", "static")),
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
