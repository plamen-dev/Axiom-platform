"""Module entrypoint for the Axiom CLI.

Enables ``python -m axiom_cli ...`` as an exact equivalent of the ``axiom``
console script (``[tool.poetry.scripts] axiom = "axiom_cli.main:cli"``). This
avoids depending on the ``axiom.exe`` console-script shim, which Windows
Application Control (WDAC / Device Guard) can block with ``WinError 4551``.
"""

from __future__ import annotations

from axiom_cli.main import cli

if __name__ == "__main__":
    cli()
