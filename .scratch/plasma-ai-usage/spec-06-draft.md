## Problem Statement

No painel do Plasma, os itens dos provedores (C, X, G) ficam pequenos, mostram dois arcos e usam uma letra em vez do logo. As opções de Painel na configuração não mudam nada no painel real (só no Notch flutuante, que ainda tem teto de escala baixo). Na configuração, o diálogo Renomear Conta corta os botões fora da moldura e o popup deixa um vazio embaixo. A conta Gemini capturada vira "expirada" em até 1 hora, porque o coletor usa uma cópia do token que a CLI da Antigravity renova no arquivo original.

## Solution

- O painel mostra um logo do provedor no lugar da inicial e só o Arco de Horário (Janela Nativa), ocupando a espessura disponível do painel.
- Clicar num item abre o popup, com os dois arcos daquele provedor destacados no topo. Abrir por hover continua como está, sem destacar ninguém.
- O Logo do Provedor substitui toda letra de provedor (painel, centro do anel, cartões, popup e configuração).
- O Notch flutuante aceita escala até 400%.
- O diálogo Renomear Conta e o popup passam a ter a altura certa.
- A conta Gemini da Antigravity é lida do arquivo vivo, como as de Claude e Codex.

## User Stories

1. Como usuário, quero ver o logo de cada IA no painel, para reconhecê-la de relance.
2. Como usuário, quero só o arco da janela de horário no painel, para um painel mais limpo.
3. Como usuário, quero clicar num item e ver os dois arcos desse provedor no popup, para consultar a janela semanal sob demanda.
4. Como usuário, quero logos no lugar de todas as letras de provedor, para ter uma identidade visual única.
5. Como usuário, quero logos que acompanham o tema claro e escuro e o nível de alerta.
6. Como usuário, quero escala do Notch flutuante até 400%, para lê-lo em monitor grande.
7. Como usuário, quero que as opções de Painel valham até o limite da espessura do painel.
8. Como usuário, quero ver o diálogo Renomear Conta inteiro, com Cancelar e Salvar dentro da moldura.
9. Como usuário, quero um popup sem vazio embaixo do histórico.
10. Como usuário do Gemini via Antigravity, quero que a conta continue válida sem recapturar, como Claude e Codex.
11. Como usuário, quero que o hover continue abrindo o popup sem destacar provedor.

## Implementation Decisions

- Logos: SVGs monocromáticos de licença livre, baixados da internet (fonte e licença registradas no repo), empacotados no plasmoide e coloridos pelo tema/nível.
- Um único componente de Logo do Provedor substitui as letras (PanelItem, centro do Anel Duplo, cartões, popup, configuração, seletor de provedor). Provedor desconhecido mantém a letra "?".
- Painel: o Anel Duplo vira anel simples (Arco de Horário). O logo e o anel ocupam a espessura do painel; a escala só reduz. Margem automática como hoje.
- Clique no item: abre o popup e informa qual provedor destacar; o popup mostra os dois arcos desse provedor no topo. Hover não destaca. O destaque não persiste entre reinícios.
- Notch flutuante: teto de escala 400%, passo de 10%; geometria e layer-shell respeitam o novo teto.
- Renomear Conta: o diálogo dimensiona pelo conteúdo (largura mínima), com o rodapé dentro da moldura. Popup: remove o vazio inferior.
- Gemini: a conta capturada da Antigravity passa a apontar para o arquivo vivo `~/.gemini/antigravity-cli/antigravity-oauth-token` (só leitura), e o coletor lê `expiry` além de `expiry_date`. Sem renovar token, sem embutir client_id. A cópia em `profiles/` deixa de ser a fonte para essa conta.
- ADR novo registrando o Arco de Horário e o clique por provedor.

## Testing Decisions

- Teste só comportamento externo. Seam único: o harness QML (`qml6` / `plasmoidviewer`) existente, mais os testes do coletor para o Gemini.
- Arte anterior: `tests/test_plasmoid_floating_screen.py` (kwin virtual), `tests/test_gemini_antigravity_token.py`, `tests/test_ui_contrast.py`, harness de configuração.
- Casos: painel desenha um arco e o logo; clique abre o popup com o provedor destacado; hover não destaca; escala 400% no Notch; Renomear com botões dentro da moldura; Gemini válido com `expiry` no futuro e lido do arquivo vivo.

## Out of Scope

- Renovar tokens OAuth no coletor.
- Aumentar o painel do Plasma além da espessura dele.
- Persistir o provedor destacado.
- Novos provedores.

## Further Notes

- Pendência: o plasmashell em execução (06:45) ainda roda o código antigo; reiniciar antes de testar o Painel.
- Logos são marcas registradas; uso apenas para identificar o provedor.
