## Parent

Closes part of #2

## What to build

Implementar a interface de alternância de conta ativa e visualização nos cards do Plasmoid (`AccountCard.qml`):

1. **Indicador de Conta Ativa**:
   - Exibir badge `[✓ Ativa no CLI]` destacado ao lado do badge de saúde quando `accountData.isActive === true`.
2. **Botão de Ativação Rápida**:
   - Para contas inativas (`accountData.isActive !== true`) e com saúde válida (`healthStatus === "valid"`), exibir botão de ação rápida `[⚡ Ativar no Sistema]`.
   - Ao ser clicado, o botão aciona `ai-usage-collector --switch-account <provider> <account_id>` assincronamente via `Plasma5Support.DataSource`.
   - Durante a operação, exibir estado ocupado (loading/disabled) e feedback visual imediato.
   - Ao concluir, o widget atualiza seu status (`refreshCollector()` ou recarga de `status.json`), fazendo o badge `[✓ Ativa no CLI]` migrar instantaneamente para a nova conta.

## Acceptance criteria

- [x] `AccountCard.qml` lê a propriedade `accountData.isActive`.
- [x] Badge `[✓ Ativa no CLI]` é visível exclusivamente na conta ativa.
- [x] Botão `[⚡ Ativar no Sistema]` é exibido nas contas inativas com saúde válida.
- [x] Clique no botão invoca `ai-usage-collector --switch-account` com argumentos devidamente sanitizados via `shellQuote()`.
- [x] Sucesso da troca dispara atualização visual imediata no Plasmoid sem exigir recarga manual do usuário.
- [x] Teste em `test_plasmoid_interactive.py` valida a presença do badge de conta ativa e do botão de switch.
- [x] Suíte completa de testes passando (145+ testes).

## Blocked by

- #5 (Ticket 15)
