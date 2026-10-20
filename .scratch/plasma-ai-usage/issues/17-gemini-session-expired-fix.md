## Parent

Closes part of #2

## What to build

Identificação e correção do bug de falso positivo de sessão expirada do Gemini no widget:

1. **Causa Raiz Identificada**:
   - `~/.gemini/oauth_creds.json` continha um `access_token` antigo com `expiry_date` estático ultrapassado.
   - O extrator `src/ai_usage_collector/extractors/gemini.py` verificava esse timestamp estático e marcava `health.status = "session_expired"`.
   - O ambiente do usuário (`agy` / Antigravity no KDE) armazena o token ativo e renovado no chaveiro nativo do KDE (`secret-tool lookup service gemini username antigravity`).
   - A chamada à API oficial da Google (`retrieveUserQuotaSummary`) com o token do chaveiro retorna `HTTP 200` com sucesso e cotas reais, mas o extrator não atualizava o `health.status` para `"valid"`.

2. **Correções**:
   - No `discovery.py` e `extractors/gemini.py`, priorizar a verificação do token ativo no chaveiro do sistema (`secret-tool`).
   - Se a chamada à API oficial da Google responder com sucesso (`HTTP 200`), forçar `health.status = "valid"`, `message = "Credencial Gemini ativa detectada via API oficial"` e enriquecer os metadados.
   - Sincronizar o token ativo obtido do chaveiro para o arquivo `~/.gemini/oauth_creds.json` de forma atômica e segura (`0600`), garantindo que tanto o chaveiro quanto o arquivo em disco fiquem atualizados e consistentes.
   - Tratar a presença de `refresh_token` como indicativo de sessão renovável, não marcando `session_expired` preventivamente se um refresh token ou chaveiro estiver presente.

## Acceptance criteria

- [x] `extractors/gemini.py` atualiza `health.status = "valid"` quando a chamada à API oficial de cotas tem sucesso com o token do chaveiro.
- [x] `discovery.py` verifica o chaveiro (`secret-tool`) como fonte prioritária de credenciais ativas do Gemini.
- [x] O token ativo do chaveiro é sincronizado para `~/.gemini/oauth_creds.json` com permissões `0600`.
- [x] `ai-usage-collector --status` exibe `status: "valid"` e cotas reais para o Gemini sem erro de `session_expired`.
- [x] Testes unitários dedicados em `tests/test_gemini_extractor.py` e `tests/test_discovery.py` cobrindo o cenário de token do chaveiro ativo sobrepondo arquivo com timestamp antigo.
- [x] Todos os testes passando (145+ testes).

## Blocked by

None (can start immediately)
