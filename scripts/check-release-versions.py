#!/usr/bin/env python3
"""Falha se tag, [project].version do pyproject e KPlugin.Version do metadata divergirem.

Uso: check-release-versions.py <tag> [raiz-do-repo]   (a tag pode ter o prefixo "v")
"""
import json
import sys
import tomllib
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(argv[2]) if len(argv) == 3 else Path(__file__).resolve().parent.parent
    tag = argv[1].removeprefix("v")
    pkg = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    meta = json.loads((root / "plasmoid" / "metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"]
    if tag == pkg == meta:
        print(f"Versões consistentes: {tag}")
        return 0
    print(f"Versões divergentes: tag={tag} pyproject={pkg} metadata={meta}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
