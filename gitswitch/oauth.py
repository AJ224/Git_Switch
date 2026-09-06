from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable


DEFAULT_CALLBACK_PORT = 8741
# Public OAuth App client ID used by GitHub CLI for device/browser login (no secret).
GITHUB_CLI_CLIENT_ID = "178c6fc778ccc68e1d6a"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_API_USER_URL = "https://api.github.com/user"
GITHUB_API_EMAILS_URL = "https://api.github.com/user/emails"
OAUTH_SCOPES = "repo read:user user:email"
DEVICE_URL = "https://github.com/login/device"


class OAuthError(Exception):
    """Raised when the browser OAuth flow fails or is cancelled."""


@dataclass
class OAuthResult:
    username: str
    token: str
    name: str = ""
    email: str = ""


StatusCallback = Callable[[str], None]


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _curl_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, str]:
    cmd = ["curl", "-sS", "-L", "--max-time", str(int(timeout)), "-X", method, "-w", "\n%{http_code}"]
    for key, value in (headers or {}).items():
        cmd.extend(["-H", f"{key}: {value}"])
    if data is not None:
        cmd.extend(["--data-binary", data.decode("utf-8", errors="replace")])
    cmd.append(url)
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    except FileNotFoundError as exc:
        raise OAuthError("Could not reach GitHub (curl is not available).") from exc
    except subprocess.TimeoutExpired as exc:
        raise OAuthError("Timed out contacting GitHub.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "curl failed").strip()
        raise OAuthError(f"Could not reach GitHub: {detail}")
    body = completed.stdout or ""
    if "\n" not in body:
        raise OAuthError("Unexpected response from GitHub.")
    payload, status_text = body.rsplit("\n", 1)
    try:
        status = int(status_text.strip())
    except ValueError as exc:
        raise OAuthError("Unexpected response from GitHub.") from exc
    return status, payload


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, str]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail
    except Exception:
        # macOS python.org installs often lack CA certs; curl usually works.
        return _curl_request(url, method=method, headers=headers, data=data, timeout=timeout)


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorize_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = OAUTH_SCOPES,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{query}"


def _post_form(url: str, data: dict[str, str], accept_json: bool = True) -> dict[str, object]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if accept_json:
        headers["Accept"] = "application/json"
    status, raw = _http_request(url, method="POST", headers=headers, data=body)
    if status >= 400:
        raise OAuthError(f"GitHub request failed ({status}): {raw}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OAuthError("Unexpected response from GitHub.") from exc
    if not isinstance(payload, dict):
        raise OAuthError("Unexpected response from GitHub.")
    return payload


def _get_json(url: str, token: str) -> object:
    status, raw = _http_request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "GitAccountSwitcher",
        },
    )
    if status >= 400:
        raise OAuthError(f"GitHub API request failed ({status}): {raw}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OAuthError("Unexpected GitHub API response.") from exc


def exchange_code_for_token(
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> str:
    payload = _post_form(
        GITHUB_TOKEN_URL,
        {
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    error = payload.get("error")
    if error:
        description = payload.get("error_description") or error
        raise OAuthError(f"GitHub authorization failed: {description}")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise OAuthError("GitHub did not return an access token.")
    return token


def fetch_github_profile(token: str) -> OAuthResult:
    user = _get_json(GITHUB_API_USER_URL, token)
    if not isinstance(user, dict):
        raise OAuthError("Unexpected GitHub user profile response.")

    username = str(user.get("login") or "").strip()
    if not username:
        raise OAuthError("GitHub profile did not include a username.")

    name = str(user.get("name") or username).strip()
    email = str(user.get("email") or "").strip()

    if not email:
        emails = _get_json(GITHUB_API_EMAILS_URL, token)
        if isinstance(emails, list):
            primary = next(
                (
                    item
                    for item in emails
                    if isinstance(item, dict) and item.get("primary") and item.get("verified")
                ),
                None,
            )
            if primary:
                email = str(primary.get("email") or "").strip()
            elif emails and isinstance(emails[0], dict):
                email = str(emails[0].get("email") or "").strip()

    return OAuthResult(username=username, token=token, name=name, email=email)


def request_device_code(client_id: str = GITHUB_CLI_CLIENT_ID, scope: str = OAUTH_SCOPES) -> dict[str, object]:
    payload = _post_form(
        GITHUB_DEVICE_CODE_URL,
        {"client_id": client_id, "scope": scope},
    )
    required = ("device_code", "user_code", "verification_uri")
    if any(not payload.get(key) for key in required):
        raise OAuthError("GitHub did not return a device login code.")
    return payload


def poll_device_token(
    device_code: str,
    client_id: str = GITHUB_CLI_CLIENT_ID,
    interval: float = 5.0,
    expires_in: float = 900.0,
    on_status: StatusCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    notify = on_status or (lambda _msg: None)
    cancel = cancel_event or threading.Event()
    deadline = time.time() + max(30.0, expires_in)
    sleep_for = max(1.0, interval)
    last_notice = 0.0

    while time.time() < deadline:
        if cancel.is_set():
            raise OAuthError("Sign-in cancelled.")

        payload = _post_form(
            GITHUB_TOKEN_URL,
            {
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        token = payload.get("access_token")
        if isinstance(token, str) and token:
            return token

        error = str(payload.get("error") or "")
        if error == "authorization_pending":
            pass
        elif error == "slow_down":
            sleep_for += 5
        elif error in {"expired_token", "access_denied", "unsupported_grant_type", "incorrect_device_code"}:
            description = payload.get("error_description") or error
            raise OAuthError(f"GitHub authorization failed: {description}")
        elif error:
            description = payload.get("error_description") or error
            raise OAuthError(f"GitHub authorization failed: {description}")

        now = time.time()
        if now - last_notice >= 10:
            remaining = max(0, int(deadline - now))
            notify(f"Waiting for browser approval… {remaining}s left")
            last_notice = now

        # Sleep in small slices so cancel is responsive.
        end = time.time() + sleep_for
        while time.time() < end:
            if cancel.is_set():
                raise OAuthError("Sign-in cancelled.")
            time.sleep(0.2)

    raise OAuthError(
        "Timed out waiting for GitHub authorization.\n"
        "Approve the request in your browser, then try again."
    )


def github_device_login(
    client_id: str = GITHUB_CLI_CLIENT_ID,
    on_status: StatusCallback | None = None,
    open_browser: Callable[[str], bool] | None = None,
    cancel_event: threading.Event | None = None,
    timeout_seconds: float | None = None,
) -> OAuthResult:
    """
    One-click browser sign-in via GitHub device flow.

    No local callback server, no gh TUI automation.
    """
    notify = on_status or (lambda _msg: None)
    notify("Requesting GitHub device code…")
    payload = request_device_code(client_id=client_id)
    user_code = str(payload["user_code"])
    device_code = str(payload["device_code"])
    verification_uri = str(payload.get("verification_uri") or DEVICE_URL)
    interval = float(payload.get("interval") or 5)
    expires_in = float(payload.get("expires_in") or 900)
    if timeout_seconds is not None:
        expires_in = min(expires_in, timeout_seconds)

    verify_url = f"{DEVICE_URL}?user_code={urllib.parse.quote(user_code)}"
    notify(f"Code {user_code} — confirm in your browser…")
    opener = open_browser or _open_browser
    opened = opener(verify_url)
    if not opened:
        opener(verification_uri)
    notify(f"Browser opened. Enter code {user_code} if asked, then approve…")

    token = poll_device_token(
        device_code=device_code,
        client_id=client_id,
        interval=interval,
        expires_in=expires_in,
        on_status=on_status,
        cancel_event=cancel_event,
    )
    notify("Authorized — loading GitHub profile…")
    return fetch_github_profile(token)


def _make_callback_handler(
    expected_state: str,
    result_holder: dict[str, str | None],
    done: threading.Event,
) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in ("/callback", "/"):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            params = urllib.parse.parse_qs(parsed.query)
            error = (params.get("error") or [None])[0]
            state = (params.get("state") or [None])[0]
            code = (params.get("code") or [None])[0]

            if error:
                description = (params.get("error_description") or [error])[0]
                result_holder["error"] = str(description)
                body = b"<html><body><h2>Authorization denied</h2><p>You can close this tab.</p></body></html>"
                self.send_response(400)
            elif state != expected_state:
                result_holder["error"] = "Invalid OAuth state. Try again."
                body = b"<html><body><h2>Invalid state</h2><p>You can close this tab.</p></body></html>"
                self.send_response(400)
            elif not code:
                result_holder["error"] = "GitHub did not return an authorization code."
                body = b"<html><body><h2>Missing code</h2><p>You can close this tab.</p></body></html>"
                self.send_response(400)
            else:
                result_holder["code"] = str(code)
                body = (
                    b"<html><body><h2>Signed in</h2>"
                    b"<p>You can close this tab and return to Git Account Switcher.</p>"
                    b"</body></html>"
                )
                self.send_response(200)

            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    return CallbackHandler


def wait_for_callback(port: int, expected_state: str, timeout_seconds: float = 180.0) -> str:
    result_holder: dict[str, str | None] = {"code": None, "error": None}
    done = threading.Event()
    handler = _make_callback_handler(expected_state, result_holder, done)

    try:
        server = HTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise OAuthError(
            f"Could not start local callback server on port {port}. "
            f"Close whatever is using that port, or choose another port in OAuth settings. ({exc})"
        ) from exc

    server.timeout = 0.5

    def serve() -> None:
        while not done.is_set():
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    finished = done.wait(timeout_seconds)
    server.server_close()
    thread.join(timeout=2)

    if not finished:
        raise OAuthError("Timed out waiting for browser authorization.")
    if result_holder.get("error"):
        raise OAuthError(str(result_holder["error"]))
    code = result_holder.get("code")
    if not code:
        raise OAuthError("Authorization ended without a code.")
    return code


def _open_browser(url: str) -> bool:
    """Open a URL reliably from a background thread (webbrowser can no-op off the main thread)."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", url], check=False, capture_output=True, timeout=10)
            return True
        if system == "Windows":
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        subprocess.run(["xdg-open", url], check=False, capture_output=True, timeout=10)
        return True
    except Exception:
        return webbrowser.open(url)


def github_browser_login(
    client_id: str,
    port: int = DEFAULT_CALLBACK_PORT,
    open_browser: Callable[[str], bool] | None = None,
    timeout_seconds: float = 180.0,
) -> OAuthResult:
    client_id = client_id.strip()
    if not client_id:
        raise OAuthError("GitHub OAuth client ID is not configured.")

    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = generate_pkce_pair()
    authorize_url = build_authorize_url(client_id, redirect_uri, state, code_challenge)

    # Start listening before opening the browser so the redirect is not missed.
    result_holder: dict[str, str | None] = {"code": None, "error": None}
    done = threading.Event()
    handler = _make_callback_handler(state, result_holder, done)
    try:
        server = HTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise OAuthError(
            f"Could not start local callback server on port {port}. "
            f"Close whatever is using that port, or choose another port in OAuth settings. ({exc})"
        ) from exc

    server.timeout = 0.5

    def serve() -> None:
        while not done.is_set():
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    opener = open_browser or _open_browser
    if not opener(authorize_url):
        server.server_close()
        raise OAuthError(
            f"Could not open a browser. Open this URL manually:\n{authorize_url}"
        )

    finished = done.wait(timeout_seconds)
    server.server_close()
    thread.join(timeout=2)

    if not finished:
        raise OAuthError("Timed out waiting for browser authorization.")
    if result_holder.get("error"):
        raise OAuthError(str(result_holder["error"]))
    code = result_holder.get("code")
    if not code:
        raise OAuthError("Authorization ended without a code.")

    token = exchange_code_for_token(client_id, code, redirect_uri, code_verifier)
    return fetch_github_profile(token)
