#!/usr/bin/env bash
# Script de empacotamento de release do Plasmoid AI Usage Widget e do coletor Python.
# BUILD_ARGS opcional (ex.: --no-isolation para build offline).
# Gera os artefatos em dist/ (ou no diretório especificado como argumento):
#   - org.kde.plasma.aiusage.plasmoid
#   - plasma_ai_usage_collector-*.whl
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLASMOID_DIR="${REPO_ROOT}/plasmoid"
PLUGIN_ID="org.kde.plasma.aiusage"

TARGET_DIST="${1:-${REPO_ROOT}/dist}"
mkdir -p "${TARGET_DIST}"
DIST_DIR="$(cd "${TARGET_DIST}" && pwd)"

PLASMOID_FILE="${DIST_DIR}/${PLUGIN_ID}.plasmoid"

echo "==> Iniciando empacotamento de release..."
echo "==> Diretório de saída: ${DIST_DIR}"

# Limpeza de artefatos anteriores no diretório de saída
rm -f "${PLASMOID_FILE}"
rm -f "${DIST_DIR}"/plasma_ai_usage_collector-*.whl

# Detectar python executável
PYTHON_BIN=""
if [ -n "${PYTHON:-}" ] && command -v "${PYTHON}" >/dev/null 2>&1; then
    PYTHON_BIN="${PYTHON}"
elif [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

# 1. Empacotar Plasmoid (a partir de uma cópia com os catálogos .mo compilados)
echo "==> Gerando ${PLUGIN_ID}.plasmoid..."
if [ ! -f "${PLASMOID_DIR}/metadata.json" ]; then
    echo "Erro: ${PLASMOID_DIR}/metadata.json não encontrado." >&2
    exit 1
fi

source "${SCRIPT_DIR}/stage-plasmoid.sh"
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGE_DIR}"' EXIT
stage_plasmoid "${REPO_ROOT}" "${STAGE_DIR}"

python3 - "${STAGE_DIR}" "${PLASMOID_FILE}" << 'EOF'
import os
import sys
import zipfile

stage, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
ignore_names = {".git", ".DS_Store", "__pycache__"}

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(stage):
        dirs[:] = sorted(d for d in dirs if d not in ignore_names and not d.startswith("."))
        for file in sorted(files):
            if file.startswith(".") or file.endswith(("~", ".swp", ".bak")):
                continue
            abs_path = os.path.join(root, file)
            zf.write(abs_path, os.path.relpath(abs_path, stage))
EOF

if [ ! -f "${PLASMOID_FILE}" ]; then
    echo "Erro: Falha ao gerar ${PLASMOID_FILE}." >&2
    exit 1
fi
echo "==> Plasmoid gerado com sucesso: ${PLASMOID_FILE}"

# 2. Empacotar wheel Python
echo "==> Gerando wheel Python do coletor..."
if [ -z "${PYTHON_BIN}" ]; then
    echo "Erro: Python não encontrado para compilar a wheel." >&2
    exit 1
fi

if "${PYTHON_BIN}" -m build --version >/dev/null 2>&1; then
    echo "==> Compilando wheel com 'python -m build --wheel'..."
    "${PYTHON_BIN}" -m build ${BUILD_ARGS:-} --wheel --outdir "${DIST_DIR}" "${REPO_ROOT}"
elif "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
    echo "==> Compilando wheel com 'pip wheel'..."
    "${PYTHON_BIN}" -m pip wheel --no-deps -w "${DIST_DIR}" "${REPO_ROOT}"
else
    echo "Erro: Nem 'build' nem 'pip' disponíveis para compilar a wheel Python." >&2
    exit 1
fi

# Limpar artefatos temporários de build se gerados
rm -rf "${REPO_ROOT}/build" "${REPO_ROOT}/src"/*.egg-info

# Validar existência da wheel gerada
WHEEL_COUNT=$(find "${DIST_DIR}" -maxdepth 1 -name "plasma_ai_usage_collector-*.whl" | wc -l)
if [ "${WHEEL_COUNT}" -eq 0 ]; then
    echo "Erro: Nenhuma wheel plasma_ai_usage_collector-*.whl foi encontrada em ${DIST_DIR}." >&2
    exit 1
fi

echo "==> Artefatos gerados com sucesso em ${DIST_DIR}:"
ls -lh "${DIST_DIR}/${PLUGIN_ID}.plasmoid" "${DIST_DIR}"/plasma_ai_usage_collector-*.whl

echo "==> Empacotamento concluído com sucesso!"
