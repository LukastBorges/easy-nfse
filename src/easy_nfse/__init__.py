from importlib.metadata import PackageNotFoundError, version

try:  # fonte única da versão: o pyproject.toml (atualizado pelo release-please)
    __version__ = version("easy-nfse")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.2.0"


def main() -> None:
    import os
    import threading
    import webbrowser

    import uvicorn

    host = os.environ.get("EASY_NFSE_HOST", "127.0.0.1")
    port = int(os.environ.get("EASY_NFSE_PORT", "8000"))
    if not os.environ.get("EASY_NFSE_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run("easy_nfse.app:app", host=host, port=port)
