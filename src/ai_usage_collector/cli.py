"""CLI entrypoint for plasma-ai-usage-collector."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from ai_usage_collector import __version__
from ai_usage_collector.claude_hooks import HooksError, install_hooks, uninstall_hooks
from ai_usage_collector.codex_hooks import install_notify, uninstall_notify
from ai_usage_collector.session_state import all_live_states, state_dir_for
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
    get_accounts_for_agent,
    set_alert_settings,
    set_notify_settings,
    set_renew_settings,
    set_update_settings,
    set_provider_settings,
    set_visibility_settings,
)
from ai_usage_collector.pace import alert_settings
from ai_usage_collector.running import HIDE_MODES, refresh_running
from pathlib import Path
from ai_usage_collector.waybar import waybar_line
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
    parser.add_argument("--renew-account", nargs=2, metavar=("PROVIDER", "ACCOUNT_ID"),
                        help="Renova a sessão de uma Conta e consulta seu uso, sem trocar a Conta Ativa")
    parser.add_argument(
        "--force-renew",
        action="store_true",
        help="Com --refresh: renova as Contas inativas vencidas mesmo dentro do Intervalo de Atualização (\"Atualizar agora\")",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Exibe o payload canônico de status atual em JSON na saída padrão",
    )
    parser.add_argument(
        "--waybar",
        action="store_true",
        help="Imprime o status em JSON de uma linha para o modulo custom do Waybar (le o cache; nao coleta)",
    )
    parser.add_argument(
        "--install-hooks",
        nargs="?",
        const="claude",
        choices=("claude", "codex", "all"),
        metavar="{claude,codex,all}",
        help="Claude (padrão): registra no settings.json do Claude Code (CLAUDE_CONFIG_DIR, absoluto, ou ~/.claude) os hooks do Estado da Sessão: UserPromptSubmit (ocupada), PostToolUse (ocupada; batimento e fim da espera), Stop (ociosa) e Notification (aguardando). Codex: grava uma linha `notify` no topo do config.toml (CODEX_HOME, absoluto, ou ~/.codex), nunca sobrescreve um notify seu. Idempotente. Perfil isolado: rode com o CLAUDE_CONFIG_DIR / CODEX_HOME de cada perfil",
    )
    parser.add_argument(
        "--uninstall-hooks",
        nargs="?",
        const="claude",
        choices=("claude", "codex", "all"),
        metavar="{claude,codex,all}",
        help="Remove só os hooks (ou o notify do Codex) do Estado da Sessão do widget, preservando o resto da configuração",
    )
    parser.add_argument(
        "--session-state",
        action="store_true",
        help="Imprime em JSON o Estado da Sessão por Conta Claude e Codex (le o mapa do último refresh e os hooks; nao coleta)",
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
    parser.add_argument(
        "--set-notify-config",
        action="store_true",
        help="Define as notificações de limite: --notify-warning/--notify-critical (0 < aviso < crítico <= 100), --notify-early e --notify-reset (on|off), --notify-mute (provedores separados por vírgula; vazio limpa)",
    )
    parser.add_argument("--notify-warning", type=float, default=None, help="Limiar de aviso em %% (padrão 80)")
    parser.add_argument("--notify-critical", type=float, default=None, help="Limiar crítico em %% (padrão 95)")
    parser.add_argument("--notify-early", choices=["on", "off"], default=None, help="Aviso antecipado de esgotamento (padrão on)")
    parser.add_argument("--notify-reset", choices=["on", "off"], default=None, help="Aviso de reset de limite já sinalizado (padrão off)")
    parser.add_argument("--notify-mute", default=None, metavar="PROVIDERS", help="Provedores silenciados, separados por vírgula")
    parser.add_argument(
        "--set-update-config",
        action="store_true",
        help="Liga/desliga a verificação diária de atualização (GitHub Releases e npm): --update-check on|off (padrão on)",
    )
    parser.add_argument("--update-check", choices=["on", "off"], default=None, help="Verificação diária de atualização")
    parser.add_argument(
        "--set-renew-config",
        action="store_true",
        help="Liga/desliga a renovação de Contas Gemini inativas (usa o app OAuth da Antigravity e lê o segredo do binário agy; pode contrariar os termos do Google): --renew-gemini on|off (padrão off)",
    )
    parser.add_argument("--renew-gemini", choices=["on", "off"], default=None, help="Renovação de Contas Gemini inativas")
    parser.add_argument(
        "--set-visibility-config",
        action="store_true",
        help="Define quando ocultar o Plasmoid sem o processo da CLI: --hide-when-not-running off (padrão) | widget (esconde tudo) | provider (esconde só o provedor parado)",
    )
    parser.add_argument("--hide-when-not-running", choices=HIDE_MODES, default=None, help="off (padrão), widget ou provider")
    parser.add_argument(
        "--detect-running",
        action="store_true",
        help="Atualiza no status.json se o processo de cada CLI está em execução (lê /proc; cache de 5 s; não consulta provedores)",
    )
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

    if args.waybar:  # fora do try: sempre uma linha JSON valida e exit 0; ignora as demais opcoes
        try:
            sys.stdout.write(waybar_line(cache_path))
        except Exception:
            sys.stdout.write('{"text": "\\u2014", "tooltip": "", "class": "unknown", "alt": "unknown"}\n')
        return 0

    if args.hide_when_not_running is not None and not args.set_visibility_config:
        sys.stderr.write("Erro: --hide-when-not-running só vale junto de --set-visibility-config.\n")
        return 1

    try:
        if args.export_history:
            sys.stdout.write(export_history(cache_path, args.export_history, load_config(config_path)))
            sys.stdout.flush()
            return 0

        if args.install_hooks or args.uninstall_hooks:
            if args.install_hooks and args.uninstall_hooks:
                sys.stderr.write("Erro: use --install-hooks ou --uninstall-hooks, não os dois.\n")
                return 2
            install = bool(args.install_hooks)
            which = args.install_hooks or args.uninstall_hooks
            state_dir = state_dir_for(cache_path)
            actions = {
                "claude": (lambda: install_hooks(state_dir)) if install else uninstall_hooks,
                "codex": (lambda: install_notify(state_dir)) if install else uninstall_notify,
            }
            code = 0
            for provider in (("claude", "codex") if which == "all" else (which,)):
                try:
                    sys.stdout.write(actions[provider]() + "\n")
                except HooksError as e:
                    sys.stderr.write(f"Erro ({provider}): {e}\n")
                    code = 1
            return code

        if args.session_state:
            sys.stdout.write(json.dumps(all_live_states(cache_path)) + "\n")
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

        if args.detect_running:
            refresh_running(load_config(config_path), Path(cache_path).expanduser().resolve())
            return 0

        if args.set_visibility_config:
            if args.hide_when_not_running is None:
                sys.stderr.write("Erro: informe --hide-when-not-running off|widget|provider.\n")
                return 1
            ok, message = set_visibility_settings(args.hide_when_not_running, config_path)
            if ok:
                reapply_alert_levels(config_path, cache_path)  # so atualiza o status; sem consulta aos provedores
            (sys.stdout if ok else sys.stderr).write((message if ok else f"Erro: {message}") + "\n")
            return 0 if ok else 1

        if args.set_notify_config:
            on = lambda v: None if v is None else v == "on"  # noqa: E731
            mute = None if args.notify_mute is None else [p.strip().lower() for p in args.notify_mute.split(",") if p.strip()]
            ok, message = set_notify_settings(
                args.notify_warning, args.notify_critical, on(args.notify_early), on(args.notify_reset), mute, config_path
            )
            if ok:
                reapply_alert_levels(config_path, cache_path)  # so atualiza o status; sem consulta aos provedores
            (sys.stdout if ok else sys.stderr).write((message if ok else f"Erro: {message}") + "\n")
            return 0 if ok else 1

        if args.set_renew_config:
            if args.renew_gemini is None:
                sys.stderr.write("Erro: --set-renew-config exige --renew-gemini on|off.\n")
                return 1
            ok, message = set_renew_settings(args.renew_gemini == "on", config_path)
            reapply_alert_levels(config_path, cache_path)  # so atualiza o status; sem rede
            sys.stdout.write(message + "\n")
            return 0

        if args.set_update_config:
            if args.update_check is None:
                sys.stderr.write("Erro: --set-update-config exige --update-check on|off.\n")
                return 1
            ok, message = set_update_settings(args.update_check == "on", config_path)
            reapply_alert_levels(config_path, cache_path)  # so atualiza o status; sem consulta de rede
            sys.stdout.write(message + "\n")
            return 0

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

        if args.renew_account:
            provider, account_id = args.renew_account
            config = load_config(config_path)
            if provider not in SUPPORTED_PROVIDERS or not any(str(a.get("id")) == account_id for a in get_accounts_for_agent(config, provider)):
                sys.stderr.write("Erro: Conta ou provedor não encontrado para renovar.\n")
                return 2
            try:
                intervals = parse_intervals(args.refresh_interval)
            except ValueError as exc:
                sys.stderr.write(f"Erro: {exc}\n")
                return 2
            status_data = collect_and_save(config_path=config_path, cache_path=cache_path,
                                           providers=[provider], intervals=intervals, force_renew=True,
                                           renew_account=(provider, account_id))
            if args.status:
                sys.stdout.write(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n")
            return 0

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
            and not args.set_notify_config
            and not args.set_update_config
            and not args.set_renew_config
            and not args.set_visibility_config
            and not args.detect_running
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
                force_renew=args.force_renew,
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
