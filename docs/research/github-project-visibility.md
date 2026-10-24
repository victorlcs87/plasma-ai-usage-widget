# Visibilidade do projeto no GitHub

Pesquisa realizada em 23 de outubro de 2026, usando documentação oficial do GitHub. As recomendações abaixo ajudam pessoas a encontrar, entender e experimentar o projeto; as fontes não garantem aumento de estrelas, posição em buscadores ou tráfego.

## Descoberta na busca

O GitHub pesquisa nome, descrição e tópicos por padrão. O README também pode ser pesquisado com `in:readme`. Portanto, a descrição do campo About merece prioridade: deve mencionar KDE Plasma 6, widget, Claude, Codex e Gemini em linguagem natural. Isso amplia a correspondência com buscas relevantes, sem promessa de melhor classificação. [Fonte: busca de repositórios](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories).

Tópicos classificam o propósito, comunidade e linguagem de um repositório, e permitem descoberta por `topic:`. O limite é de 20 tópicos, com letras minúsculas, números e hífens. Para este projeto, candidatos pertinentes são `kde`, `kde-plasma`, `plasma6`, `plasmoid`, `linux`, `ai`, `claude`, `codex`, `gemini`, `usage-monitor`, `python`, `qml` e `waybar`; use apenas os que descrevem funcionalidades reais. [Fonte: tópicos](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics).

## Apresentação do README

O README costuma ser o primeiro conteúdo visto por visitantes. O GitHub recomenda explicar o que o projeto faz, sua utilidade, como começar, onde obter ajuda e quem o mantém. [Fonte: READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes).

Aplicação editorial recomendada: usar o nome do widget no título; apresentar uma descrição curta, uma captura real e links de instalação antes dos detalhes do coletor. Uma introdução em inglês com acesso à documentação em português pode tornar o conteúdo compreensível para mais visitantes internacionais; essa é uma decisão editorial, não um fator de ranqueamento documentado. Conservar detalhes técnicos em documentação vinculada. Imagens e documentos locais devem usar caminhos relativos, que o GitHub resolve conforme a branch. [Fonte: READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes).

## Compartilhamento

A imagem de prévia social substitui a apresentação básica com avatar quando links são compartilhados, ajudando a identificar o projeto. O GitHub recomenda PNG, JPG ou GIF com menos de 1 MB; 1280 × 640 pixels oferece a melhor apresentação recomendada. Uma captura no README não configura automaticamente essa prévia: ela deve ser enviada em Settings → Social preview. [Fonte: prévia social](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).

## Participação e confiança

Um `CONTRIBUTING.md` informa como colaborar e recebe links na abertura de issues e pull requests, na página de contribuição, na visão geral e na barra lateral do repositório. Para este projeto, deve explicar instalação de desenvolvimento, verificações relevantes, tradução e informações úteis para relatar problemas. Isso reduz o esforço para contribuir; não é uma garantia de descoberta na busca. [Fonte: diretrizes de contribuição](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/setting-guidelines-for-repository-contributors).

Modelos de issue padronizam relatos; formulários permitem solicitar dados estruturados e campos obrigatórios. Sugestão: separar bugs de pedidos de funcionalidade e pedir versões do Plasma/widget/coletor, provedor afetado e passos de reprodução, sem solicitar credenciais. Os arquivos precisam estar na branch padrão, em `.github/ISSUE_TEMPLATE`, para aparecerem aos usuários. [Fonte: modelos de issues e pull requests](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates).

## Prioridade prática

1. Corrigir o foco do título e da introdução: o produto é o widget, com coletor necessário.
2. Mostrar captura real e caminho de instalação visível, mantendo as instruções completas acessíveis.
3. Preencher descrição, link útil e tópicos relevantes no About.
4. Facilitar ajuda e contribuições com documentação e modelos de issue.
5. Preparar e configurar uma prévia social ao compartilhar o repositório.

Essas prioridades são uma síntese aplicada ao projeto. Evitar repetição artificial de palavras-chave, badges sem significado, status de CI que não refletem execuções atuais e afirmações de suporte sem verificação.
