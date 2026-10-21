# Notch flutuante: janela propria presa a borda (layer-shell no Wayland, janela simples no X11)

Opcional e DESLIGADO por padrao (`floatingNotch`). Com a opcao desligada nada muda: o modo Plasmoid, o
`CompactRepresentation` e o popup nativo sao os de sempre (`main.qml` so carrega `FloatingNotch.qml` por um
`Loader` ativo com a opcao ligada).

## Decisoes

- **Reuso total.** A janela da pilula hospeda o mesmo `CompactRepresentation` (anel duplo, estilos, selos,
  hover/clique/fixar do ticket 34, ocultar sem CLI do 37) com `hosted: true`, orientacao e tamanho forcados; a do
  popup hospeda o mesmo `FullRepresentation`. Nenhuma regra de negocio nem de cor foi duplicada.
- **Estado do popup.** `main.qml` ganhou `open`/`setOpen()`: com o flutuante ativo e o popup do Plasma nunca
  aberto (`floatOpen`); sem ele, `open` e exatamente `expanded`. Ativacao do Plasma (atalho global) com o
  flutuante ativo alterna o popup flutuante.
- **Pilula do painel ao ligar:** vira um marcador miniatura (mesmo clique/hover; botao direito segue abrindo
  "Configurar"), assim o usuario nunca fica sem caminho de volta a configuracao. Se o flutuante nao estiver
  disponivel (modulo layer-shell ausente, sem tela), a pilula normal continua no painel.
- **Posicao.** Uma por borda (`floatOffsetTop|Bottom|Left|Right`, px a partir do centro, 0 = centralizado).
  Toda a conta esta em `FloatingGeometry.js` (puro, testado): `pillRect` reconstroi o retangulo contra a
  geometria ATUAL da tela (clamp), entao monitor removido ou resolucao menor nunca deixam o Notch fora da tela.
  Valores invalidos de configuracao caem no padrao. Arrastar so mexe em `liveOffset` (local) e grava ao soltar
  (com grude opcional no centro); setas movem 8 px (Shift 32 px), Home recentraliza; ha botao "Center" na
  configuracao. A configuracao e a unica fonte (sem laco de binding).
- **Popup** abre para DENTRO da tela, ancorado na pilula, com tamanho limitado ao espaco livre
  (`popupRect`); fecha ao clicar fora quando chegou a ter foco, exceto fixado ou com o mouse na pilula.
- **Multi-monitor.** `floatScreen` (nome da tela; vazio = tela do widget; nome desconhecido = tela do widget).

## API de janela

Wayland (KDE Plasma 6): `LayerShellQt` QML (`import org.kde.layershell`, tipo anexado `Window`) em
`FloatingLayer.qml`, o unico arquivo que importa o modulo, carregado por `Loader` (se faltar, o Loader falha e o
flutuante se declara indisponivel). Ancora sempre superior-esquerda + margens `left/top` = posicao local a
tela (uniforme nas quatro bordas); `exclusionZone = -1`; camada Top (pilula) e Overlay (popup);
`keyboardInteractivity = OnDemand`; a janela so e mostrada depois de aplicar os atributos.
X11 e fallback: `Window` sem moldura com `Qt.WindowStaysOnTopHint | Qt.Tool | Qt.FramelessWindowHint`, posicao
`x/y` explicita, sem strut e sem tipo DOCK (nao reserva area).

### Verificado
- Protocolo `zwlr_layer_shell_v1` (wayland.app): exclusive_zone `0` = "mova-me para nao cobrir zonas
  exclusivas" (a pilula se deslocaria quando paineis aparecem), `-1` = "nao me mova"; por isso `-1`, nao `0`.
  Dois lados perpendiculares (topo+esquerda) ancoram no canto e as margens deslocam a partir dele.
  `on_demand` e o modo para foco de teclado sob demanda.
- Modulo instalado (layer-shell-qt 6.8.0): tipo `LayerShellQt::Window` com `anchors`, `margins`, `exclusionZone`,
  `layer`, `keyboardInteractivity`, `scope`, `screen`; fora do Wayland as propriedades anexadas sao aceitas e
  lidas de volta (os testes leem anchors/margens/zona/camada de volta). O atributo anexado precisa ser criado
  antes de a janela ser mostrada (o Qt avisa "already has a shell integration" se nao).
- Geometria por borda/tela/clamp/popup, configuracao e fallback sem o modulo: testes em qml6 offscreen.

### Suposto (so verificavel no Plasma real)
- KWin aplica `exclusionZone = -1` e as margens como no protocolo; paineis nao deslocam o Notch; as quatro
  bordas com a ancora superior-esquerda; camada Top/Overlay sobre janelas normais.
- O arraste com o ponteiro real: o desvio e acumulado sobre o offset ja aplicado, supondo que o compositor
  aplique as margens rapido; se oscilar, aumentar o limiar/limitar a taxa. Setas e o campo de posicao na
  configuracao funcionam sem depender disso.
- Compositor Wayland SEM layer-shell (nao e o KWin): o Qt mostra uma janela comum e a posicao nao e honrada;
  nao ha deteccao pelo QML. Sem o modulo QML a opcao nao tem efeito.
- X11: o KWin respeita `x/y` programaticos de uma janela Tool sem moldura e nao a empurra para fora de areas
  reservadas de paineis; foco do popup e Escape.
- Foco de teclado na pilula flutuante so depois de clicar nela ou de usar o marcador do painel (Tab);
  fechar o popup ao clicar fora so funciona se ele chegou a receber foco.
- Troca de tela/resolucao com a janela mostrada reposiciona pelo clamp, mas o comportamento do layer-shell ao
  mudar `screen` em uma janela ja mostrada nao foi testado.
