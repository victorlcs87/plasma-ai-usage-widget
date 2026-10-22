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

## Consequencias

O widget depende da disponibilidade do PyPI no momento da instalacao. O envio inicial a loja KDE e manual.
