# Plasma AI Usage Collector

Coletor de métricas de uso e cotas de agentes de IA (Claude, Codex e Gemini) para o widget nativo KDE Plasma 6.

## Waybar

`ai-usage-collector --waybar` imprime uma linha JSON (`text`, `tooltip`, `class`, `alt` e, quando há nível, `percentage`) a partir do cache, sem consultar provedores nem a rede, sempre com exit code 0. Mantenha o cache atualizado com `ai-usage-collector --refresh` (ou pelo Plasmoid).

A classe é o pior nível de alerta entre as Contas Ativas no Sistema (contas inativas não contam): `normal`, `warning` ou `critical`. Sem nível confiável a classe é neutra: `stale` (dados desatualizados, erro ou pausa por HTTP 429) ou `unknown` (sem cache, cache inválido ou nenhuma conta ativa; texto `—`). Nunca é mostrado um 0% inventado. Rótulos de conta são escapados para o Pango markup do Waybar.

```jsonc
// ~/.config/waybar/config.jsonc
"custom/ai-usage": {
    "exec": "ai-usage-collector --waybar",
    "return-type": "json",
    "interval": 30,
    "tooltip": true
}
```

```css
/* ~/.config/waybar/style.css */
#custom-ai-usage.warning { color: #f9e2af; }
#custom-ai-usage.critical { color: #f38ba8; }
#custom-ai-usage.stale, #custom-ai-usage.unknown { opacity: 0.6; }
```
