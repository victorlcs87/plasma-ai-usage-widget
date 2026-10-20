# Spec 04: Alternância de Conta Ativa, Renomeação e Correção de Diálogos

## Problem Statement

O usuário possui múltiplas contas cadastradas para os provedores Claude, Codex e Gemini, cada uma com perfil isolado em disco. No entanto, três problemas impedem o uso fluido do widget:

1. **Sem alternância rápida de conta**: Quando a cota de uma conta esgota no terminal, o usuário precisa abrir o navegador e refazer o login OAuth para usar outra conta. Ele quer simplesmente clicar em outra conta com cota disponível no widget e continuar trabalhando no terminal instantaneamente.

2. **Sem renomeação**: Contas capturadas automaticamente recebem nomes genéricos (ex.: `Claude (pro)`, `Codex (user@...)`) que o usuário não pode alterar depois sem remover e recadastrar.

3. **Sobreposição visual em diálogos**: O diálogo de confirmação de exclusão de conta renderiza dois conjuntos de botões sobrepostos — os automáticos do `standardButtons` e os customizados do layout interno — tornando a interface ilegível.

## Solution

1. **Alternância direta de conta ativa no sistema** com um clique no widget desktop: o coletor CLI sincroniza a credencial ativa de volta para seu perfil, aplica a credencial da nova conta nos caminhos padrão do sistema, e atualiza o status. O terminal passa a usar a nova conta imediatamente.

2. **Renomeação rápida** de qualquer conta cadastrada via botão de edição no widget e/ou via CLI, alterando apenas o rótulo amigável sem tocar em identificadores ou credenciais.

3. **Correção dos diálogos modais**: remoção de `standardButtons` automáticos para eliminar duplicidades visuais no tema Breeze.

## User Stories

1. As a KDE Plasma user, I want to see which account is currently active in the system CLI for each provider, so that I know which identity my terminal is using.

2. As a KDE Plasma user, I want to activate a different account with a single click on its card in the widget popup, so that I can switch to one with available quota without opening a browser.

3. As a KDE Plasma user, I want the system to back up the current active session's credentials before switching, so that renewed tokens from my previous session are not lost.

4. As a KDE Plasma user, I want the widget to show a clear visual indicator (`✓ Ativa no CLI`) on the currently active account card, so that I can instantly identify it.

5. As a KDE Plasma user, I want an activation button (`⚡ Ativar no Sistema`) on inactive account cards, so that switching is discoverable and obvious.

6. As a KDE Plasma user, I want to rename an account from the configuration dialog, so that I can give meaningful names to accounts captured automatically.

7. As a KDE Plasma user, I want the rename operation to preserve the internal account ID and credential paths, so that nothing breaks.

8. As a KDE Plasma user, I want a rename button (pencil icon) next to each account in the config dialog's account list, so that renaming is easy to find.

9. As a KDE Plasma user, I want the rename dialog to show the current name pre-filled, so that I can edit it quickly.

10. As a CLI user, I want `ai-usage-collector --switch-account <provider> <account_id>` to activate a saved account in the system, so that I can script account switching.

11. As a CLI user, I want `ai-usage-collector --rename-account <provider> <account_id> --label <new_name>` to update the account label, so that I can manage names without the GUI.

12. As a KDE Plasma user, I want the delete confirmation dialog to display its buttons without visual overlap, so that I can read and click them properly.

13. As a KDE Plasma user, I want automatic detection of the currently active account on each status refresh, so that the active indicator stays accurate even if I logged in manually via terminal.

14. As a KDE Plasma user, I want the switch operation to update the widget display immediately after activation, so that I see the new active state without manually refreshing.

15. As a KDE Plasma user, I want the switch to work for all three providers (Claude, Codex, Gemini), each using its provider-specific credential mechanism (file copy for Claude/Codex, file copy or keyring update for Gemini).

16. As a CLI user, I want the switch command to fail gracefully with a clear error message if the target account's profile directory is missing or corrupted.

17. As a KDE Plasma user, I want the rename dialog to validate that the new name is not empty before saving.

## Implementation Decisions

### CLI — New Commands

- **`--switch-account <provider> <account_id>`**: New CLI command that:
  1. Loads `config.json` and locates the target account's profile directory.
  2. Calls `backup_active_to_profile()` to sync the current system credentials back to the matching profile (bidirectional sync).
  3. Calls `activate_profile_to_system()` to copy the target profile's credentials to the system default paths.
  4. Updates `config.json` with `"active": true` on the target account and `"active": false` on all other accounts of the same provider.
  5. Triggers a `collect_and_save()` refresh to regenerate `status.json`.

- **`--rename-account <provider> <account_id>`**: New CLI command that updates `label` and `name` fields in `config.json` using the value from `--label`, then triggers `collect_and_save()`.

### Config Module — New Functions

- `rename_account_in_config(config_data, provider, account_id, new_label)`: Pure function that mutates `label` and `name` fields for the matching account. Returns `(updated_config, was_renamed)`.

- `set_active_account_in_config(config_data, provider, account_id)`: Pure function that sets `"active": true` on the target and `"active": false` on siblings.

### Capture Module — New Functions

- `backup_active_to_profile(provider, config_path)`: Inspects system-default credentials, finds which profile they correspond to by comparing credential content or identity, and syncs back any updated files.

- `activate_profile_to_system(provider, account_id, config_path)`: Copies profile credentials to system default paths (`~/.claude/.credentials.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`) with `save_secure_json` / atomic copy and `0600` permissions.

### Credential Mapping per Provider

| Provider | System Default Path | Profile Path | Mechanism |
|----------|-------------------|-------------|-----------|
| Claude   | `~/.claude/.credentials.json` | `profiles/<slug>/.credentials.json` | Atomic file copy |
| Codex    | `~/.codex/auth.json` | `profiles/<slug>/auth.json` | Atomic file copy |
| Gemini   | `~/.gemini/oauth_creds.json` | `profiles/<slug>/oauth_creds.json` | Atomic file copy (fallback: `secret-tool store` for keyring) |

### Collector — Active Account Detection

- During `collect_and_save()`, for each provider, compare the system-default credentials against each registered profile's credentials. Mark the matching account with `isActive: true` in the `status.json` output. If no match is found (e.g., the user logged in with an unregistered account), no account is marked active.

### Contract — New Field

- Each account object in `status.json` gains an `isActive` boolean field (`true`/`false`/absent). The `build_agent_account_status()` function accepts an optional `is_active` parameter.

### QML — AccountCard Changes

- New property `isActive` read from `accountData.isActive`.
- Badge `✓ Ativa no CLI` displayed next to the health badge when `isActive === true`.
- Button `⚡ Ativar no Sistema` displayed when `isActive !== true` and `healthStatus === "valid"`, calling `ai-usage-collector --switch-account <provider> <account_id>` via a new `Plasma5Support.DataSource`.

### QML — configGeneral Changes

- **Rename button**: New `PlasmaComponents3.Button` with icon `document-edit` in each account list item's `RowLayout`, next to the delete button.
- **Rename dialog**: New `QQC2.Dialog` with a `QQC2.TextField` (pre-filled with current name) and `Salvar` / `Cancelar` buttons. No `standardButtons`. Calls `ai-usage-collector --rename-account <provider> <account_id> --label <new_name>` via a new `Plasma5Support.DataSource`.
- **Confirm dialog fix**: Remove `standardButtons: QQC2.Dialog.Cancel` from the existing `confirmDialog`. The custom buttons in the `RowLayout` are sufficient and will no longer collide.

## Testing Decisions

### What Makes a Good Test

Tests verify external behavior through public interfaces — the CLI `main()` function, the config module's pure functions, and QML source text structure. Tests do not verify internal implementation details like private function signatures or intermediate state.

### Testing Seams

1. **CLI `main()` function** (existing seam): All new commands (`--switch-account`, `--rename-account`) are tested by calling `main([...args...])` and asserting on exit code, stdout/stderr output, and resulting file system state. Prior art: `test_cli_capture_current.py`, `test_cli_interactive_login.py`, `test_cli_add_account.py`, `test_cli_remove_account.py`.

2. **Config module pure functions** (existing seam): `rename_account_in_config()` and `set_active_account_in_config()` are tested as pure dict-in/dict-out functions. Prior art: `test_config.py`, `test_account_management.py`.

3. **QML source text analysis** (existing seam): Validate that `AccountCard.qml` contains the `isActive` badge and switch button, that `configGeneral.qml` contains the rename button and dialog, and that `confirmDialog` no longer uses `standardButtons`. Prior art: `test_plasmoid_interactive.py`, `test_plasmoid_packaging.py`.

### Modules Tested

- **`test_cli_switch_account.py`** (new): Tests for `--switch-account` covering success, backup before switch, missing profile, invalid provider, `--status` output, and idempotent re-activation.
- **`test_cli_rename_account.py`** (new): Tests for `--rename-account` covering success, empty label rejection, nonexistent account, ID preservation, and `--status` output.
- **`test_config.py`** (extended): Unit tests for `rename_account_in_config()` and `set_active_account_in_config()`.
- **`test_plasmoid_interactive.py`** (extended): QML source analysis for rename dialog, switch button, active badge, and `confirmDialog` fix.

## Out of Scope

- **Automatic switching on quota exhaustion**: The widget does not auto-switch accounts when a quota runs out. The user must click the activation button manually.
- **Cross-provider switching**: The switch command operates within a single provider. You cannot "switch" from a Claude account to a Codex account.
- **Keyring write for Gemini**: If the active Gemini credentials are stored exclusively in the Secret Service keyring (not a file), the switch command will copy them to a file-based profile. Writing back to the keyring via `secret-tool store` is a best-effort fallback, not a guaranteed feature.
- **Account reordering or prioritization**: The order of accounts in the widget is determined by their order in `config.json` and is not changeable in this spec.
- **PR merge**: The deliverable is a PR ready for merge, not the merge itself.

## Further Notes

- The bidirectional sync (`backup_active_to_profile`) is critical for Claude and Codex, where the CLI can silently refresh OAuth tokens during use. Without backing up before switching, the user could lose a valid refreshed token and be forced to re-authenticate.
- All file operations use `save_secure_json` (atomic `mkstemp` + `os.replace` + `chmod 0600`) to prevent partial writes or permission issues.
- The `isActive` detection during `collect_and_save()` compares credential file contents (JSON equality or JWT subject/email match), not file modification timestamps, to avoid false negatives from backup/restore operations that preserve content but change mtime.
