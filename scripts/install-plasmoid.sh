#!/usr/bin/env bash
# Script de instalação e validação local do Plasmoid AI Usage Widget para KDE Plasma 6.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLASMOID_DIR="${REPO_ROOT}/plasmoid"
PLUGIN_ID="org.kde.plasma.aiusage"
TARGET_DIR="${HOME}/.local/share/plasma/plasmoids/${PLUGIN_ID}"

echo "==> Iniciando instalação do Plasmoid (${PLUGIN_ID})..."

if [ ! -f "${PLASMOID_DIR}/metadata.json" ]; then
    echo "Erro: ${PLASMOID_DIR}/metadata.json não encontrado." >&2
    exit 1
fi

# Catálogos: compila po/*.po em contents/locale/<idioma>/LC_MESSAGES/plasma_applet_<id>.mo numa cópia
# temporária (os .mo não são versionados) e instala essa cópia.
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGE_DIR}"' EXIT
cp -r "${PLASMOID_DIR}/." "${STAGE_DIR}/"
python3 "${REPO_ROOT}/tools/i18n.py" compile "${STAGE_DIR}/contents/locale" >/dev/null
PLASMOID_DIR="${STAGE_DIR}"

if command -v kpackagetool6 >/dev/null 2>&1; then
    echo "==> Utilizando kpackagetool6..."
    
    # Verifica hash/integridade do pacote
    kpackagetool6 -t Plasma/Applet --hash "${PLASMOID_DIR}" >/dev/null

    # Verifica se já está instalado
    if kpackagetool6 -t Plasma/Applet -s "${PLUGIN_ID}" >/dev/null 2>&1; then
        echo "==> Atualizando pacote existente..."
        kpackagetool6 -t Plasma/Applet -u "${PLASMOID_DIR}"
    else
        echo "==> Instalando novo pacote..."
        kpackagetool6 -t Plasma/Applet -i "${PLASMOID_DIR}"
    fi
else
    echo "==> kpackagetool6 não encontrado. Copiando diretamente para diretório de plasmoids do usuário..."
    mkdir -p "$(dirname "${TARGET_DIR}")"
    rm -rf "${TARGET_DIR}"
    cp -r "${PLASMOID_DIR}" "${TARGET_DIR}"
fi

if [ -f "${TARGET_DIR}/metadata.json" ]; then
    echo "==> Plasmoid '${PLUGIN_ID}' instalado com sucesso em:"
    echo "    ${TARGET_DIR}"
else
    echo "Erro: Falha na validação do diretório instalado (${TARGET_DIR})." >&2
    exit 1
fi
