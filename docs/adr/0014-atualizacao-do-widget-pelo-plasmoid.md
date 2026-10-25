# 0014. Atualizacao do Widget pelo Plasmoid

Status: proposta (aguarda spec)

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
- O `package-release.sh` roda `scripts/check-release-hash.py` no fim e falha se o hash faltar ou divergir do zip. O zip e reprodutivel (datas e modos fixos), entao os jobs `release` (GitHub) e `pypi-build` geram os mesmos bytes; o `pypi-build` passou a publicar o wheel do `package-release.sh` (sem sdist, que nao carregaria o hash).
