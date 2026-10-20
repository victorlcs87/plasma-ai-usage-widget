# 05: Estrutura do Plasmoid KDE Plasma 6 e Renderizacao em Cards (Desktop e Painel)

**What to build:** O pacote Plasmoid nativo compativel com KDE Plasma 6 / Qt 6 que le o `status.json` e renderiza as metricas de forma responsiva tanto no Painel (icone minimalista com flyout popup) quanto solto na Area de Trabalho (cards com abas para Claude, Codex e Gemini, barras de progresso coloridas por limiares de uso, capacidades disponiveis e contadores de tempo de liberacao).

**Blocked by:** 04: Gestao Multi-Conta e Remocao de Contas via CLI e Configuracao

**Status:** in-review

- [x] Pacote Plasmoid valido com manifesto `metadata.json` compativel com KDE Plasma 6 (`KPackage/GenericQML` e tipo `Plasma/Applet`).
- [x] Implementacao de visualizacao responsiva baseada em `Plasmoid.formFactor` (Painel com popup vs Desktop com exibicao expandida).
- [x] Organizacao visual por abas ou secoes retrateis para Claude, Codex e Gemini.
- [x] Renderizacao individual de cada conta cadastrada com seu apelido amigavel e status de conexao.
- [x] Barras de progresso das janenas nativas com dinamica de cores (verde para < 70%, amarelo para 70-90% e vermelho para > 90%).
- [x] Exibicao da capacidade restante e do tempo de liberacao da cota em contagem regressiva clara.
- [x] Badge visual de convites de teste gratuito disponiveis por conta.
- [x] Script de instalacao/atualizacao local do Plasmoid via `kpackagetool6`.
- [x] Validacao estrutural e sintatica do pacote Plasmoid.
