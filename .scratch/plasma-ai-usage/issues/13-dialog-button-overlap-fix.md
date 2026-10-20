## Parent

Closes part of #2

## What to build

O diálogo de confirmação de exclusão de conta (`confirmDialog`) em `configGeneral.qml` atualmente renderiza dois conjuntos de botões sobrepostos: os automáticos gerados pelo `standardButtons: QQC2.Dialog.Cancel` e os customizados do `RowLayout` interno (`Cancelar` + `Remover Conta`). O resultado é uma sobreposição visual ilegível no tema Breeze.

A correção deve remover a propriedade `standardButtons` do diálogo (definindo `QQC2.Dialog.NoButton` ou removendo a linha), mantendo exclusivamente os botões customizados com espaçamento, padding e alinhamento limpos. O diálogo deve ser legível e funcional no tema Breeze do KDE Plasma 6.

## Acceptance criteria

- [x] O `confirmDialog` não utiliza `standardButtons` automáticos — apenas os botões customizados `Cancelar` e `Remover Conta` são exibidos.
- [x] Os botões têm espaçamento adequado e não se sobrepõem visualmente.
- [x] Teste em `test_plasmoid_interactive.py` valida que o QML fonte do `confirmDialog` não contém `standardButtons`.
- [x] Todos os testes existentes continuam passando (145+).

## Blocked by

None (can start immediately)
