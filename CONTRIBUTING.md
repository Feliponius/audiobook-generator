# Contributing

This is a personal project that grew into something shareable. While it's primarily built for my own use, contributions are welcome!

## Development Setup

```bash
git clone <repo>
cd audiobook-generator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pytest
```

## Code Style

- Python: Follow PEP 8, keep lines under 100 characters
- JavaScript: Vanilla JS, no build step
- HTML/CSS: Single-file dashboard pattern

## Pull Request Guidelines

1. Keep changes focused and reviewable
2. Test on mobile if changing UI
3. Document any new dependencies
4. Ensure tests pass: `pytest tests/`

## Areas for Contribution

- **Performance**: Faster TTS, parallel processing
- **Formats**: Support for more ebook formats (MOBI, PDF)
- **Accessibility**: Screen reader support, keyboard navigation
- **i18n**: Multi-language TTS support

## Questions?

Open an issue or reach out directly.
