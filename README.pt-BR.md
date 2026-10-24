# Plasma AI Usage Widget

**Limites de uso do Claude, Codex e Gemini no seu desktop KDE Plasma 6.**

Veja sua cota, os horários de liberação e as contas ativas sem abrir três ferramentas diferentes.

[![Última versão](https://img.shields.io/github/v/release/victorlcs87/plasma-ai-usage-widget)](https://github.com/victorlcs87/plasma-ai-usage-widget/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/plasma-ai-usage-collector)](https://pypi.org/project/plasma-ai-usage-collector/)
[![KDE Plasma 6](https://img.shields.io/badge/KDE-Plasma_6-1d99f3)](https://kde.org/plasma-desktop/)
[![Licença](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Apoie no Ko-fi](https://img.shields.io/badge/Ko--fi-Apoie_o_projeto-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/victorlcs87)

[Baixar](https://github.com/victorlcs87/plasma-ai-usage-widget/releases/latest) · [Instalar](#instalação) · [Relatar problema](https://github.com/victorlcs87/plasma-ai-usage-widget/issues/new?template=bug_report.yml) · [English](README.md)

![Widget compacto no painel com indicadores de uso do Claude, Codex e Gemini](docs/images/panel.png)

<p align="center">
  <img src="docs/images/overview.png" alt="Widget expandido com cotas atuais e semanais, horários de liberação, alertas e histórico de tokens dos três provedores" width="440">
</p>

*Capturas dos componentes QML do projeto com dados fictícios de demonstração, sem informações de contas reais.*

## Recursos

- **Três provedores em um lugar:** Claude Code, OpenAI Codex e Gemini / Antigravity.
- **Cotas atuais e semanais:** percentual usado ou restante, contagem regressiva ou data da liberação. Dados ausentes são indicados.
- **Várias contas:** captura, alternância e renomeação com perfis isolados de credenciais.
- **Alertas:** por ritmo de consumo ou percentuais fixos, com notificações opcionais.
- **Visual configurável:** anéis, percentuais, barras, notch flutuante e indicadores opcionais de sessão para Claude Code e Codex.
- **Histórico de tokens:** gráficos e exportação em CSV ou JSON, quando houver dados locais de uso.
- **Inglês e português brasileiro**, com suporte a traduções.
- **Coletor Python leve:** sem dependências de execução de pacotes Python e com saída opcional para Waybar.

## Instalação

Requisitos: **KDE Plasma 6**, **Python 3.10+ com `venv` e `ensurepip`** e login no provedor que deseja acompanhar. A disponibilidade das cotas varia conforme o provedor, a conta e a autenticação; uma chave de API, sozinha, pode não fornecer os limites da assinatura.

### 1. Instale o widget

Baixe `org.kde.plasma.aiusage.plasmoid` no [último release](https://github.com/victorlcs87/plasma-ai-usage-widget/releases/latest). No Plasma, abra **Adicionar widgets → Obter novos widgets → Instalar widget de arquivo local**, selecione o pacote e adicione **Monitor de Uso de IA** ao painel ou à área de trabalho. Os nomes dos menus podem variar com a versão e o idioma do Plasma.

Pelo terminal, na pasta do arquivo baixado:

```bash
kpackagetool6 --type Plasma/Applet --install ./org.kde.plasma.aiusage.plasmoid
```

Para atualizar uma instalação existente, troque `--install` por `--upgrade`.

### 2. Instale o coletor

Abra o widget, clique em **Install collector** e confirme. Ele instala do PyPI a versão correspondente ao widget, em um ambiente virtual próprio, sem `sudo` ou alterações no Python do sistema. O coletor é obrigatório para exibir o uso.

Se preferir gerenciar o coletor, use pipx para instalar a **mesma versão do widget**. Para o release `v1.2.1`:

```bash
pipx install plasma-ai-usage-collector==1.2.1
```

### 3. Adicione suas contas

Entre pela CLI do provedor e use a configuração do widget para capturar a conta atual. Também é possível capturar pelo terminal:

```bash
ai-usage-collector --capture-current claude
ai-usage-collector --capture-current codex
ai-usage-collector --capture-current gemini
ai-usage-collector --refresh
```

Execute apenas as capturas dos provedores que usa. Veja os caminhos de credenciais do Gemini / Antigravity no [guia técnico](docs/usage.pt-BR.md#credencial-do-gemini).

## O que os anéis mostram

Na visualização expandida, o **anel interno** representa a janela atual e o **externo**, o limite semanal. A duração depende dos dados do provedor. O painel compacto normalmente mostra a janela atual.

Por padrão, o arco representa a **cota usada**. A opção **Restante** mostra o saldo. A marca branca indica o tempo decorrido quando a duração é conhecida. As cores seguem o modo de alerta configurado. Um traço indica ausência de leitura confiável, em vez de consumo zero.

## Privacidade

O widget e o coletor rodam na sua máquina. **Sem servidor do projeto, telemetria ou análise de uso.** As credenciais ficam localmente, e as consultas de cota acessam os endpoints do provedor correspondente.

A checagem opcional de atualizações consulta GitHub e npm. A instalação do coletor acessa o PyPI após confirmação. Captura, alternância e renovação usam credenciais locais. A renovação automática de contas Gemini inativas vem **desligada**; veja [detalhes e limitações](docs/usage.pt-BR.md#renovação-automática-das-contas-inativas).

As APIs dos provedores podem mudar ou limitar consultas. O widget informa dados indisponíveis, sessões vencidas e leituras desatualizadas; a disponibilidade não é igual em todos os planos.

## Documentação e contribuição

- [Guia técnico completo](docs/usage.pt-BR.md): configuração, Waybar, histórico, renovação, notificações e traduções.
- [Histórico de versões](CHANGELOG.md).
- [Como contribuir](CONTRIBUTING.md) e [decisões de arquitetura](docs/adr/).
- [Relatar problema](https://github.com/victorlcs87/plasma-ai-usage-widget/issues/new?template=bug_report.yml) ou [sugerir melhoria](https://github.com/victorlcs87/plasma-ai-usage-widget/issues/new?template=feature_request.yml). Pode escrever em português. Remova credenciais e dados pessoais de logs e capturas.

## Apoie o projeto

Se o widget facilita seu dia, você pode [me pagar um café no Ko-fi](https://ko-fi.com/victorlcs87). Seu apoio voluntário ajuda a manter e melhorar o projeto. O widget continua gratuito e com código aberto.

## Licença

[GPL-3.0-or-later](LICENSE). Projeto independente, sem afiliação ou endosso de KDE, Anthropic, OpenAI ou Google. Os logos identificam os respectivos provedores; veja os [créditos](plasmoid/contents/ui/LOGOS.md).
