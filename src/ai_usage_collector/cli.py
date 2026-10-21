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
    reapply_alert_levels,
    remove_account,
    rename_account,
    switch_account,
)
from ai_usage_collector.config import (
    DEFAULT_CACHE_PATH,
    DEFAULT_CONFIG_PATH,
    SUPPORTED_PROVIDERS,
    load_config,
    set_alert_settings,
    set_provider_settings,
)
from ai_usage_collector.pace import alert_settings
from ai_usage_collector.refresh import parse_intervals
from ai_usage_collector.history import export_history
from ai_usage_collector.orphans import delete_orphan, list_orphans, reimport_orphan


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="ai-usage-collector",
        description="Coletor de métricas de uso e cotas de agentes de IA para KDE Plasma 6",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Executa a coleta (respeitando pausas do provedor) e atualiza o arquivo de status",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Exibe o payload canônico de status atual em JSON na saída padrão",
    )
    parser.add_argument(
        "--switch-account",
        "--activate-account",
        dest="switch_account",
        nargs=2,
        metavar=("PROVIDER", "ACCOUNT_ID"),
        help="Alterna e ativa a conta no sistema para o provedor especificado e sincroniza o status",
    )
    parser.add_argument(
        "--remove-account",
        nargs=2,
        metavar=("PROVIDER", "ACCOUNT_ID"),
        help="Remove uma conta cadastrada do provedor e sincroniza o status",
    )
    parser.add_argument(
        "--rename-account",
        nargs=2,
        metavar=("PROVIDER", "ACCOUNT_ID"),
        help="Renomeia uma conta cadastrada do provedor e sincroniza o status",
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
        "--export-history",
        choices=["csv", "json"],
        help="Exporta o Historico de Tokens diario (ate 400 dias) em CSV ou JSON na saida padrao",
    )
    parser.add_argument(
        "--list-orphans",
        action="store_true",
        help="Lista os Perfis Órfãos (Perfis Isolados sem Conta cadastrada) em JSON",
    )
    parser.add_argument(
        "--reimport-orphan",
        nargs=2,
        metavar=("PROVIDER", "PROFILE"),
        help="Reimporta um Perfil Órfão como Conta (funde se a identidade já existir)",
    )
    parser.add_argument(
        "--delete-orphan",
        nargs=2,
        metavar=("PROVIDER", "PROFILE"),
        help="Exclui um Perfil Órfão do disco; exige --confirm",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirma explicitamente a exclusão de um Perfil Órfão",
    )
    parser.add_argument(
        "--set-provider-config",
        metavar="PROVIDER",
        help="Define caminho de credenciais (--credential-path) e, no Claude, --api-base-url/--api-key-stdin/--clear-api-key; valor vazio remove. A configuração explícita vence as variáveis de ambiente",
    )
    parser.add_argument(
        "--set-alert-config",
        action="store_true",
        help="Define o modo de alerta (--alert-mode pace|threshold) e os limiares (--alert-warning, --alert-critical; 0 < aviso < crítico <= 100)",
    )
    parser.add_argument("--alert-mode", choices=["pace", "threshold"], default=None, help="Alerta por ritmo (padrão) ou limiar fixo")
    parser.add_argument("--alert-warning", type=float, default=None, help="Limiar de aviso em %% (padrão 70)")
    parser.add_argument("--alert-critical", type=float, default=None, help="Limiar crítico em %% (padrão 90)")
    parser.add_argument("--api-base-url", type=str, default=None, help="URL base do gateway de uso (Claude)")
    parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Le a chave de API da entrada padrao (nunca por argumento); vazia remove",
    )
    parser.add_argument("--clear-api-key", action="store_true", help="Remove a chave de API personalizada")
    parser.add_argument(
        "--provider",
        type=str,
        help="Provedor da conta ('claude', 'codex', 'gemini'); com --refresh, lista separada por vírgula dos provedores a atualizar",
    )
    parser.add_argument(
        "--refresh-interval",
        action="append",
        metavar="PROVIDER=SECONDS",
        help="Intervalo de Atualização do provedor em segundos (mínimo 60, padrão 300); pode repetir",
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
        if args.export_history:
            sys.stdout.write(export_history(cache_path, args.export_history, load_config(config_path)))
            sys.stdout.flush()
            return 0

        if args.list_orphans:
            sys.stdout.write(json.dumps(list_orphans(config_path), indent=2, ensure_ascii=False) + "\n")
            return 0

        if args.set_provider_config:
            key = sys.stdin.read().strip() if args.api_key_stdin else None
            ok, message = set_provider_settings(
                args.set_provider_config, args.credential_path, args.api_base_url, key, config_path,
                clear_api_key=args.clear_api_key,
            )
            if ok:
                collect_and_save(config_path=config_path, cache_path=cache_path)
            (sys.stdout if ok else sys.stderr).write((message if ok else f"Erro: {message}") + "\n")
            return 0 if ok else 1

        if args.set_alert_config:
            before = alert_settings(load_config(config_path))
            ok, message = set_alert_settings(args.alert_mode, args.alert_warning, args.alert_critical, config_path)
            if ok and alert_settings(load_config(config_path)) != before:
                reapply_alert_levels(config_path, cache_path)  # so recalcula niveis; sem consulta aos provedores
            (sys.stdout if ok else sys.stderr).write((message if ok else f"Erro: {message}") + "\n")
            return 0 if ok else 1

        for pair, action in ((args.reimport_orphan, reimport_orphan), (args.delete_orphan, delete_orphan)):
            if pair:
                if action is delete_orphan:
                    ok, message = action(*pair, confirm=args.confirm, config_path=config_path)
                else:
                    ok, message = action(*pair, config_path=config_path)
                if ok:
                    collect_and_save(config_path=config_path, cache_path=cache_path)
                (sys.stdout if ok else sys.stderr).write((message if ok else f"Erro: {message}") + "\n")
                return 0 if ok else 1

        if args.switch_account:
            provider, account_id = args.switch_account
            success, message, status_data = switch_account(
                provider=provider,
                account_id=account_id,
                config_path=config_path,
                cache_path=cache_path,
            )
            if success:
                sys.stdout.write(f"{message}\n")
                sys.stdout.flush()
                if args.status:
                    out_status = status_data or load_status_cache(cache_path)
                    if out_status:
                        sys.stdout.write(json.dumps(out_status, indent=2, ensure_ascii=False) + "\n")
                        sys.stdout.flush()
                return 0
            else:
                sys.stderr.write(f"Erro: {message}\n")
                sys.stderr.flush()
                return 1

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

        if args.rename_account:
            provider, account_id = args.rename_account
            if not args.label:
                sys.stderr.write("Erro: Parâmetro --label / --name é obrigatório para --rename-account.\n")
                sys.stderr.flush()
                return 1

            clean_label = args.label.strip()
            if not clean_label:
                sys.stderr.write("Erro: Rótulo/nome da conta não pode ser vazio.\n")
                sys.stderr.flush()
                return 1

            success, message, status_data = rename_account(
                provider=provider,
                account_id=account_id,
                new_label=clean_label,
                config_path=config_path,
                cache_path=cache_path,
            )
            if success:
                sys.stdout.write(f"{message}\n")
                sys.stdout.flush()
                if args.status:
                    out_status = status_data or load_status_cache(cache_path)
                    if out_status:
                        sys.stdout.write(json.dumps(out_status, indent=2, ensure_ascii=False) + "\n")
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
            and not args.list_orphans
            and not args.set_provider_config
            and not args.set_alert_config
            and not args.switch_account
            and not args.remove_account
            and not args.rename_account
            and not args.add_account
            and args.capture_current is None
            and args.interactive_login is None
        )
        should_output_status = args.status

        status_data = None

        if should_refresh:
            providers = [p.strip().lower() for p in (args.provider or "").split(",") if p.strip()]
            invalid = [p for p in providers if p not in SUPPORTED_PROVIDERS]
            if invalid:
                sys.stderr.write(f"Erro: Provedor inválido: {', '.join(invalid)}\n")
                return 2
            try:
                intervals = parse_intervals(args.refresh_interval)
            except ValueError as e:
                sys.stderr.write(f"Erro: {e}\n")
                return 2
            status_data = collect_and_save(
                config_path=config_path,
                cache_path=cache_path,
                providers=providers or None,
                intervals=intervals,
            )

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
