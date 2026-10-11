"""Execução como aplicativo de desktop: servidor local + janela nativa (pywebview).

É o ponto de entrada do executável gerado pelo PyInstaller (`packaging/launcher.py`) e também
pode ser usado a partir do código-fonte: `uv run --group desktop easy-nfse-desktop`.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
# Porta fixa: se já estiver em uso, o app já está aberto (evita duas instâncias gravando os mesmos dados).
PORTA = int(os.environ.get("EASY_NFSE_PORT", "47318"))
TITULO = "easy-nfse"


def _porta_em_uso(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, porta)) == 0


def _configurar_logs() -> None:
    """No app empacotado não há terminal: os logs vão para <pasta de dados>/logs/easy-nfse.log."""
    from . import storage

    if getattr(sys, "frozen", False):
        for nome in ("stdout", "stderr"):  # no Windows, sem console, eles são None
            if getattr(sys, nome) is None:
                setattr(sys, nome, open(os.devnull, "w", encoding="utf-8"))
        pasta = storage.DATA_DIR / "logs"
        pasta.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=pasta / "easy-nfse.log", encoding="utf-8", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO)


def _abrir_janela(url: str) -> bool:
    """Abre a janela nativa. Retorna False se o pywebview não estiver disponível."""
    try:
        import webview
    except ImportError:
        return False
    webview.settings["ALLOW_DOWNLOADS"] = True  # "Baixar PDF/XML"
    webview.create_window(TITULO, url, width=1280, height=860, min_size=(420, 600))
    webview.start()  # bloqueia até a janela ser fechada
    return True


def main() -> None:
    url = f"http://{HOST}:{PORTA}"
    if _porta_em_uso(PORTA):
        logging.basicConfig(level=logging.INFO)
        logging.info("easy-nfse já está aberto em %s; mostrando a instância existente.", url)
        if os.environ.get("EASY_NFSE_NO_BROWSER"):
            return
        if not _abrir_janela(url):
            webbrowser.open(url)
        return

    _configurar_logs()
    try:
        import uvicorn

        from .app import app
    except Exception:  # sem terminal no app empacotado: registra a causa no log antes de sair
        logging.exception("Falha ao iniciar o easy-nfse")
        raise

    servidor = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORTA, log_config=None, log_level="warning"))
    thread = threading.Thread(target=servidor.run, name="servidor", daemon=True)
    thread.start()
    for _ in range(150):  # até 15 s para o servidor responder
        if servidor.started:
            break
        time.sleep(0.1)
    logging.info("easy-nfse iniciado em %s", url)

    if os.environ.get("EASY_NFSE_NO_BROWSER"):  # só o servidor (testes e verificação do build)
        thread.join()
    elif _abrir_janela(url):
        servidor.should_exit = True  # janela fechada: encerra o servidor
        thread.join(timeout=5)
    else:
        logging.warning("pywebview indisponível; abrindo no navegador.")
        webbrowser.open(url)
        thread.join()


if __name__ == "__main__":
    main()
