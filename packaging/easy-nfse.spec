# -*- mode: python ; coding: utf-8 -*-
"""Empacotamento do easy-nfse com PyInstaller.

    uv run --group desktop --group build pyinstaller packaging/easy-nfse.spec --noconfirm

Gera dist/easy-nfse.app (macOS) ou dist/easy-nfse/easy-nfse.exe (Windows).
Assinatura de código (Developer ID / Authenticode) ainda não configurada: os executáveis saem sem
assinatura, e o PyInstaller aplica só a assinatura ad hoc exigida no macOS Apple Silicon.
"""

import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

RAIZ = Path(SPECPATH).parent
VERSAO = tomllib.loads((RAIZ / "pyproject.toml").read_text())["project"]["version"]
ICONES = RAIZ / "packaging" / "icons"

datas = (
    collect_data_files("easy_nfse")  # templates, static, xsd, paises.json
    + collect_data_files("reportlab")  # fontes usadas no DANFSe
    + copy_metadata("easy-nfse")  # para importlib.metadata.version() funcionar no app
    + [(str(RAIZ / "CHANGELOG.md"), "easy_nfse")]  # notas de atualização (menu ⋮ → Notas de atualização)
)
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("reportlab.graphics.barcode")  # carregados via exec() (QR Code do DANFSe)
    + ["easy_nfse.app"]
)

a = Analysis(
    [str(RAIZ / "packaging" / "launcher.py")],
    pathex=[str(RAIZ / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "xmlsec"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="easy-nfse",
    console=False,  # app de janela, sem terminal
    icon=str(ICONES / ("easy-nfse.ico" if sys.platform == "win32" else "easy-nfse.icns")),
    codesign_identity=None,  # TODO: Developer ID Application (assinatura Apple), quando houver
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="easy-nfse")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="easy-nfse.app",
        icon=str(ICONES / "easy-nfse.icns"),
        bundle_identifier="io.github.lukastborges.easynfse",
        version=VERSAO,
        info_plist={
            "CFBundleDisplayName": "easy-nfse",
            "CFBundleShortVersionString": VERSAO,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.business",
            "NSHumanReadableCopyright": "easy-nfse",
        },
    )
