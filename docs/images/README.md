# Documentation screenshots

`panel.png` and `overview.png` render the current QML components with synthetic account and quota data from `tools/smoke_status.py`. They contain no real credentials or account information. The popup uses native Kirigami for its theme and icons, with Plasma services stubbed so it cannot collect live data or run commands.

The rendering helpers in `tests/test_plasmoid_notch_render.py` and `tests/test_plasmoid_popup.py` accept `AIU_PNG_DIR` for saving screenshots. Keep demonstration names and figures fictional when updating these assets. These images illustrate the interface; they do not promise a particular provider plan or quota.

For a full Plasma runtime check, use `scripts/plasmoidviewer-smoke.sh` with its isolated demo environment. See the [technical guide](../usage.pt-BR.md#smoke-no-runtime-real-do-plasma).
