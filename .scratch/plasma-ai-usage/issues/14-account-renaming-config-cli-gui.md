## Parent

Closes part of #2

## What to build

O usuário pode renomear qualquer conta cadastrada (capturada automaticamente ou adicionada manualmente) sem precisar excluí-la e recadastrá-la. A funcionalidade atravessa todas as camadas:

**Config**: Função pura `rename_account_in_config(config_data, provider, account_id, new_label)` que altera exclusivamente os campos `label` e `name` da conta, preservando `id`, `credential_path`, perfil isolado e todas as demais propriedades. Retorna `(updated_config, was_renamed)`.

**CLI**: Novo comando `ai-usage-collector --rename-account <provider> <account_id> --label <novo_nome>` que invoca a função acima, persiste atomicamente o `config.json` com `0600`, executa `collect_and_save()` para atualizar o `status.json`, e imprime confirmação em stdout. Compatível com `--status` para emitir o JSON atualizado.

**GUI (configGeneral.qml)**: Botão de edição (ícone `document-edit` / lápis) ao lado do botão de exclusão em cada item da lista de contas. Ao clicar, abre um diálogo modal nativo (sem `standardButtons`) com `QQC2.TextField` pré-preenchido com o nome atual e botões `Salvar` / `Cancelar`. O `Salvar` executa `--rename-account` assincronamente via `Plasma5Support.DataSource`, exibe feedback via `Kirigami.InlineMessage` e recarrega a lista. Validação: nome não pode ser vazio.

## Acceptance criteria

- [x] Função `rename_account_in_config()` altera `label` e `name` corretamente, preservando `id` e demais campos.
- [x] Função retorna `(config, False)` se a conta não for encontrada.
- [x] CLI `--rename-account claude <id> --label "Novo Nome"` altera o `config.json` e retorna exit code 0.
- [x] CLI rejeita label vazia com mensagem de erro e exit code 1.
- [x] CLI com `--status` emite JSON atualizado contendo o novo nome.
- [x] QML contém botão `document-edit` em cada item da lista de contas.
- [x] QML contém diálogo de renomeação com `QQC2.TextField` e botões `Salvar`/`Cancelar`, sem `standardButtons`.
- [x] QML invoca `--rename-account` via `DataSource` e recarrega a lista após sucesso.
- [x] Todos os testes existentes continuam passando.

## Blocked by

None (can start immediately)
