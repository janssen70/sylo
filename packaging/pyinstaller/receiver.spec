# Build (on Windows, inside the project's venv with pyinstaller installed):
#   pyinstaller packaging/pyinstaller/receiver.spec --distpath dist --workpath build
#
# Produces dist/sylo-receiver.exe -- a single-file, no-arg-vs-args dual-mode
# binary (see sylo/receiver/winservice.py's main()): run with no arguments,
# the Service Control Manager starts it as the SyloReceiver service; run
# with install/start/stop/remove, pywin32's HandleCommandLine manages the
# service registration directly against this exe (no separate python.exe
# hop needed since sys.frozen makes win32serviceutil point the SCM at the
# exe itself).
#
# win32timezone is not auto-detected by PyInstaller's pywin32 hook in some
# pywin32/PyInstaller version combinations and is commonly needed at
# runtime by win32serviceutil-based services -- listed explicitly as a
# known, recurring gotcha. This spec is authored but not build-verified
# (no Windows machine in this dev environment); resolve any further
# ModuleNotFoundError from a first build attempt by adding the missing
# module to hiddenimports below.

a = Analysis(
    ["../../sylo/receiver/winservice.py"],
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
    name="sylo-receiver",
    console=True,
)
