# Checklist do mantenedor: release

Ordem obrigatória. O PyPI vem antes da loja KDE, porque o botão do widget instala do PyPI a versão exata do widget. Itens marcados "primeiro release" só se confirmam no primeiro release real (PyPI real, loja real); nada disso foi exercitado ainda.

> **BLOQUEANTE (antes de tornar o repositório público e antes de qualquer tag):** o nome `plasma-ai-usage-collector` precisa estar publicado no PyPI e ser seu. Enquanto ele estiver livre, qualquer pessoa pode registrá-lo (squatting) e o botão do widget instalaria o pacote dela, executando código arbitrário na máquina do usuário. Crie o projeto (ou o pending publisher) e faça o primeiro publish (pode ser manual, com token do projeto; ver passo 7) ANTES de divulgar o `.plasmoid` ou o repositório.

## 1. Contas e Trusted Publisher (uma única vez)

- [ ] Conta no PyPI com 2FA.
- [ ] No GitHub: Settings > Environments > criar o ambiente `pypi` com **revisor obrigatório** (Required reviewers) e restrinja o deploy a tags `v*`.
- [ ] No PyPI, como o projeto `plasma-ai-usage-collector` ainda não existe, criar um *pending publisher* (Account settings > Publishing). Campos exatos:
  - Project name: `plasma-ai-usage-collector`
  - Owner: `victorlcs87`
  - Repository: `plasma-ai-usage-widget`
  - Workflow: `release.yml`
  - Environment: `pypi`
- [ ] Settings > Tags (ou Rulesets): proteção para tags `v*` (só mantenedores criam, ninguém apaga/move).
- [ ] Conta no store.kde.org.

## 2. Versão e verificações

- [ ] Mesma versão em `pyproject.toml` (`[project].version`) e `plasmoid/metadata.json` (`KPlugin.Version`). Em `CHANGELOG.md`, mova "Não lançado" para a nova versão.
- [ ] `python3 scripts/check-release-versions.py X.Y.Z` imprime "Versões consistentes".
- [ ] Suíte de testes completa verde (no venv: `.venv/bin/python -m pytest`).
- [ ] `gitleaks` sem achados novos (ver passo 3).

## 3. Tornar o repositório público

- [ ] **Bloqueante:** `https://pypi.org/project/plasma-ai-usage-collector/` existe e é seu (primeiro publish já feito).
- [ ] Rode `gitleaks detect` no histórico inteiro. Achados conhecidos e aceitos: fixtures falsas `sk-dummy-12345` e `ya29.vencido`. Qualquer outro achado bloqueia a publicação.
- [ ] Revise issues, specs e `docs/` por caminhos pessoais ou dados reais.
- [ ] Settings > Danger Zone > Change visibility > Public.

## 4. Tag e workflow

- [ ] **Bloqueante:** o nome no PyPI já é seu (aviso do topo) e o commit da tag está na `main` (o `pypi-build` recusa o contrário).
- [ ] Na `main` atualizada: crie e envie a tag `vX.Y.Z` (a mesma versão do passo 2). Só tags `vX.Y.Z[-sufixo]` disparam o PyPI.
- [ ] Acompanhe em Actions (`Release Automation`): `release` (GitHub Release com `.plasmoid` e `.whl`), `pypi-build` e `pypi-publish`. Os jobs do PyPI rodam em paralelo ao release do GitHub; um pode falhar sem o outro.
- [ ] Aprove o `pypi-publish` (o environment `pypi` tem revisor obrigatório).
- [ ] Primeiro release: o Trusted Publisher só se confirma aqui. Se o `pypi-publish` falhar por permissão, revise os campos do passo 1.

## 5. Confirmar o PyPI e o instalador

- [ ] https://pypi.org/project/plasma-ai-usage-collector/ mostra a versão `X.Y.Z`.
- [ ] Smoke com HOME limpo (usuário novo ou `HOME=$(mktemp -d)`): `pipx install plasma-ai-usage-collector==X.Y.Z` e `ai-usage-collector --version` devolve `X.Y.Z`.
- [ ] Smoke do botão: instale o `.plasmoid` da release num perfil sem Coletor, abra o popup, clique em Install collector, confirme e veja o card sumir e os dados aparecerem. Confira `~/.local/share/plasma-ai-usage/venv` e o atalho em `~/.local/bin`. Primeiro release: é a primeira vez que o botão fala com o PyPI de verdade.

## 6. KDE Store

Só depois do passo 5.

- [ ] store.kde.org > Add product, categoria Plasma 6 Widgets.
- [ ] Envie `dist/org.kde.plasma.aiusage.plasmoid` (o mesmo anexo da GitHub Release).
- [ ] Cole título, resumo e descrição de `docs/store/kde-store.md` (inglês e português) e suba as capturas listadas lá.
- [ ] Licença GPL-3.0-or-later e link do repositório preenchidos.
- [ ] Primeiro release: as regras e a revisão da loja só se confirmam no envio real.

## 7. Se o Actions estiver parado (billing)

Publique à mão, na ordem PyPI, depois GitHub Release.

```bash
python3 -m venv .venv && .venv/bin/pip install build twine
.venv/bin/python -m build --outdir dist-pypi
.venv/bin/twine check dist-pypi/*
.venv/bin/twine upload dist-pypi/*     # usuário __token__ e token de escopo do projeto
./scripts/package-release.sh           # gera dist/*.plasmoid e dist/*.whl
gh release create vX.Y.Z dist/*.plasmoid dist/*.whl --title "Release vX.Y.Z" --generate-notes
```

No primeiro upload o projeto ainda não existe, então o token precisa ser da conta inteira; depois troque por um token de escopo do projeto e apague o antigo. Nunca guarde o token no repositório.

## Rollback

- **PyPI:** não dá para reenviar a mesma versão. Em pypi.org > Manage > Releases, faça *yank* da versão ruim (quem fixou `==X.Y.Z` ainda instala; quem não fixou deixa de receber) e publique `X.Y.(Z+1)` corrigida. O botão do widget instala a versão exata do widget, então a loja e o PyPI precisam andar juntos.
- **Loja KDE:** em store.kde.org, despublique o produto ou volte o arquivo para o `.plasmoid` anterior.
- **GitHub Release:** `gh release delete vX.Y.Z` e, se necessário, apague a tag. Isso não desfaz o PyPI.
