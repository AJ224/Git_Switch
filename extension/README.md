# Git Switch

Switch Git accounts from the status bar.

## Use

1. Click **Git Switch** in the status bar
2. Pick an account, or **Add with GitHub…**
3. Approve in the browser → done

Also: command palette → **Git Switch: Switch Account** / **Add Account (GitHub)**.

Uses this workspace’s Git config when you’re in a repo; otherwise global.

## Install

[Marketplace](https://marketplace.visualstudio.com/items?itemName=gitswitch.git-switch-accounts) — search **Git Switch**.

Tokens stay in your OS credential store. Does not change `gh` CLI login.

## Privacy

Account labels live in `~/.gitswitch/`. GitHub tokens go through Git’s credential helper — never into the extension config file.
