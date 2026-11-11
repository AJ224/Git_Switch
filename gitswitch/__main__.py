"""Machine JSON bridge for the IDE extension. Not a user-facing CLI."""

from __future__ import annotations

import argparse
import json
import sys

from gitswitch.oauth import OAuthError
from gitswitch.service import (
    account_to_public_dict,
    add_github_account,
    find_git_root,
    get_status,
    list_accounts,
    switch_by_id_or_label,
)


def _emit(payload: dict[str, object], ok: bool = True) -> int:
    print(json.dumps(payload, indent=2))
    return 0 if ok else 1


def _emit_status(message: str) -> None:
    """Progress lines on stderr so the extension can show them live."""
    print(json.dumps({"type": "status", "message": message}), file=sys.stderr, flush=True)


def cmd_list(_args: argparse.Namespace) -> int:
    accounts = [account_to_public_dict(account) for account in list_accounts()]
    return _emit({"ok": True, "accounts": accounts})


def cmd_status(args: argparse.Namespace) -> int:
    repo = find_git_root(args.repo) if args.repo else None
    scope = args.scope
    snapshot = get_status(repo_path=repo, scope=scope)
    return _emit(
        {
            "ok": True,
            "scope": snapshot.scope,
            "repo_path": snapshot.repo_path,
            "name": snapshot.name,
            "email": snapshot.email,
            "matched": account_to_public_dict(snapshot.matched) if snapshot.matched else None,
            "accounts": [account_to_public_dict(account) for account in snapshot.accounts],
        }
    )


def cmd_switch(args: argparse.Namespace) -> int:
    repo = find_git_root(args.repo) if args.repo else None
    result = switch_by_id_or_label(
        account_id=args.id,
        label=args.label,
        scope=args.scope,
        repo_path=repo,
    )
    payload: dict[str, object] = {
        "ok": result.ok,
        "summary": result.summary,
        "detail": result.detail,
        "scope": result.scope,
    }
    if result.account:
        payload["account"] = account_to_public_dict(result.account)
    return _emit(payload, ok=result.ok)


def cmd_add_github(_args: argparse.Namespace) -> int:
    try:
        result = add_github_account(on_status=_emit_status)
    except OAuthError as exc:
        return _emit({"ok": False, "summary": str(exc)}, ok=False)
    except Exception as exc:  # noqa: BLE001
        return _emit({"ok": False, "summary": f"{type(exc).__name__}: {exc}"}, ok=False)

    payload: dict[str, object] = {
        "ok": result.ok,
        "summary": result.summary,
        "detail": result.detail,
        "action": result.action,
    }
    if result.account:
        payload["account"] = account_to_public_dict(result.account)
    return _emit(payload, ok=result.ok)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gitswitch",
        description="Internal JSON bridge for Git Switch IDE extensions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List saved accounts as JSON")

    status = sub.add_parser("status", help="Current identity + matched account")
    status.add_argument("--repo", default=None, help="Workspace / repo path")
    status.add_argument(
        "--scope",
        choices=("global", "local"),
        default=None,
        help="Force scope (default: local if repo, else global)",
    )

    switch = sub.add_parser("switch", help="Switch to an account")
    target = switch.add_mutually_exclusive_group(required=True)
    target.add_argument("--id", help="Account id")
    target.add_argument("--label", help="Account label")
    switch.add_argument("--repo", default=None, help="Workspace / repo path")
    switch.add_argument(
        "--scope",
        choices=("global", "local"),
        default=None,
        help="Force scope (default: local if repo, else global)",
    )

    sub.add_parser("add-github", help="Add/update account via GitHub browser sign-in")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "switch":
        return cmd_switch(args)
    if args.command == "add-github":
        return cmd_add_github(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
