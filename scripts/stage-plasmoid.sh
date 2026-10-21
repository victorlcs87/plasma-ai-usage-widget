# Função compartilhada (usada via `source` por install-plasmoid.sh e package-release.sh).
# stage_plasmoid <repo_root> <stage_dir>: copia plasmoid/ para <stage_dir> e compila po/*.po nos
# catálogos .mo (não versionados). Falha se faltar algum catálogo (en e pt_BR).
stage_plasmoid() {
    local repo_root="$1" stage="$2" plugin="org.kde.plasma.aiusage" lang
    cp -r "${repo_root}/plasmoid/." "${stage}/"
    python3 "${repo_root}/tools/i18n.py" compile "${stage}/contents/locale" >/dev/null
    for lang in en pt_BR; do
        if [ ! -f "${stage}/contents/locale/${lang}/LC_MESSAGES/plasma_applet_${plugin}.mo" ]; then
            echo "Erro: catálogo .mo ausente para ${lang}." >&2
            return 1
        fi
    done
}
