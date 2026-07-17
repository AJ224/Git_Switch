# Contributing to Git Account Switcher

Thanks for helping improve Git Account Switcher.

## Getting started

1. Clone the repository.
2. Ensure Python 3.8+ and Git are installed.
3. Run the app locally:

```bash
python3 git_account_switcher.py
```

On Linux, install Tkinter if needed:

```bash
sudo apt install python3-tk
```

For PAT testing, configure a Git credential helper for your platform before saving tokens in the app.

## Development guidelines

- Keep runtime dependencies at zero beyond the Python standard library.
- Preserve local-first behavior: account metadata stays in `~/.gitswitch/`, and PAT tokens must never be written to disk by the app.
- Use Git's credential protocol (`git credential approve` / `reject`) for PAT storage; do not call platform helpers directly.
- Prefer small, focused modules under `gitswitch/`.
- Add or update tests in `tests/` for backend, storage, validation, and credential behavior.
- Test both light and dark themes when changing UI code.

## Pull requests

- Describe the problem and the solution clearly.
- Include screenshots for UI changes when possible.
- Run tests before opening a PR:

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q git_account_switcher.py gitswitch tests
```

## Releases

Maintainers cut releases by pushing a version tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The release workflow builds macOS, Windows, and Linux binaries and attaches them to the GitHub Release.

## Reporting issues

Include:

- Operating system and Python version
- Git version (`git --version`)
- Whether a credential helper is configured (`git config --global --get-all credential.helper`)
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs or screenshots
