# 06: Acoes Interativas no Plasmoid (Atualizacao Sob Demanda, Copiar Convite e Remocao na GUI)

**What to build:** O conjunto completo de acoes interativas no Plasmoid: botao "Atualizar agora" com animacao de carregamento assincrono (spinner) e registro de timestamp da ultima verificacao; botao de 1 clique para copiar o link do convite de teste gratuito para o Clipboard do KDE com aviso visual; e janela nativa de configuracoes (`configGeneral.qml`) para visualizar contas e remove-las diretamente com clique no icone de lixeira.

**Blocked by:** 05: Estrutura do Plasmoid KDE Plasma 6 e Renderizacao em Cards (Desktop e Painel)

**Status:** ready-for-agent

- [ ] Botao "Atualizar agora" no cabecalho do Plasmoid disparando a execucao assincrona do coletor Python sem travar a interface grafica.
- [ ] Indicador visual de carregamento (spinner) ativo durante a execucao da atualizacao.
- [ ] Carimbo de data/hora atualizado e formatado (ex.: "Atualizado hoje as 09:45").
- [ ] Acao de copiar link de convite integrada a Area de Transferencia do KDE (Clipboard) com feedback visual imediato ao usuario.
- [ ] Janela de configuracoes do Plasmoid (`configGeneral.qml`) listando as contas ativas com botao de exclusao (icone de lixeira).
- [ ] Exclusao pela interface grafica dispara internamente a remocao no coletor e recarrega o estado do widget imediatamente.
- [ ] Teste de ponta a ponta validando o fluxo de interacao e feedback visual no desktop.
