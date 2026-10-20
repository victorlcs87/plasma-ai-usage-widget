# 12: Assistente de Login no Terminal e Ações de Captura na GUI do Plasmoid

**What to build:** Implementação do comando `--interactive-login <provider>` que dispara um emulador de terminal (Konsole) com variáveis de ambiente isoladas (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) para autenticar nova conta sem sobrescrever a conta principal, integração dos botões de ação na GUI ("Capturar Login Atual do CLI" e "Fazer Login no Terminal..."), reorganização do formulário gráfico recolhendo campos técnicos sob opções avançadas e atualização imediata do desktop.

**Blocked by:** 10: Correção Visual do Seletor ComboBox no Plasmoid, 11: Backend de Captura de Sessão Ativa (`--capture-current`) e Isolamento de Perfis

**Status:** ready-for-agent

- [ ] Comando CLI `ai-usage-collector --interactive-login <provider>` implementado, configurando pastas isoladas e executando `claude auth login`, `codex login` ou `agy`.
- [ ] Detecção e suporte a emuladores de terminal (`konsole -e`, `x-terminal-emulator`, etc.) com passagem segura de comandos.
- [ ] Monitoramento do término da autenticação e registro automático do perfil resultante com permissões `0600`.
- [ ] Inclusão dos botões de ação rápida no formulário de `configGeneral.qml`: "Capturar Login Atual do CLI" e "Fazer Login no Terminal...".
- [ ] Realocação do campo "Caminho das Credenciais" para uma seção retrátil "Configuração Avançada (Opcional)", dispensando digitação manual de caminhos.
- [ ] Invocação assíncrona segura no Plasmoid via `Plasma5Support.DataSource` com `shellQuote`.
- [ ] Feedback visual claro em `Kirigami.InlineMessage` com o e-mail/identidade da conta adicionada e atualização imediata do desktop.
- [ ] Revalidação do pacote Plasmoid com `kpackagetool6` e suíte completa de testes no pytest.
