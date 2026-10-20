"""CLI entrypoint for plasma-ai-usage-collector."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from ai_usage_collector import __version__
from ai_usage_collector.collector import (
    add_account_entry,
    capture_current_account,
    collect_and_save,
    interactive_login_account,
    load_status_cache,
    remove_account,
)
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
        "--remove-account",
        nargs=2,
        metavar=("PROVIDER", "ACCOUNT_ID"),
        help="Remove uma conta cadastrada do provedor e sincroniza o status",
    )
    parser.add_argument(
        "--add-account",
        action="store_true",
        help="Adiciona uma nova conta ao provedor especificado e sincroniza o status",
    )
    parser.add_argument(
        "--capture-current",
        "--capture-active",
        dest="capture_current",
        nargs="?",
        const="",
        type=str,
        metavar="PROVIDER",
        help="Captura a autenticação ativa do sistema para o provedor selecionado e cria perfil isolado",
    )
    parser.add_argument(
        "--interactive-login",
        "--login",
        dest="interactive_login",
        nargs="?",
        const="",
        type=str,
        metavar="PROVIDER",
        help="Inicia login interativo no terminal em perfil isolado e registra a conta",
    )
    parser.add_argument(
        "--no-terminal",
        action="store_true",
        help="Executa o login diretamente sem abrir janela de emulador de terminal",
    )
    parser.add_argument(
        "--provider",
        type=str,
        help="Provedor da conta ('claude', 'codex', 'gemini')",
    )
    parser.add_argument(
        "--label",
        "--name",
        dest="label",
        type=str,
        help="Rótulo amigável legível da nova conta",
    )
    parser.add_argument(
        "--credential-path",
        "--dir",
        dest="credential_path",
        type=str,
        help="Caminho do arquivo ou diretório de credenciais da conta",
    )
    parser.add_argument(
        "--invite-url",
        type=str,
        default=None,
        help="URL opcional de convite para teste gratuito",
    )
    parser.add_argument(
        "--total-capacity",
        type=int,
        default=None,
        help="Capacidade total opcional personalizada para a conta",
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
        if args.remove_account:
            provider, account_id = args.remove_account
            success, message = remove_account(
                provider=provider,
                account_id=account_id,
                config_path=config_path,
                cache_path=cache_path,
            )
            if success:
                sys.stdout.write(f"{message}\n")
                sys.stdout.flush()
                if args.status:
                    status_data = load_status_cache(cache_path)
                    if status_data:
                        sys.stdout.write(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n")
                        sys.stdout.flush()
                return 0
            else:
                sys.stderr.write(f"Erro: {message}\n")
                sys.stderr.flush()
                return 1

        if args.add_account:
            if not args.provider:
                sys.stderr.write("Erro: Parâmetro --provider é obrigatório para --add-account.\n")
                sys.stderr.flush()
                return 1
            if not args.label:
                sys.stderr.write("Erro: Parâmetro --label / --name é obrigatório para --add-account.\n")
                sys.stderr.flush()
                return 1
            if not args.credential_path:
                sys.stderr.write("Erro: Parâmetro --credential-path / --dir é obrigatório para --add-account.\n")
                sys.stderr.flush()
                return 1

            success, message, status_data = add_account_entry(
                provider=args.provider,
                label=args.label,
                credential_path=args.credential_path,
                invite_url=args.invite_url,
                total_capacity=args.total_capacity,
                config_path=config_path,
                cache_path=cache_path,
            )
            if success:
                sys.stdout.write(f"{message}\n")
                sys.stdout.flush()
                if args.status and status_data:
                    sys.stdout.write(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                return 0
            else:
                sys.stderr.write(f"Erro: {message}\n")
                sys.stderr.flush()
                return 1

        if args.capture_current is not None:
            target_provider = args.capture_current if args.capture_current != "" else (args.provider or "")
            if not target_provider:
                sys.stderr.write("Erro: Parâmetro do provedor é obrigatório para --capture-current. Ex: --capture-current claude\n")
                sys.stderr.flush()
                return 1

            success, message, status_data = capture_current_account(
                provider=target_provider,
                label=args.label,
                invite_url=args.invite_url,
                total_capacity=args.total_capacity,
                config_path=config_path,
                cache_path=cache_path,
            )
            if success:
                sys.stdout.write(f"{message}\n")
                sys.stdout.flush()
                if args.status and status_data:
                    sys.stdout.write(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                return 0
            else:
                sys.stderr.write(f"Erro: {message}\n")
                sys.stderr.flush()
                return 1

        if args.interactive_login is not None:
            target_provider = args.interactive_login if args.interactive_login != "" else (args.provider or "")
            if not target_provider:
                sys.stderr.write("Erro: Parâmetro do provedor é obrigatório para --interactive-login. Ex: --interactive-login claude\n")
                sys.stderr.flush()
                return 1

            success, message, status_data = interactive_login_account(
                provider=target_provider,
                label=args.label,
                no_terminal=args.no_terminal,
                invite_url=args.invite_url,
                total_capacity=args.total_capacity,
                config_path=config_path,
                cache_path=cache_path,
            )
            if success:
                sys.stdout.write(f"{message}\n")
                sys.stdout.flush()
                if args.status and status_data:
                    sys.stdout.write(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                return 0
            else:
                sys.stderr.write(f"Erro: {message}\n")
                sys.stderr.flush()
                return 1

        # Default behavior: if neither refresh nor status is explicitly given, default to refresh
        should_refresh = args.refresh or (
            not args.refresh
            and not args.status
            and not args.remove_account
            and not args.add_account
            and args.capture_current is None
            and args.interactive_login is None
        )
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
