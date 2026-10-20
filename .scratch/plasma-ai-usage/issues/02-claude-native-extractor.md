# 02: Extrator Nativo Claude (Janela de 5h, Semanal, Liberacao e Convites)

**What to build:** O modulo extrator dedicado ao Claude Code / Anthropic que le os artefatos locais (`stats-cache.json`, logs de sessao em `history.jsonl` e credenciais OAuth), computa o consumo da janela nativa de 5 horas e da janela semanal, calcula a capacidade disponivel e o tempo exato de liberacao da cota (com contagem regressiva), alem de expor o status dos convites de teste gratuito com suporte a link manual no `config.json`.

**Blocked by:** 01: Core CLI Coletor, Contrato de Estado e Descoberta Automatica

**Status:** closed

- [x] Extracao correta do consumo de tokens/mensagens na janela movel de 5 horas a partir dos dados locais do Claude.
- [x] Extracao do consumo acumulado na janela semanal (ultimos 7 dias).
- [x] Calculo preciso da capacidade restante e do timestamp de liberacao da cota de 5h com diferenca em segundos/minutos.
- [x] Captura de convites de teste gratuito com fallback funcional para URLs estaticas configuradas no `config.json`.
- [x] Atualizacao das secoes do Claude no `status.json` com campos consistentes e tratamento gracioso de erros de leitura/sessao expirada.
- [x] Testes automatizados no seam do extrator com fixtures reais e sinteticas de dados do Claude.
