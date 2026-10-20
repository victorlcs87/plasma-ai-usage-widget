# Arquitetura Desacoplada: Coletor Python e Plasmoid QML (Plasma 6)

Contexto: O widget para KDE Plasma 6 necessita consultar arquivos SQLite locais, logs e endpoints de autenticacao de multiplos agentes de IA (Claude, Codex e Gemini).
Decisao: Separar a arquitetura em um Coletor CLI em Python (`ai-usage-collector`) e um Plasmoid QML leve para o KDE Plasma 6, comunicando-se por meio de um arquivo de estado estruturado em JSON (`~/.cache/plasma-ai-usage/status.json`).
Motivo: Evitar bloqueio de threads graficas no motor QML/JS do Plasma 6, facilitar testes automatizados independentes e simplificar a manutencao e extensao de novos extratores de agentes.
