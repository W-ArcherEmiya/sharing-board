# Contributing to Sharing Board

Thank you for helping improve Sharing Board.

## Development setup

1. Install Python 3.10 or newer and Node.js 20 or newer.
2. Install development dependencies with `python -m pip install -r requirements-dev.txt`.
3. Run the application with `python main.py`, or use `Run.bat` on Windows for HTTPS LAN testing.

## Before opening a pull request

Run all automated checks:

```text
python -m unittest discover -s tests -v
node --check static/vendor/qrcode.js
node --check static/script.js
python -m pip_audit -r requirements-dev.txt
python -m bandit -r main.py gen_cert.py launch_config.py -q
detect-secrets scan
```

Keep changes focused, update `README.md` when behavior changes, and add an entry to `CHANGELOG.md` for user-visible changes.

Do not commit generated certificates, private keys, local logs, temporary files, room links, or access credentials.

## Security reports

Do not report exploitable security issues in a public pull request or issue. Follow [SECURITY.md](SECURITY.md) instead.
