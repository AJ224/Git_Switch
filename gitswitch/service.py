"""UI-free account operations shared by the desktop app and IDE bridge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gitswitch.backend import GitBackend
from gitswitch.github_signin import account_payload_from_oauth, sign_in_with_github
from gitswitch.models import Account, AuthMethod, Scope
from gitswitch.oauth import OAuthResult
from gitswitch.store import AccountStore

StatusCallback = Callable[[str], None]


@dataclass
class SwitchResult:
    ok: bool
    summary: str
    detail: str = ""
    account: Account | None = None
    scope: Scope = "global"


@dataclass
class StatusSnapshot:
    scope: Scope
    repo_path: str | None
    name: str
    email: str
    matched: Account | None
    accounts: list[Account]


def list_accounts(store: AccountStore | None = None) -> list[Account]:
    return (store or AccountStore()).load()


def find_account(
    account_id: str | None = None,
    label: str | None = None,
    store: AccountStore | None = None,
) -> Account | None:
    accounts = list_accounts(store)
    if account_id:
        for account in accounts:
            if account.id == account_id:
                return account
    if label:
        needle = label.strip().lower()
        for account in accounts:
            if account.label.strip().lower() == needle:
                return account
    return None


def match_account(email: str, accounts: list[Account] | None = None) -> Account | None:
    needle = (email or "").strip().lower()
    if not needle:
        return None
    for account in accounts or list_accounts():
        if account.email.strip().lower() == needle:
            return account
    return None


def resolve_scope(repo_path: str | None, prefer_local: bool = True) -> tuple[Scope, str | None]:
    """Pick local when the folder is a git repo; otherwise global."""
    if prefer_local and repo_path and GitBackend.is_git_repo(repo_path):
        return "local", repo_path
    return "global", None


def get_status(
    repo_path: str | None = None,
    scope: Scope | None = None,
    store: AccountStore | None = None,
    backend: type[GitBackend] = GitBackend,
) -> StatusSnapshot:
    accounts = list_accounts(store)
    if scope is None:
        resolved_scope, resolved_repo = resolve_scope(repo_path)
    else:
        resolved_scope = scope
        resolved_repo = repo_path if scope == "local" else None

    name, email = backend.get_current_identity(scope=resolved_scope, repo_path=resolved_repo)
    return StatusSnapshot(
        scope=resolved_scope,
        repo_path=resolved_repo,
        name=name,
        email=email,
        matched=match_account(email, accounts),
        accounts=accounts,
    )


def activate_authentication(
    account: Account,
    scope: Scope,
    repo_path: str | None,
    backend: type[GitBackend] = GitBackend,
) -> tuple[bool, str]:
    if account.auth_method == AuthMethod.SSH and account.ssh_key:
        return backend.ssh_add_key(account.ssh_key)
    if account.auth_method == AuthMethod.PAT:
        if not account.has_pat:
            return (
                False,
                "No HTTPS token saved for this account. "
                "Use Add with GitHub in the desktop app, or edit the account and paste a token.",
            )
        return backend.activate_pat(
            account.pat_host,
            account.pat_username,
            scope=scope,
            repo_path=repo_path,
        )
    return True, ""


def switch_summary(account: Account, scope: Scope, auth_ok: bool) -> str:
    summary = f"Switched to '{account.label}' ({scope})."
    if account.auth_method == AuthMethod.NONE:
        summary += (
            " Identity only: commit author updated. "
            "Push/pull auth was not changed — configure SSH or HTTPS / PAT for repo access."
        )
    elif account.auth_method == AuthMethod.SSH and account.ssh_key:
        summary += f" Commit author updated. SSH push/pull: {'OK' if auth_ok else 'FAILED'}."
    elif account.auth_method == AuthMethod.PAT:
        if auth_ok:
            summary += (
                " Commit author updated. HTTPS push/pull credentials activated "
                f"for '{account.pat_username}' "
                "(use https:// remotes; gh CLI is unchanged)."
            )
        else:
            summary += " Commit author updated, but HTTPS credentials were NOT activated."
    return summary


def switch_account(
    account: Account,
    scope: Scope = "global",
    repo_path: str | None = None,
    backend: type[GitBackend] = GitBackend,
) -> SwitchResult:
    if scope == "local" and not backend.is_git_repo(repo_path):
        return SwitchResult(
            ok=False,
            summary=f"'{repo_path}' is not a git repository.",
            account=account,
            scope=scope,
        )

    ok, message = backend.set_identity(account.name, account.email, scope=scope, repo_path=repo_path)
    if not ok:
        return SwitchResult(ok=False, summary=message, account=account, scope=scope)

    auth_ok, auth_message = activate_authentication(account, scope, repo_path, backend=backend)
    summary = switch_summary(account, scope, auth_ok)
    return SwitchResult(
        ok=True,
        summary=summary,
        detail=auth_message,
        account=account,
        scope=scope,
    )


def switch_by_id_or_label(
    account_id: str | None = None,
    label: str | None = None,
    scope: Scope | None = None,
    repo_path: str | None = None,
    store: AccountStore | None = None,
    backend: type[GitBackend] = GitBackend,
) -> SwitchResult:
    account = find_account(account_id=account_id, label=label, store=store)
    if not account:
        target = account_id or label or "(unknown)"
        return SwitchResult(ok=False, summary=f"No account found for '{target}'.")

    if scope is None:
        scope, repo_path = resolve_scope(repo_path)
    elif scope == "global":
        repo_path = None

    return switch_account(account, scope=scope, repo_path=repo_path, backend=backend)


def account_to_public_dict(account: Account) -> dict[str, object]:
    return {
        "id": account.id,
        "label": account.label,
        "name": account.name,
        "email": account.email,
        "auth_method": account.auth_method.value,
        "has_pat": account.has_pat,
        "ssh_key": bool(account.ssh_key),
        "host_alias": account.host_alias,
        "pat_host": account.pat_host,
        "pat_username": account.pat_username,
    }


def find_git_root(start: str | None) -> str | None:
    """Walk up from start looking for a .git directory (file or folder)."""
    if not start:
        return None
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for path in [current, *current.parents]:
        git_entry = path / ".git"
        if git_entry.exists():
            return str(path)
    return None


@dataclass
class AddAccountResult:
    ok: bool
    summary: str
    action: str = ""
    account: Account | None = None
    detail: str = ""


def save_github_account(
    result: OAuthResult,
    store: AccountStore | None = None,
    backend: type[GitBackend] = GitBackend,
) -> AddAccountResult:
    """Persist a GitHub OAuth/device-login result as a PAT account."""
    account_store = store or AccountStore()
    payload = account_payload_from_oauth(result)
    account = Account(
        label=payload["label"],
        name=payload["name"],
        email=payload["email"] or f"{payload['pat_username']}@users.noreply.github.com",
        auth_method=AuthMethod.PAT,
        pat_host=payload["pat_host"],
        pat_username=payload["pat_username"],
        has_pat=False,
    )

    ok, message = backend.store_pat(account.pat_host, account.pat_username, payload["token"])
    if not ok:
        return AddAccountResult(ok=False, summary=message or "Could not save GitHub token.")

    account.pat_host = backend.normalize_host(account.pat_host)
    account.has_pat = True

    existing = next(
        (
            item
            for item in account_store.load()
            if item.auth_method == AuthMethod.PAT
            and item.pat_username.lower() == account.pat_username.lower()
            and item.pat_host == account.pat_host
        ),
        None,
    )
    if existing:
        account.id = existing.id
        account_store.update(existing.id, account)
        action = "Updated"
    else:
        account_store.add(account)
        action = "Added"

    detail = ""
    if not payload["email"]:
        detail = "GitHub did not return an email — using a noreply address. Edit if needed."

    return AddAccountResult(
        ok=True,
        summary=f"{action} GitHub account '{account.label}'.",
        action=action,
        account=account,
        detail=detail,
    )


def add_github_account(
    on_status: StatusCallback | None = None,
    store: AccountStore | None = None,
    backend: type[GitBackend] = GitBackend,
) -> AddAccountResult:
    """Browser device login → save account (same flow as the desktop app)."""
    oauth_result, _method = sign_in_with_github(on_status=on_status)
    if on_status:
        on_status("Saving GitHub account…")
    return save_github_account(oauth_result, store=store, backend=backend)
