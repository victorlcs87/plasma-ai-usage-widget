# Página da KDE Store

Texto para colar em store.kde.org (categoria Plasma 6 Widgets). Suba o `.plasmoid` só depois que o pacote estiver no PyPI (ver `docs/release-checklist.md`).

Repositório: https://github.com/victorlcs87/plasma-ai-usage-widget
Licença: GPL-3.0-or-later.

## English

**Title:** AI Usage Widget

**Summary:** See your Claude, Codex and Gemini usage limits and reset times in the Plasma panel. Local and read-only.

**Description:**

AI Usage Widget shows how much of your Claude, Codex and Gemini quota you have used, per account, right in the Plasma 6 panel and popup.

What it does:

- Panel item per provider with the provider logo and an arc for the current native window (for example, the 5-hour window). Click it to open the popup with the native and weekly arcs.
- Multiple accounts per provider, with isolated profiles so you can switch and rename them.
- Reset countdown, pace and threshold alerts, optional desktop notifications, optional floating notch and optional session state (all opt-in).
- Daily token history that you can export as CSV or JSON.
- Available in English and Brazilian Portuguese.

**Requirement: the collector is mandatory.** The widget only displays data written by the companion Python package `plasma-ai-usage-collector`. Without it the widget shows nothing. Needs `python3` with `venv` support.

How to install the collector (pick one):

1. Click **Install collector** in the widget popup and confirm. It installs the exact version matching the widget from PyPI into `~/.local/share/plasma-ai-usage/venv`, with a shortcut in `~/.local/bin`. No sudo, never automatic, and it never touches a collector you installed yourself.
2. Or run `pipx install plasma-ai-usage-collector`.

Privacy:

- Everything runs on your machine. There is no telemetry, no analytics and no account on a server of ours.
- The collector reads your own provider credentials locally and queries each provider's own usage endpoints (Anthropic, OpenAI, Google) to get your quota. Nothing else is sent.
- Optional daily update check (on by default, can be turned off in settings or with `--set-update-config --update-check off`): read-only requests to api.github.com (latest widget release) and registry.npmjs.org (latest Claude Code, Codex and Gemini CLI versions), without credentials. Nothing is downloaded or installed by it.
- The collector install button contacts PyPI only after you confirm.
- Renewing inactive Gemini accounts is off by default.

Trademarks: Claude and Anthropic are trademarks of Anthropic PBC; OpenAI and Codex of OpenAI, Inc.; Gemini and Google of Google LLC. This project is independent and is not affiliated with, endorsed by or sponsored by those companies. Logos are used only to identify the provider.

Source code and issues: https://github.com/victorlcs87/plasma-ai-usage-widget

## Português (Brasil)

**Título:** AI Usage Widget

**Resumo:** Veja os limites de uso e os horários de renovação do Claude, Codex e Gemini no painel do Plasma. Local e somente leitura.

**Descrição:**

O AI Usage Widget mostra quanto da cota do Claude, Codex e Gemini você usou, por conta, no painel e no popup do Plasma 6.

O que ele faz:

- Um item no painel por provedor, com o logo e um arco da janela nativa (por exemplo, a de 5 horas). Clique para abrir o popup com os arcos nativo e semanal.
- Várias contas por provedor, com perfis isolados para trocar e renomear.
- Contagem regressiva, alertas por ritmo ou limiar, notificações, Notch flutuante e estado da sessão (tudo opcional).
- Histórico diário de tokens, exportável em CSV ou JSON.
- Em inglês e português do Brasil.

**Requisito: o Coletor é obrigatório.** O widget só exibe dados gravados pelo pacote Python `plasma-ai-usage-collector`. Sem ele, não mostra nada. Precisa de `python3` com suporte a `venv`.

Como instalar o Coletor (escolha um):

1. Clique em **Install collector** no popup do widget e confirme. Ele instala do PyPI a versão exata do widget em `~/.local/share/plasma-ai-usage/venv`, com atalho em `~/.local/bin`. Sem sudo, nunca automático, e nunca mexe num coletor que você instalou.
2. Ou rode `pipx install plasma-ai-usage-collector`.

Privacidade:

- Tudo roda na sua máquina. Não há telemetria, análise de uso nem conta em servidor nosso.
- O coletor lê localmente as suas credenciais dos provedores e consulta os endpoints de uso de cada provedor (Anthropic, OpenAI, Google) para obter a cota. Nada mais é enviado.
- Checagem diária de atualização, opcional (ligada por padrão; desligue na configuração ou com `--set-update-config --update-check off`): consultas somente leitura a api.github.com (última versão do widget) e registry.npmjs.org (últimas versões das CLIs Claude Code, Codex e Gemini), sem credenciais. Ela não baixa nem instala nada.
- O botão de instalar o Coletor só fala com o PyPI depois da sua confirmação.
- A renovação das contas Gemini inativas vem desligada.

Marcas: Claude e Anthropic são marcas da Anthropic PBC; OpenAI e Codex, da OpenAI, Inc.; Gemini e Google, da Google LLC. Este projeto é independente e não tem afiliação, endosso nem patrocínio dessas empresas. Os logos só identificam o provedor.

Código-fonte e issues: https://github.com/victorlcs87/plasma-ai-usage-widget

## Capturas de tela a tirar

Tire em tema claro ou escuro padrão, com dados fictícios (use `tools/smoke_status.py` ou contas de teste; nunca e-mails reais). Não foram geradas.

1. `01-painel.png`: painel com os três itens de provedor (logo e arco).
2. `02-popup.png`: popup aberto com os arcos nativo e semanal do provedor em destaque e a lista de contas.
3. `03-card-coletor.png`: card "Collector not installed" com o botão Install collector.
4. `04-confirmacao.png`: confirmação inline (pacote, versão, destino, sem sudo).
5. `05-instalando.png`: card durante a instalação, com a etapa atual.
6. `06-alertas-notch.png`: Notch flutuante com um alerta de ritmo.
7. `07-configuracao.png`: aba Geral da configuração (intervalo, caminho do coletor, checagem de atualização).
8. `08-pt-br.png`: popup em português do Brasil.
