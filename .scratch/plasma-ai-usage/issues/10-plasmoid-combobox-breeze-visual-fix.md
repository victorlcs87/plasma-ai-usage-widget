# 10: Correção Visual do Seletor ComboBox no Plasmoid

**What to build:** Correção completa da renderização do seletor de provedores em `configGeneral.qml`, substituindo o componente com estilização customizada defeituosa por `PlasmaComponents3.ComboBox` nativo, eliminando a sobreposição de textos ("Claudede") e garantindo a exibição nítida dos nomes de todos os provedores acompanhados de seus indicadores visuais oficiais, tanto no estado fechado quanto na lista suspensa do tema Breeze.

**Blocked by:** None (can start immediately)

**Status:** completed

- [x] Remoção da sobreposição de textos ("Claudede") no seletor de provedor em `configGeneral.qml`.
- [x] Uso do componente nativo `PlasmaComponents3.ComboBox` integrado perfeitamente ao tema Breeze e Kirigami.
- [x] Exibição clara e legível dos nomes de todos os provedores (`Claude`, `Codex`, `Gemini`) tanto no campo fechado quanto na lista suspensa do popup.
- [x] Preservação dos indicadores visuais coloridos oficiais de cada IA sem interferir no layout de texto do KDE Plasma.
- [x] Validação sintática QML com `qml6` e atualização do pacote com `kpackagetool6`.
- [x] Testes automatizados em pytest validando os atributos, bindings e propriedades do ComboBox.
