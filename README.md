# Plasma AI Usage Collector

Coletor de métricas de uso e cotas de agentes de IA (Claude, Codex e Gemini) para o widget nativo KDE Plasma 6.

## Waybar

`ai-usage-collector --waybar` imprime uma linha JSON (`text`, `tooltip`, `class`, `alt` e, quando há nível, `percentage`) a partir do cache, sem consultar provedores nem a rede, sempre com exit code 0. Mantenha o cache atualizado com `ai-usage-collector --refresh` (ou pelo Plasmoid).

A classe é o pior nível de alerta entre as Contas Ativas no Sistema (contas inativas não contam): `normal`, `warning` ou `critical`. Sem nível confiável a classe é neutra: `stale` (dados desatualizados, erro ou pausa por HTTP 429) ou `unknown` (sem cache, cache inválido ou nenhuma conta ativa; texto `—`). Nunca é mostrado um 0% inventado. Rótulos de conta são escapados para o Pango markup do Waybar.

```jsonc
// ~/.config/waybar/config.jsonc
"custom/ai-usage": {
    "exec": "ai-usage-collector --waybar",
    "return-type": "json",
    "interval": 30,
    "tooltip": true
}
```

```css
/* ~/.config/waybar/style.css */
#custom-ai-usage.warning { color: #f9e2af; }
#custom-ai-usage.critical { color: #f38ba8; }
#custom-ai-usage.stale, #custom-ai-usage.unknown { opacity: 0.6; }
```

Notas: `text` pode mostrar o % de uma janela com leitura local enquanto a classe fica `unknown` (leitura local não recebe nível); `percentage` considera só janelas com nível. Percentuais fora de 0..100 são limitados e NaN/Infinity são ignorados. A saída é JSON ASCII (acentos escapados como `\uXXXX`, válido para o Waybar), o tooltip mostra no máximo 20 linhas, e `--waybar` ignora as demais opções (só `--cache-path` vale).

## Painel e popup

No painel cada item mostra o logo do provedor e o arco da Janela Nativa. Clique no item para abrir o popup com os dois arcos (nativa e semanal) daquele provedor no topo; passar o mouse abre o popup sem destacar ninguém.

## Onde o widget procura o coletor

O plasmoide chama `ai-usage-collector` pelo shell, nesta ordem: o `PATH`, `~/.local/bin/ai-usage-collector`, o venv do
pipx (`~/.local/share/pipx/venvs/plasma-ai-usage-collector/bin/`) e, só por último, o caminho da opção **Caminho do
coletor** (Configuração > Geral; `collectorPath` em `main.xml`, vazio por padrão; aceita `~/`). Se nada for achado, cai em
`python3 -m ai_usage_collector`. Para um venv de desenvolvimento, preencha o campo com
`~/caminho/do/repo/.venv/bin/ai-usage-collector`; nenhum caminho pessoal vai no código.

## Histórico de Tokens, órfãos e configuração pela CLI

- **Exportar o histórico:** `ai-usage-collector --export-history csv|json` imprime o Histórico de Tokens diário (até 400 dias, por provedor, Conta e modelo) na saída padrão. Identidades sem Conta cadastrada saem mascaradas.
- **Perfis Órfãos** (Perfis Isolados sem Conta): `--list-orphans` lista em JSON, `--reimport-orphan PROVEDOR PERFIL` reimporta como Conta (funde se a identidade já existir) e `--delete-orphan PROVEDOR PERFIL --confirm` exclui do disco. Nada é apagado sem `--confirm`.
- **Opções `--set-*`** (as mesmas que a tela de configuração aplica): `--set-provider-config PROVEDOR` (`--credential-path`, e no Claude `--api-base-url`, `--api-key-stdin`, `--clear-api-key`), `--set-alert-config` (`--alert-mode pace|threshold`, `--alert-warning`, `--alert-critical`), `--set-notify-config` (`--notify-warning`, `--notify-critical`, `--notify-early`, `--notify-reset`, `--notify-mute`), `--set-update-config` (`--update-check on|off`), `--set-renew-config` (`--renew-gemini on|off`, padrão off) e `--set-visibility-config` (`--hide-when-not-running off|widget|provider`).

## Renovação automática das Contas inativas

A cada Intervalo de Atualização o coletor renova, antes de consultar o uso, as Contas **inativas** com login vencido. Só mexe no Perfil Isolado da Conta (`profiles/`); a Conta Ativa no Sistema nunca é renovada pelo coletor. No máximo uma tentativa por Conta por intervalo.

- **Claude:** `claude auth status` com o perfil da Conta.
- **Codex:** `codex app-server` (`account/read` com renovação do token), sem gastar tokens de modelo.
- **Gemini (opt-in, desligada por padrão):** renovação do token no Google. Usa o app OAuth da Antigravity e lê o segredo do binário `agy` instalado (nunca vem no repositório), o que pode contrariar os termos do Google. Ligue em Configuração > Geral ("Renovar Contas Gemini inativas automaticamente") ou com `ai-usage-collector --set-renew-config --renew-gemini on` (`off` desliga). Desligada, o coletor nunca lê o `agy` nem chama o endpoint de token do Google, e a Conta Gemini vencida só avisa para você entrar de novo no provedor.

Requisitos: Plasma aberto, `claude` e `codex` no `PATH` e `agy` instalado e a opção ligada para o Gemini. Limites: o refresh token vale cerca de 30 dias; a Conta Ativa depende do uso da própria CLI. Tokens e saída das CLIs não vão para log nem para o `status.json`; só a classe do erro.

O card da Conta explica o estado: renovação pendente (nova tentativa na próxima consulta), login revogado, CLI ou `agy` não encontrado, tempo esgotado, rede indisponível ou falha genérica. Nos casos sem solução automática, faça login no provedor com a Conta. Riscos e decisões: `docs/adr/0013-renovacao-de-conta-inativa.md`.

## Credencial do Gemini

A captura (`--capture-current gemini`) procura a sessão ativa nesta ordem: chaveiro (`secret-tool`, serviço `gemini`, usuário `antigravity`), `~/.gemini/oauth_creds.json` e `~/.gemini/antigravity-cli/antigravity-oauth-token` (CLI Antigravity, formato aninhado em `token`). `GEMINI_CONFIG_DIR` troca `~/.gemini`. Esses arquivos e o chaveiro são só lidos na captura; a cópia fica isolada em `profiles/` com permissão 0600.

## Notificações de limite (opt-in)

O coletor avisa quando uma janela passa dos limiares, esgotará antes da liberação ou, se ativado, foi liberada. Configure em Configuração > Notificações ou com `--set-notify-config`. O envio usa o binário **`notify-send`** (libnotify) numa sessão gráfica com serviço de notificações; **não** fala D-Bus diretamente. Sem o `notify-send` (ou sem barramento de sessão) o aviso falha em silêncio: o coletor segue normalmente, registra uma única mensagem em stderr, tenta de novo no próximo ciclo sem repetir a mensagem e a marca some quando um envio funciona (`notify_failed` ao lado do `status.json`).

## Estado da Sessão (Claude Code e Codex, opt-in)

`ai-usage-collector --install-hooks` registra hooks no `settings.json` do Claude Code (`CLAUDE_CONFIG_DIR`
absoluto ou `~/.claude`); `--uninstall-hooks` remove só os do widget (pode reindentar o arquivo). Perfil
isolado: rode com o `CLAUDE_CONFIG_DIR` de cada perfil. Para o Codex, o estado "ocupada" vem dos logs de sessão sem instalar nada;
`ai-usage-collector --install-hooks codex` (opcional) grava uma linha `notify` no `config.toml` (`CODEX_HOME`), nunca sobrescreve um `notify` seu, encerra
o estado ocupado ao fim de cada turno e é o que habilita o som e o Notch no Codex (sem ele o Codex só mostra o estado). Ative "Mostrar o estado da sessão" na configuração
do plasmoide. O caminho leve de consulta (`ai-usage-session-state`) exige reinstalar o pacote
(`pip install -e .`); ele lê `session-accounts.json`, atualizado a cada refresh. Detalhes e limitações no
ADR-0009.

## Cores: acento e alerta

Os acentos "red" e "orange" do Notch podem coincidir com a cor de alerta (crítico/atenção). O nível nunca depende só da cor: ele
aparece também pela forma (normal ●, atenção ▲, crítico ■, sem nível ○) e pela palavra.

## Traduções (i18n)

O Plasmoid segue o idioma do sistema: inglês (texto-fonte, convenção KDE) e português do Brasil, ambos completos.

- **Mecanismo único:** `plasmoid/contents/ui/I18n.js` (`tr`, `trc`, `trp`), que chama `i18n`/`i18nc`/`i18np` do KDE e,
  sem eles (harness `qml6`, testes), devolve o texto em inglês com os `%N` substituídos. Os modelos JS recebem `I18n.tr`
  como parâmetro `tr`. Só literais de string entram como msgid; nome de conta, mensagem do coletor etc. vão como
  argumento `%N`, nunca como msgid. Use frases inteiras com `%N` (nada de montar frase por pedaços) e `trp` para plurais.
- **Catálogos:** `po/plasma_applet_org.kde.plasma.aiusage.pot` (domínio = `plasma_applet_` + `KPlugin.Id` do
  `metadata.json`), `po/pt_BR.po` e `po/en.po` (`en.po` é gerado: msgstr = msgid).
- **Regenerar o `.pot` e sincronizar os `.po`** (só Python, determinístico): `python3 tools/i18n.py extract && python3 tools/i18n.py update`.
  `python3 tools/i18n.py check` acusa msgid não literal e texto visível fora de i18n.
- **Novo idioma:** crie `po/<codigo>.po` copiando o `.pot` (ex.: `cp po/*.pot po/es.po`), rode `update`, traduza todas as
  entradas (sem `fuzzy`, sem vazias, mesmos `%N`) e, se o idioma tiver regra de plural diferente, ajuste `PLURALS` em `tools/i18n.py`.
  O teste `tests/test_i18n.py` valida o novo arquivo sozinho (adicione o código em `LANGS`).
- **`.mo`:** `scripts/install-plasmoid.sh` compila `po/*.po` (`tools/i18n.py compile`) para
  `contents/locale/<idioma>/LC_MESSAGES/plasma_applet_org.kde.plasma.aiusage.mo` numa cópia temporária e instala essa cópia;
  os `.mo` não são versionados.
- **Limites conhecidos:** `health.message` (diagnóstico do coletor, em português) é mostrado como veio; o erro de consulta
  (`fetch_error`) é traduzido pelo `kind`. Data/hora usam o formato fixo `dd/MM HH:mm` e as unidades abreviadas da contagem
  regressiva (`d h m s`) não variam por idioma.

## Smoke no runtime real do Plasma

`scripts/plasmoidviewer-smoke.sh [diretório-de-PNGs]` instala o plasmoide num HOME temporário, gera um `status.json` de
fixture (`tools/smoke_status.py`), roda o `plasmoidviewer` sob `xvfb-run` em pt_BR e en_US, horizontal e vertical, clica na
pílula (`xdotool`) e salva PNGs (`import`). Sai com código != 0 se o log tiver erro de QML do plasmoide (recursive
rearrange, TypeError, ReferenceError, Unable to assign, is not defined, Binding loop). Não usa a sessão nem dados reais.
Requer `plasmoidviewer` (plasma-sdk), `xvfb-run`, `xdotool` e ImageMagick; `tests/test_plasmoidviewer_smoke.py` o roda se existirem.

## Licença e marcas

GPL-3.0-or-later (ver `LICENSE`). Claude e Anthropic são marcas da Anthropic PBC; OpenAI e Codex, da OpenAI, Inc.; Gemini e Google, da Google LLC. Este projeto é independente e não tem afiliação nem endosso dessas empresas; os logos só identificam o provedor.
