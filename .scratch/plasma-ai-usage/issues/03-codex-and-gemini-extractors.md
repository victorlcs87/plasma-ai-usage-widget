# 03: Extratores Nativos Codex e Gemini (Janelas Nativas 3h/Diaria/Semanal, Liberacao e Convites)

**What to build:** Os modulos extratores para Codex (OpenAI) e Gemini (Google), processando os bancos de dados SQLite locais (`~/.codex/thread_history_1.sqlite` e `~/.gemini/antigravity-cli/conversation_summaries.db`), calculando suas janelas nativas de cota (janela de 3h e semanal no Codex; diaria e semanal no Gemini), indicando tempo de liberacao e gerenciando badges de convites de teste gratuito.

**Blocked by:** 02: Extrator Nativo Claude (Janela de 5h, Semanal, Liberacao e Convites)

**Status:** in-review

- [x] Extracao de turnos e consumo do Codex na janela nativa de 3 horas e agregacao semanal a partir do SQLite local.
- [x] Calculo de tempo de liberacao para o Codex.
- [x] Extracao do historico de conversas e turnos do Gemini para agregacao diaria e semanal.
- [x] Calculo do proximo ciclo de renovacao de cota para o Gemini.
- [x] Tratamento de convites de teste gratuito para Codex e Gemini com suporte a fallback manual no `config.json`.
- [x] Consolidacao dos tres provedores (Claude, Codex, Gemini) simultaneamente no arquivo de contrato `status.json`.
- [x] Testes automatizados cobrindo os extratores de Codex e Gemini com fixtures isoladas.
