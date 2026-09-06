from __future__ import annotations

import os
import threading
from typing import Callable

from gitswitch.oauth import (
    DEFAULT_CALLBACK_PORT,
    GITHUB_CLI_CLIENT_ID,
    OAuthError,
    OAuthResult,
    github_browser_login,
    github_device_login,
)
from gitswitch.store import OAuthConfigStore

# Optional override for builds that ship a custom OAuth app.
DEFAULT_GITHUB_CLIENT_ID = GITHUB_CLI_CLIENT_ID

StatusCallback = Callable[[str], None]


def resolve_github_client_id(store: OAuthConfigStore | None = None) -> str:
    env_id = os.environ.get("GITSWITCH_GITHUB_CLIENT_ID", "").strip()
    if env_id:
        return env_id
    config = store or OAuthConfigStore()
    local_id = config.github_client_id()
    if local_id:
        return local_id
    return DEFAULT_GITHUB_CLIENT_ID.strip() or GITHUB_CLI_CLIENT_ID


def sign_in_with_github(
    on_status: StatusCallback | None = None,
    open_browser: Callable[[str], bool] | None = None,
    store: OAuthConfigStore | None = None,
    client_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[OAuthResult, str]:
    """
    Browser device-code sign-in (no gh TUI, no localhost callback server).

    Uses GitHub's public device-flow client by default.
    """
    config = store or OAuthConfigStore()
    resolved = (client_id or resolve_github_client_id(config)).strip() or GITHUB_CLI_CLIENT_ID

    if cancel_event is not None and cancel_event.is_set():
        raise OAuthError("Sign-in cancelled.")

    try:
        result = github_device_login(
            client_id=resolved,
            on_status=on_status,
            open_browser=open_browser,
            cancel_event=cancel_event,
        )
        return result, "device"
    except OAuthError:
        # If a custom localhost OAuth app is configured, allow that fallback.
        if resolved != GITHUB_CLI_CLIENT_ID and config.github_client_id():
            if on_status:
                on_status("Device login failed — trying browser redirect…")
            result = github_browser_login(
                resolved,
                port=config.callback_port() or DEFAULT_CALLBACK_PORT,
                open_browser=open_browser,
            )
            return result, "oauth"
        raise


def account_payload_from_oauth(result: OAuthResult) -> dict[str, str]:
    return {
        "label": result.username,
        "name": result.name or result.username,
        "email": result.email,
        "pat_host": "github.com",
        "pat_username": result.username,
        "token": result.token,
    }


def describe_signin_requirements() -> str:
    return (
        "Click Add with GitHub → approve in your browser. "
        "No Client ID, PAT paste, or GitHub CLI required."
    )
