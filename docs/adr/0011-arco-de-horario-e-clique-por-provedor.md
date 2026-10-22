# Painel com Arco de Horário e clique que destaca o provedor

## Contexto

Os itens do painel mostravam dois arcos (Anel Duplo) e uma letra por provedor, pequenos para a espessura do painel.

## Decisões

- **Arco de Horário.** No painel cada item desenha só o arco da Janela Nativa, ocupando a espessura do painel menos a margem automática; a escala só reduz, nunca amplia. O Anel Duplo continua no Notch flutuante e no popup.
- **Clique por provedor.** Clicar num item abre o popup e destaca esse provedor no topo, com os dois arcos (nativa e semanal). Hover abre sem destacar ninguém. O destaque vive só em memória (`highlightProvider` em `main.qml`), é zerado ao fechar o popup e nunca vai para a configuração.
- **Logo do Provedor** substitui toda letra de provedor (ADR não necessário além deste registro; ver `CONTEXT.md`).

## Consequências

- Painéis estreitos caem mais cedo no modo `lean`, porque o anel agora é maior.
- Teclado e ação de acessibilidade abrem o popup sem destacar provedor.
