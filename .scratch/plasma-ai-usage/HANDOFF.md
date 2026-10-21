# Handoff — Spec 05 (issue #8), parada em 2026-10-21

Sessão anterior: `alinhar-visual-codenotch-e-contas`. Leia antes: `CLAUDE.md` global, `CONTEXT.md`, `docs/specs/05-*.md`, ADRs 0007/0008/0009 e os tickets em `.scratch/plasma-ai-usage/issues/18..42`.

## Autorizações do usuário (válidas para quem continuar)
- Implementação automática de TODOS os tickets, por subagentes de contexto limpo, sem pedir confirmação por ticket.
- Ao final, o usuário autorizou **fazer o merge e os deploys manuais direto** (o GitHub Actions está parado por cobrança — não depender de CI/gh actions). Antes do merge cumprir os gates: suíte completa, `/code-review` final em contexto limpo, `/security-review`, `impeccable` nos tickets visuais (UI).
- Comunicação sempre em PT-BR. Python só em venv local (`.venv`), nunca global.

## Estado das branches (push feito; base: 280e8b8 = main antiga)
| Branch remota | O que tem | Estado |
|---|---|---|
| `feat/codenotch-v2` | docs (spec 05, ADRs, glossário, tickets 18-42) + **28** (detalhes Claude/Codex) + **26** (histórico de tokens) + **18** (identidade Claude, até commit 4ef29dd) | suíte **226 passed, 1 skipped** |
| `feat/ticket-22-native-window-duration` | **22** (duração da Janela Nativa), commit b60d124, 217 testes na worktree | revisado 1x (aprovado c/ ressalvas), achados M1-M3/B1-B2 corrigidos; **sem re-revisão**; NÃO integrado |
| `feat/ticket-23-periodic-refresh` | **23** (atualização periódica), commit 0ac5819, 241 testes | revisado 1x (reprovado), todos os achados corrigidos; **2ª revisão interrompida**; NÃO integrado |

`origin/main` avançou (77dfdb4, release automation) — rebasear/mesclar antes do PR final. Existe `feat/release-automation` com `.github/workflows/release.yml` (de outra sessão, não nossa): achado de segurança pendente — fixar `softprops/action-gh-release` em SHA e `permissions` no nível do job.

## Ticket 18 (identidade Claude) — NÃO aprovado ainda
Passou por 2 revisões independentes que reprovaram; terceira rodada de correções está em `feat/codenotch-v2` (merge 63daf48) e a **3ª revisão foi interrompida** (nenhum veredito). Refaça uma revisão independente em contexto limpo. Foco: perda/corrupção de credencial; precedência token-exato > identidade > assinatura; não propagar identidade que já pertence a outra conta; não fundir identidade recém-atribuída com refresh tokens divergentes; `config_lock`; layout real do usuário (entrada `default` → caminho do sistema, `claude-signatus`, `claude-cga` sem `.claude.json`, órfão `claude-pro` com tokens do signatus) nas variantes `oauthAccount` coerente (cga) e defasado (signatus); Codex/Gemini sem regressão. Limitações conhecidas estão em `docs/adr/0008` (Consequences).

**NÃO rodar o coletor novo contra os dados reais do usuário (`~/.claude`, `~/.config/plasma-ai-usage`) até o 18 ser aprovado** — risco de perda de credencial. Estado real hoje: 3 contas Claude (default→caminho do sistema "Claude (Pro)", `claude-signatus`, `claude-cga`) + órfão `claude-pro`; sistema == tokens da CGA; `oauthAccount` == CGA.

## Ordem sugerida para continuar
1. Revisar 18 (independente) → corrigir → aprovar.
2. Integrar 22 em `feat/codenotch-v2` (conflito esperado só em `contract.py`/`CONTRACT_VERSION`; rode a suíte). Re-revisar 22 se mudar algo.
3. Lançar em paralelo (worktrees): **19** (Codex), **20** (Gemini), **21** (órfãos) — todos usam `identity.py` (interface de adaptador por provedor; só o Claude existe).
4. 2ª revisão do 23 → integrar (conflitos esperados: `contract.py`, `tests/conftest.py`, QML `AccountCard.qml`).
5. Depois: 24 (ritmo/previsão; bloq. por 22,23) → 25, 27 → 29, 30 → 31 (notch compacto) → 32, 33, 34, 35→36, 37, 38, 39 → 40 (i18n) → 42 (histórico por identidade; bloq. 18, 19, 26) → 41 (notch flutuante, opcional, por último).
Grafo completo de dependências em cada ticket (`Blocked by`) e nas issues #9..#33 do GitHub (sub-issues da #8; o 42 é a #33).

## Método que funcionou
Um subagente por ticket, em worktree isolada (`isolation: worktree`), que deve começar com `git reset --hard feat/codenotch-v2` (a worktree nasce de base antiga) e usar venv próprio (`python -m venv .venv && .venv/bin/pip install -e . pytest` — o editable do repo principal aponta para outro código). Depois: revisão independente em agente novo (relatório por severidade), correção pelo mesmo agente, nova revisão, integração em worktree `integration`. Subagentes não fazem push/PR/merge. Hook local reescreve `git`: usar `/usr/bin/git` para commits.

## Pontos de atenção
- Nomes de campos de duração do Codex (`limit_window_seconds`, `window_minutes`) vieram de memória do agente, não de resposta real; se errados, cai no fallback 3h sem quebrar. Valide só em leitura contra a conta Codex do usuário.
- Caso real que motivou o 23: API de uso do Claude respondeu 429 (retry-after 226 s) para a CGA e o widget mostrava 0% falso. O 23 corrige (por janela → "—"/"Sem dados").
- Atribuição do Histórico de Tokens (26) vai para a conta ativa no momento da leitura até o ticket 42 (por identidade) existir.
- `extra_usage` do Claude foi assumido em centavos de dólar (ticket 28) — não confirmado com conta real.
- Verificação visual (plasmoidviewer) e `impeccable` ainda não foram feitos em nada; ficam para os tickets de UI e o gate do PR.
- O stash antigo ("wip: codenotch…") foi restaurado e commitado; não há stash pendente nossa.
