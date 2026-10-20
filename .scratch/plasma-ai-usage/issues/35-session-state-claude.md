# 35: Estado da Sessão — Claude (hooks opt-in)

**Parent:** #8

**What to build:** Comandos `--install-hooks`/`--uninstall-hooks` registram/removem hooks do Claude Code (envio de prompt, parada, notificação) que gravam um arquivo de estado; a remoção preserva os hooks existentes do usuário (ADR-0009). O contrato expõe o Estado da Sessão; o anel mostra arco girando (ocupada) e âmbar pulsando (aguardando); o Notch abre por 5 s com som opcional quando a sessão termina ou pede algo.

**Blocked by:** 31 (#22)

**Status:** ready-for-agent

- [ ] Instalação e remoção idempotentes, preservando outros hooks e configurações.
- [ ] Nada é instalado sem o comando explícito.
- [ ] Estado refletido no contrato e nas animações.
- [ ] Testes pela CLI com configuração temporária.
- [ ] Testes do coletor passando (`.venv/bin/pytest`), sem regressão nas funcionalidades existentes.
