# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller : deux exécutables autonomes, un fichier chacun.

    pyinstaller --clean --noconfirm packaging/moonlight.spec

Sortie dans dist/ :
    moonlight-bitrate.exe   mesure UDP + rapport complet
    moonlight-recap.exe     tableau récapitulatif (table/markdown/csv/html/json)
"""

from PyInstaller.utils.hooks import collect_submodules

HIDDEN = collect_submodules("paramiko") + collect_submodules("cryptography")

EXCLUDES = [
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "numpy", "PIL", "matplotlib", "setuptools", "pip", "pytest",
]

# Le modèle d'exemple voyage avec l'exécutable : au premier lancement sans
# config.toml, l'utilisateur a de quoi partir.
DATAS = [("config.example.toml", ".")]


def onefile(script, name):
    analysed = Analysis(
        [script],
        pathex=["."],
        binaries=[],
        datas=DATAS,
        hiddenimports=HIDDEN,
        hookspath=[],
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
    )
    return EXE(
        PYZ(analysed.pure, analysed.zipped_data),
        analysed.scripts,
        analysed.binaries,
        analysed.datas,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


exe_bench = onefile("packaging/entry_bench.py", "moonlight-bitrate")
exe_recap = onefile("packaging/entry_recap.py", "moonlight-recap")
