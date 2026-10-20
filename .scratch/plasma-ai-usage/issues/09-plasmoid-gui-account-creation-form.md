# 09: Formulario Grafico de Adicao de Contas no KDE Plasma (`configGeneral.qml`)

**What to build:** Um formulario grafico intuitivo e nativo integrado a janela de configuracoes do Plasmoid (`configGeneral.qml`) que permite cadastrar novas contas selecionando o provedor, digitando o apelido da conta, definindo o caminho da pasta/credencial e informando opcionalmente o link de convite, acionando a criacao assincrona no backend e atualizando os cards na tela instantaneamente.

**Blocked by:** 08: Reformulacao Visual dos Cards no Plasmoid com Medidores Simetricos Horario/Semanal

**Status:** completed

- [x] Secao expansivel de cadastro "+ Adicionar Nova Conta" em `configGeneral.qml`.
- [x] ComboBox para selecao do provedor (`Claude`, `Codex`, `Gemini`) com estilizacao visual condizente.
- [x] Campos de texto para Apelido/Label da conta, caminho das credenciais e URL de convite opcional.
- [x] Botao auxiliar para sugerir/preencher o caminho padrao do provedor selecionado.
- [x] Botao "Salvar Conta" que invoca assincronamente `ai-usage-collector --add-account` via `Plasma5Support.DataSource` com `shellQuote` e `"$@"`.
- [x] Exibicao de mensagem em linha (`Kirigami.InlineMessage`) com feedback de sucesso ou erro.
- [x] Atualizacao imediata da lista de contas e sincronizacao automatica do widget no desktop.
- [x] Reinstalacao e validacao do pacote Plasmoid com `kpackagetool6`.
- [x] Bateria de testes automatizados cobrindo a interacao do formulario e bindings QML.
