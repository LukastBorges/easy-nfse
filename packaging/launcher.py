"""Ponto de entrada do executável (PyInstaller)."""

import multiprocessing

from easy_nfse.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
