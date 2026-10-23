# 0012. Instalador do Coletor pelo Plasmoid

Status: aceita

## Contexto

A loja KDE distribui so o Plasmoid (QML). O Coletor (Python) e obrigatorio: sem ele o widget instalado mostra apenas "Status cache not found".

## Decisao

- O Coletor e publicado no PyPI (`plasma-ai-usage-collector`) e o Plasmoid oferece um **Instalador do Coletor**.
- Instala sempre a versao **exata** do Plasmoid (`==X.Y.Z`), nunca "a ultima".
- Destino: venv proprio do widget e symlink em `~/.local/bin`; sem `sudo`, sem tocar no Python do sistema. Sem `python3` com `venv`/`ensurepip`, mostra o que falta em vez de instalar Python.
- **Nunca automatico**: so apos confirmacao que mostra o pacote, a versao e o destino. Executar codigo baixado sem consentimento seria risco de seguranca e motivo de reprovacao na loja.
- Coletor mais antigo que o Plasmoid: oferece atualizar pelo mesmo fluxo; mais novo: so avisa.
- Publicacao no PyPI por Trusted Publisher (OIDC) no workflow de release, sem token guardado. O PyPI precede o envio do Plasmoid a loja.
- Licenca GPL-3.0-or-later.

## Implementacao (o que ficou)

- O instalador e o script `plasmoid/contents/code/collector-installer.py`, empacotado no Plasmoid. Usa so a stdlib e roda com o `python3` do sistema, sem o Coletor. Dois subcomandos: `status --required X.Y.Z` (uma linha JSON: `ausente`, `desatualizado`, `ok`, `mais_novo` ou `python_indisponivel`) e `install --version X.Y.Z` (uma linha JSON por etapa `venv`, `download`, `install`, `link`, `verify` e uma linha final `result`).
- Nao ha argumento de indice nem de URL: a versao precisa ser `X.Y.Z` estrita e o pip roda com `--isolated` e `--index-url https://pypi.org/simple` explicito, entao `PIP_*` e `pip.conf` do usuario nao valem e "baixado do PyPI" e verdade. Override so por `PLASMA_AI_INSTALLER_INDEX` (URL) e `PLASMA_AI_INSTALLER_FIND_LINKS` (diretorio de `.whl`, com `--no-index`), apenas para testes/ambientes offline, nunca por argumento. Do ambiente do usuario o pip recebe so proxy/certificado (`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `PIP_CERT`); `PYTHONPATH`, `PYTHONHOME` e `VIRTUAL_ENV` sao descartadas.
- O Plasmoid executa o script pelo DataSource `executable`, so apos clique e confirmacao inline no card do popup (pacote, versao, destino, sem `sudo`). Nada roda na partida, por timer ou ao abrir o popup. Ao fim, rechecka o status e faz um `--refresh`.
- Causas classificadas: `python_indisponivel`, `rede`, `versao_inexistente`, `permissao`, `conflito_em_local_bin`, `verificacao`, `falha`. O timeout do pip (300 s) conta como `rede`. O log guarda ~30 linhas, sem credenciais de URL e com `~` no lugar do HOME.
- Seguranca: nunca sobrescreve um `~/.local/bin/ai-usage-collector` que nao aponte para o venv do widget (conflito, nada alterado); lock (`install.lock`) contra instalacoes simultaneas; em falha ou sinal remove so o que a propria execucao criou.
- Publicacao: jobs `pypi-build` e `pypi-publish` (environment `pypi`) no `release.yml`, so em tag `vX.Y.Z`, em paralelo ao job de release do GitHub. `scripts/check-release-versions.py` exige tag = `pyproject.toml` = `metadata.json`.

## Limitacoes

- O DataSource `executable` entrega a saida agregada, nao em fluxo: o progresso mostrado e indeterminado, com o nome da etapa atual.
- `kill -9` no instalador (ou queda do Plasma) pode deixar um `pip` orfao; o lock e solto pelo SO e a proxima tentativa reaproveita ou recria o venv.
- Como o job do PyPI roda em paralelo ao release do GitHub, um deles pode falhar sozinho; o checklist (`docs/release-checklist.md`) cobre o recurso manual.
- Publicacao real no PyPI e envio a loja ainda nao foram exercitados; so se confirmam no primeiro release.

## Consequencias

O widget depende da disponibilidade do PyPI no momento da instalacao. O envio inicial a loja KDE e manual.
