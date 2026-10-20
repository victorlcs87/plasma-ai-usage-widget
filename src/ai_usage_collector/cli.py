"""CLI entrypoint for plasma-ai-usage-collector."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from ai_usage_collector import __version__
from ai_usage_collector.collector import collect_and_save, load_status_cache
from ai_usage_collector.config import DEFAULT_CACHE_PATH, DEFAULT_CONFIG_PATH


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="ai-usage-collector",
        description="Coletor sob demanda de métricas de uso e cotas de agentes de IA para KDE Plasma 6",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Executa a coleta sob demanda e atualiza o arquivo de status",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Exibe o payload canônico de status atual em JSON na saída padrão",
    )
    parser.add_argument(
        "--config-path",
        type=str,
        default=str(DEFAULT_CONFIG_PATH),
        help="Caminho alternativo para o arquivo config.json (padrão: ~/.config/plasma-ai-usage/config.json)",
    )
    parser.add_argument(
        "--cache-path",
        type=str,
        default=str(DEFAULT_CACHE_PATH),
        help="Caminho alternativo para o arquivo status.json (padrão: ~/.cache/plasma-ai-usage/status.json)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = args.config_path
    cache_path = args.cache_path

    try:
        # Default behavior: if neither refresh nor status is explicitly given, default to refresh
        should_refresh = args.refresh or (not args.refresh and not args.status)
        should_output_status = args.status

        status_data = None

        if should_refresh:
            status_data = collect_and_save(config_path=config_path, cache_path=cache_path)

        if should_output_status:
            if status_data is None:
                status_data = load_status_cache(cache_path)
                if status_data is None:
                    # If cache not present, perform collection
                    status_data = collect_and_save(config_path=config_path, cache_path=cache_path)

            sys.stdout.write(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n")
            sys.stdout.flush()

        return 0
    except Exception as e:
        sys.stderr.write(f"Erro no coletor de uso de IA: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
