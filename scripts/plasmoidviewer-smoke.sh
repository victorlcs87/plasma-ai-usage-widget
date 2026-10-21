#!/usr/bin/env bash
# Smoke do plasmoide no runtime REAL do Plasma (plasmoidviewer) numa tela virtual, com HOME falso.
# Nunca toca na sessão nem nos dados do usuário: xvfb-run + HOME/XDG_* temporários + sem Wayland/D-Bus de sessão.
# Uso: scripts/plasmoidviewer-smoke.sh [diretório-de-PNGs]   (padrão: ./smoke-out)
# Variáveis: LANGS="pt_BR en_US"  FORMS="horizontal vertical"  PYTHON=python3
# Sai com código != 0 se o log tiver erro de QML nosso (recursive rearrange, TypeError, ReferenceError, Unable to assign,
# is not defined, Binding loop) vindo do plasmoide; ruído do próprio viewer é ignorado (allowlist abaixo).
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mkdir -p "${1:-./smoke-out}" && cd "${1:-./smoke-out}" && pwd)"
PYTHON="${PYTHON:-python3}"
for t in plasmoidviewer xvfb-run xdotool import; do command -v "$t" >/dev/null || { echo "faltando: $t" >&2; exit 2; }; done

if [ -z "${AIU_SMOKE_INNER:-}" ]; then
    exec env AIU_SMOKE_INNER=1 xvfb-run -a -s "-screen 0 1600x1000x24" "$0" "$OUT"
fi

FH="$(mktemp -d)"; trap 'rm -rf "$FH"' EXIT
export HOME="$FH" XDG_DATA_HOME="$FH/.local/share" XDG_CACHE_HOME="$FH/.cache" XDG_CONFIG_HOME="$FH/.config"
export QT_QPA_PLATFORM=xcb QT_FORCE_STDERR_LOGGING=1
unset WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS
mkdir -p "$XDG_CACHE_HOME/plasma-ai-usage"
PYTHONPATH="$REPO/src" "$PYTHON" "$REPO/tools/smoke_status.py" "$XDG_CACHE_HOME/plasma-ai-usage/status.json" || exit 2
bash "$REPO/scripts/install-plasmoid.sh" >/dev/null 2>&1 || { echo "instalação falhou" >&2; exit 2; }

# Só contam linhas que citam arquivos do nosso plasmoide (org.kde.plasma.aiusage). O ruído do viewer fica de fora por
# construção: desktopcontainment/isScreenUiReady, "Failed to register with host portal", "Failed to create wl_display",
# "AppletPopup: Exposed with no visual parent / Window positioning broken".
BAD='recursive rearrange|TypeError|ReferenceError|Unable to assign|is not defined|Binding loop'
fail=0
for lang in ${LANGS:-pt_BR en_US}; do
  for form in ${FORMS:-horizontal vertical}; do
    log="$OUT/log_${lang}_${form}.txt"
    LANGUAGE=$lang LANG=$lang.UTF-8 LC_ALL=$lang.UTF-8 timeout 30 plasmoidviewer -a org.kde.plasma.aiusage -f "$form" -s 900x500 >"$log" 2>&1 &
    pid=$!
    sleep 6
    # A pílula fica no canto superior esquerdo do viewer; o clique abre o popup
    xdotool mousemove 40 47; sleep 1; xdotool click 1; sleep 3
    # o popup nasce sob a janela do viewer: leva-o para uma área livre para o PNG
    for w in $(xdotool search --name "" 2>/dev/null); do
      g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
      case "$g" in *"Geometry: 4"[0-9][0-9]x[45]*) xdotool windowmove "$w" 1000 20 2>/dev/null;; esac
    done
    sleep 1
    import -window root -display "$DISPLAY" "$OUT/popup_${lang}_${form}.png" 2>/dev/null
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
    if grep -E "$BAD" "$log" | grep -E 'org\.kde\.plasma\.aiusage' ; then
      echo "ERRO de QML nosso em $lang/$form (ver $log)" >&2; fail=1
    fi
  done
done
[ $fail = 0 ] && echo "smoke ok: PNGs e logs em $OUT"
exit $fail
