# 24: Ritmo de Uso, Previsão de Esgotamento e nível de alerta

**Parent:** #8

**What to build:** O coletor calcula, por janela, o Ritmo de Uso (consumido × decorrido), a Previsão de Esgotamento (Janela Nativa: amostras dos últimos 30 min; semanal: últimas 24 h, guardadas em cache) e o nível de alerta (`normal`/`warning`/`critical`) no modo escolhido: por ritmo (padrão) ou limiar fixo 70/90. Os cards atuais exibem previsão e colorem pelo nível.

**Blocked by:** 22 (#13), 23 (#14)

**Status:** ready-for-agent

- [ ] Contrato expõe ritmo, previsão e nível por janela.
- [ ] Modo ritmo: `warning` quando o ritmo esgota antes do Tempo de Liberação.
- [ ] Modo limiar: 70/90 configuráveis.
- [ ] Sem amostras suficientes ⇒ sem previsão (não inventa valor).
- [ ] Testes pela CLI com séries de amostras.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
