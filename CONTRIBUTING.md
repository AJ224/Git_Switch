# Contributing to Git Switch

Thanks for helping improve Git Switch.

## Repo layout

```text
git_account_switcher.py   # desktop launcher
gitswitch/                # Python core + Tk UI
  app.py                  # desktop window
  service.py              # shared switch / list / status
  backend.py              # git / ssh / credential commands
  __main__.py             # JSON bridge for the extension
extension/                # VS Code / Cursor extension
tests/                    # unit tests
assets/                   # app icons (.icns / .ico / png)
docs/                     # logo and user-facing images
```

## Desktop app (Python)

**Requirements:** Python 3.8+, Git, Tkinter.

```bash
python3 git_account_switcher.py
```

Linux Tkinter (if missing):

```bash
sudo apt install python3-tk
```

For PAT / GitHub sign-in testing, configure a credential helper first (osxkeychain / GCM / libsecret).

### Guidelines

- Zero runtime deps beyond the Python stdlib
- Local-first: metadata in `~/.gitswitch/`; **never** write PAT/OAuth tokens into JSON
- Store PATs only via `git credential approve` / `reject`
- Keep modules under `gitswitch/` small and focused
- Add tests in `tests/` for service, backend, store, OAuth helpers
- Check light and dark themes when changing UI

### Tests

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q git_account_switcher.py gitswitch tests
```

## Extension (VS Code / Cursor)

```bash
cd extension
npm install
npm run compile
```

Then **F5**, or **Extensions: Install from Location…** → `extension/`.

- Marketplace id: `gitswitch.git-switch-accounts`
- Built-in native engine works without Python; optional bridge via `python -m gitswitch` if `gitSwitch.packageRoot` points at this repo
- Before publishing, check the `name` in `package.json` is free on the Marketplace (names are global), then:

```bash
cd extension
npx vsce package
npx vsce publish --dry-run   # or --oidc with Trusted Publishing
```

Full publish steps (Marketplace + Open VSX): [extension/PUBLISH.md](extension/PUBLISH.md).

## Desktop binaries

```bash
pip install pyinstaller
pyinstaller git_account_switcher.spec   # macOS .app + icons
```

Maintainers ship releases by tagging:

```bash
git tag v1.2.0
git push origin v1.2.0
```

CI builds macOS / Windows / Linux and attaches artifacts to the GitHub Release. Extension publishes via **Actions → Publish Extension** (Trusted Publishing / OIDC).

## Pull requests

- Describe the problem and the fix
- Screenshots for UI changes when useful
- Run the test commands above before opening the PR

## Issues

Include OS, Python/`git --version`, credential helper (`git config --global --get-all credential.helper`), steps to reproduce, expected vs actual, and screenshots if relevant.
