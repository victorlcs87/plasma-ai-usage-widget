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

## Onde o widget procura o coletor

O plasmoide chama `ai-usage-collector` pelo shell, nesta ordem: o `PATH`, `~/.local/bin/ai-usage-collector`, o venv do
pipx (`~/.local/share/pipx/venvs/plasma-ai-usage-collector/bin/`) e, só por último, o caminho da opção **Caminho do
coletor** (Configuração > Geral; `collectorPath` em `main.xml`, vazio por padrão; aceita `~/`). Se nada for achado, cai em
`python3 -m ai_usage_collector`. Para um venv de desenvolvimento, preencha o campo com
`~/caminho/do/repo/.venv/bin/ai-usage-collector`; nenhum caminho pessoal vai no código.

## Estado da Sessão (Claude Code, opt-in)

`ai-usage-collector --install-hooks` registra hooks no `settings.json` do Claude Code (`CLAUDE_CONFIG_DIR`
absoluto ou `~/.claude`); `--uninstall-hooks` remove só os do widget (pode reindentar o arquivo). Perfil
isolado: rode com o `CLAUDE_CONFIG_DIR` de cada perfil. Ative "Mostrar o estado da sessão" na configuração
do plasmoid. O caminho leve de consulta (`ai-usage-session-state`) exige reinstalar o pacote
(`pip install -e .`); ele lê `session-accounts.json`, atualizado a cada refresh. Detalhes e limitações no
ADR-0009.

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
