# Contributing

Thanks for helping improve Plasma AI Usage Widget. Bug reports, translations, documentation and focused code changes are welcome. You can write issues in English or Brazilian Portuguese.

## Report a bug

Use the [bug report form](https://github.com/victorlcs87/plasma-ai-usage-widget/issues/new?template=bug_report.yml). Include your widget and collector versions, Plasma version, affected provider, steps to reproduce, and expected behavior.

Remove access tokens, refresh tokens, cookies, account emails and private paths from logs and screenshots. Never attach credential files or raw authenticated API responses. For an incorrect quota, include a redacted comparison of the provider's figures and the widget's figures, taken at the same time.

## Suggest an improvement

Use the [feature request form](https://github.com/victorlcs87/plasma-ai-usage-widget/issues/new?template=feature_request.yml). Explain the problem and how the proposed behavior helps. Check existing issues first.

## Work on the code

Requirements: Python 3.10+ and KDE Plasma 6 to run the widget. QML rendering tests also need `qml6`; the Plasma smoke test has additional requirements listed in the [technical guide](docs/usage.pt-BR.md#smoke-no-runtime-real-do-plasma).

```bash
git clone https://github.com/victorlcs87/plasma-ai-usage-widget.git
cd plasma-ai-usage-widget
python3 -m venv .venv
.venv/bin/pip install -e . pytest build setuptools wheel
.venv/bin/python -m pytest
```

Keep changes focused and describe the problem, resulting behavior and validation in your pull request. Add a regression test for a bug when it exercises the actual failure. Use synthetic data in tests and screenshots. Test the affected behavior before running broader checks.

The interface lives in `plasmoid/contents/ui/`; the Python collector lives in `src/ai_usage_collector/`. [CONTEXT.md](CONTEXT.md) defines the project's terminology and [docs/adr/](docs/adr/) records design decisions. User-facing QML strings go through the existing translation helpers.

## Translate

English and Brazilian Portuguese are included. See the [translation guide](docs/usage.pt-BR.md#traduções-i18n) for catalog generation and validation. Translation improvements are welcome even without a code change.

## License

Contributions are distributed under the project's [GPL-3.0-or-later license](LICENSE).
