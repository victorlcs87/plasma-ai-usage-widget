# Suporte a Multi-Contas e Janelas Nativas por Provedor

Contexto: O usuario possui multiplas contas cadastradas para os mesmos agentes (Claude, Codex e Gemini) e cada plataforma opera com regras de cotas temporais fundamentalmente distintas (ex.: janela de 5 horas no Claude, janela de 3 horas no Codex e cotas diarias/semanais no Gemini).
Decisao: O modelo de dominio e a interface suportarao multiplas contas por agente (com capacidade de adicao e remocao via UI e configuracao) e exibirao fielmente as janelas nativas de cada provedor, com suas respectivas contagens regressivas para liberacao de cota.
Motivo: Evitar perda de informacao causada por unificacoes artificiais de metricas e permitir que o usuario alterne ou acompanhe individualmente o consumo e os convites de todas as suas contas ativas.
