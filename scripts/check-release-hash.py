#!/usr/bin/env python3
"""Falha se o wheel não embute o SHA256 do .plasmoid dado, ou se o hash embutido diverge do zip.

Uso: check-release-hash.py <arquivo.plasmoid> <arquivo.whl>
"""
import hashlib
import re
import sys
import zipfile

MODULE = "ai_usage_collector/_plasmoid_sha256.py"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    plasmoid, wheel = argv[1], argv[2]
    with zipfile.ZipFile(wheel) as zf:
        found = MODULE in zf.namelist() and re.search(r'PLASMOID_SHA256 = "([0-9a-f]{64})"', zf.read(MODULE).decode())
    if not found:
        print(f"Hash do .plasmoid ausente no wheel ({MODULE}).", file=sys.stderr)
        return 1
    with open(plasmoid, "rb") as f:
        actual = hashlib.sha256(f.read()).hexdigest()
    if found.group(1) != actual:
        print(f"Hash do wheel diverge do .plasmoid: wheel={found.group(1)} zip={actual}", file=sys.stderr)
        return 1
    print(f"Hash consistente: {actual}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
