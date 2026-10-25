# 0014. Atualizacao do Widget pelo Plasmoid

Status: aceita

## Contexto

`updates.py` so avisa de versao nova. O usuario pediu um botao que busque a ultima release e atualize o app. O ADR-0012 proibe instalacao automatica e exige consentimento; a loja KDE reprova execucao de codigo baixado sem ele.

## Decisao

- Escopo: Plasmoid + Coletor, sempre na mesma versao. Fora: CLIs dos agentes (claude/codex/gemini).
- Sempre com confirmacao inline (versao atual -> nova, origem GitHub Releases, sem `sudo`). Nada por timer, partida ou abertura do popup.
- Ordem: Coletor novo primeiro (fluxo do ADR-0012); depois o `.plasmoid` por `kpackagetool6 --upgrade`. Falha no Coletor nao altera nada; Coletor novo com Plasmoid antigo e compativel. Sem backup/rollback do QML.
- Integridade: o wheel do Coletor embute o SHA256 do `.plasmoid` da mesma release (PyPI e GitHub sao canais independentes). O zip so e instalado se o hash bater; host fixo, https, sem redirect aberto. Um hash publicado ao lado do zip na release nao protege contra release adulterada, por isso nao e usado.
- Recarga: ao final o card pede "Recarregar o widget"; nunca reinicia o plasmashell sozinha. Ate la o QML antigo segue em memoria.
- Interface: botao "Atualizar para vX" so com versao nova, no cabecalho do popup, menu de contexto do painel, menu do Notch e janela de configuracao. Sem versao nova, "Buscar atualizacao" forca uma consulta (Busca de Atualizacao) e informa que ja esta na atual.

## Consequencias

- O workflow de release passa a gerar o hash do `.plasmoid` antes de construir o wheel, e o zip publicado no GitHub precisa ser exatamente o hasheado.
- Depende de `kpackagetool6` e do PyPI no momento da atualizacao.

## Implementacao

- O hash vive no wheel como modulo gerado `ai_usage_collector/_plasmoid_sha256.py` (`PLASMOID_SHA256 = "<hex>"`), escrito por `scripts/package-release.sh` depois de gerar o `.plasmoid` e removido ao sair; nao e versionado (esta no `.gitignore`). Modulo `.py` evita configurar package-data.
- Leitura: `ai-usage-collector --plasmoid-sha256` imprime o hex minusculo de 64 caracteres numa linha e sai 0; sem hash embutido (arvore de desenvolvimento, versao <= 1.2.3) ou malformado, nao imprime nada e sai 1. Em Python: `ai_usage_collector.plasmoid_hash.plasmoid_sha256()`.
- O `package-release.sh` roda `scripts/check-release-hash.py` no fim e falha se o hash faltar ou divergir do zip. O workflow constroi uma vez (job `package`, `upload-artifact`) e os jobs `release` (GitHub) e `pypi-build` baixam os mesmos bytes; assim nao depende de o zlib dos runners coincidir (menor que conferir o hash depois). O zip continua reprodutivel (datas e modos fixos), o que o teste de empacotamento garante.
- Remover o sdist do PyPI e decisao consciente: o wheel e `py3-none-any` puro, o sdist nao carregaria o hash embutido, e o Trusted Publisher segue valido.
- Instalador: `collector-installer.py update --version X.Y.Z` reaproveita o install (venv, pip, link, verify) e acrescenta `plasmoid_hash`, `plasmoid_download` (tag `vX.Y.Z`, nunca `latest`), `plasmoid_verify` e `plasmoid_install` (`kpackagetool6 --upgrade`). Causas finais: as do install mais `sem_hash` e `kpackagetool`.
- Busca de Atualizacao: `ai-usage-collector --check-update` imprime uma linha JSON (`nova` com versao, `atual` ou `indisponivel`; `desligada` e decidida pela configuracao no Plasmoid).
- Estado no `main.qml`: `idle | buscando | confirmando | atualizando | concluido | erro`, com watchdog, pausa de 5 s entre buscas e uma unica instalacao/atualizacao por vez. `WidgetUpdate.qml` desenha botao, confirmacao inline, progresso, erro e recarga; esta no popup e na configuracao. Os menus do painel (`contextualActions`) e do Notch chamam `requestWidgetUpdate`, que so busca ou abre a confirmacao no popup.
- Canal da configuracao: a janela de configuracao e outro processo QML; o estado chega por `widgetUpdateMirror` e os pedidos voltam por `widgetUpdateRequest` (entradas de `main.xml`).
- Limitacoes: o canal da configuracao aceita `start` de qualquer processo do mesmo usuario que escreva o campo `widgetUpdateRequest`; mitigado pelo SHA256 do plasmoid e pelo estado `confirmando` (`start` so vale depois de um `ask`).
- Primeira atualizacao: Coletores <= 1.2.3 nao embutem hash e terminam em `sem_hash`; a atualizacao manual esta em `docs/usage.pt-BR.md`.
