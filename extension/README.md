# Git Switch (VS Code / Cursor)

One-click Git account switching from the status bar.

## User journey

1. Click the status bar (**Git Switch** / your account name).
2. Pick an account **or** choose **Add with GitHub…**
3. Approve in the browser → done.

You can also run **Git Switch: Add Account (GitHub)** from the command palette.

## Setup (from this repo)

```bash
cd extension
npm install
npm run compile
```

Then in VS Code/Cursor: **Extensions: Install from Location…** → choose the `extension` folder  
(or press **F5** from the extension folder to launch an Extension Development Host).

Requires:

- `python3` on your PATH (same machine as the desktop app)
- This repo’s `gitswitch` package (auto-detected next to `extension/`)

Optional settings:

- `gitSwitch.pythonPath` — default `python3`
- `gitSwitch.packageRoot` — repo root containing the `gitswitch` folder

## Commands

| Command | What it does |
| --- | --- |
| **Git Switch: Switch Account** | Quick-pick to switch or add (same as status bar click) |
| **Git Switch: Add Account (GitHub)** | Browser sign-in → save account |
| **Git Switch: Refresh** | Reload the status bar label |

Switch prefers **this workspace** (local git config) when the folder is a repo; otherwise it uses **global**.
