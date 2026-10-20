# ADR 0009: Estado da Sessao via Hooks Opt-in

Status: accepted

Para exibir o Estado da Sessao (ocupada / aguardando o usuario), no estilo dos aneis animados do Codenotch, decidimos registrar hooks do Claude Code (eventos de envio de prompt, parada e notificacao) que gravam um arquivo de estado local lido pelo Plasmoid. Para o Codex, usamos seu mecanismo de notificacao e os logs de sessao. Os hooks so sao instalados quando o usuario pede explicitamente (`--install-hooks`) e possuem remocao limpa (`--uninstall-hooks`), que preserva os demais hooks e configuracoes do usuario.

## Considered Options

- Heuristica pelo mtime dos logs de sessao: rejeitada porque nao distingue "aguardando o usuario" de "ociosa".
- Instalar os hooks automaticamente: rejeitado porque alterar a configuracao do agente sem consentimento do usuario e invasivo.
