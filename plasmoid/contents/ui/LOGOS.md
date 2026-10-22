# Logos dos provedores

Silhuetas monocromáticas de um só path, usadas só para identificar o provedor na interface
(componente `ProviderLogo.qml`). Coloridas em tempo de execução pelo tema e pelo nível.

| Arquivo | Provedor | Ícone de origem |
|---|---|---|
| `logo-claude.svg` | Claude (Anthropic) | `icons/claude.svg` |
| `logo-codex.svg` | Codex (OpenAI) | `icons/openai.svg` (marca OpenAI; o Simple Icons não tem ícone do Codex) |
| `logo-gemini.svg` | Gemini (Google) | `icons/googlegemini.svg` |

- Fonte: pacote Simple Icons, https://github.com/simple-icons/simple-icons, tag `15.0.0`
  (commit `a00fb996df1e3c161f33e2806ddc28998b6f1ae8`), URL de cada ícone:
  `https://raw.githubusercontent.com/simple-icons/simple-icons/15.0.0/icons/<ícone>.svg`.
  A tag 15.0.0 é a última que ainda traz o ícone `openai` (removido nas versões seguintes).
- Licença: CC0 1.0 Universal (domínio público), conforme o `LICENSE.md` do Simple Icons.
- Alterações: removidos o `<title>` e o `role="img"`; adicionados `width`/`height` de 192 (o Canvas rasteriza o SVG no tamanho intrínseco, depois reduz nítido); o `path` ficou intacto.

## Marcas registradas

Claude e Anthropic são marcas da Anthropic PBC; OpenAI e Codex, da OpenAI, Inc.; Gemini e Google,
da Google LLC. A licença CC0 vale para os arquivos de desenho, não para as marcas. Os logos são
usados apenas para identificar o provedor, sem sugerir afiliação ou endosso.
