from __future__ import annotations

import json
from pathlib import Path

from gitswitch.models import Account

CONFIG_DIR = Path.home() / ".gitswitch"
CONFIG_FILE = CONFIG_DIR / "accounts.json"
THEME_FILE = CONFIG_DIR / "theme.json"


class AccountStore:
    def __init__(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_FILE.exists():
            self._write([])

    def _write(self, accounts: list[Account]) -> None:
        payload = [account.to_dict() for account in accounts]
        with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def load(self) -> list[Account]:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

        if not isinstance(raw, list):
            return []

        accounts: list[Account] = []
        for item in raw:
            if isinstance(item, dict):
                accounts.append(Account.from_dict(item))
        return accounts

    def save(self, accounts: list[Account]) -> None:
        self._write(accounts)

    def add(self, account: Account) -> Account:
        accounts = self.load()
        accounts.append(account)
        self.save(accounts)
        return account

    def update(self, account_id: str, updated: Account) -> None:
        accounts = self.load()
        for index, account in enumerate(accounts):
            if account.id == account_id:
                accounts[index] = updated
                break
        self.save(accounts)

    def delete(self, account_id: str) -> None:
        accounts = [account for account in self.load() if account.id != account_id]
        self.save(accounts)


class ThemePreferenceStore:
    def load(self) -> str:
        try:
            with open(THEME_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            theme = str(data.get("theme", "dark"))
            return theme if theme in {"light", "dark"} else "dark"
        except (json.JSONDecodeError, OSError):
            return "dark"

    def save(self, theme: str) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(THEME_FILE, "w", encoding="utf-8") as handle:
            json.dump({"theme": theme}, handle, indent=2)
