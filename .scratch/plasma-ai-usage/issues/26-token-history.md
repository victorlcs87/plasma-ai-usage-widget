# 26: Histórico de Tokens com exportação

**Parent:** #8

**What to build:** O coletor mantém o Histórico de Tokens: agregado diário por provedor, Conta e modelo, com retenção de 400 dias, lendo logs locais de forma incremental. O contrato expõe tokens de hoje/semana/mês e séries de 30 dias (diário), 3 meses (semanal) e 12 meses (mensal); o card atual mostra os totais e um gráfico simples. A CLI exporta o histórico em CSV ou JSON.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Leitura incremental: reexecutar não duplica contagens.
- [ ] Dias além de 400 são descartados; dados persistem mesmo se os logs do CLI forem apagados.
- [ ] Exportação CSV e JSON pela CLI.
- [ ] Card exibe hoje/semana/mês e gráfico.
- [ ] Testes pela CLI com logs simulados.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
