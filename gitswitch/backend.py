from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from gitswitch.models import Scope

SYSTEM = platform.system()


class GitBackend:
    @staticmethod
    def run(cmd: list[str], cwd: str | None = None, input_text: str | None = None) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return result.returncode == 0, output.strip()
        except FileNotFoundError:
            return False, f"Command not found: {cmd[0]}"
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as exc:
            return False, str(exc)

    @classmethod
    def get_current_identity(cls, scope: Scope = "global", repo_path: str | None = None) -> tuple[str, str]:
        cwd = repo_path if scope == "local" else None
        flag = "--global" if scope == "global" else "--local"

        ok_name, name = cls.run(["git", "config", flag, "user.name"], cwd=cwd)
        ok_email, email = cls.run(["git", "config", flag, "user.email"], cwd=cwd)
        return (name if ok_name else "", email if ok_email else "")

    @classmethod
    def set_identity(
        cls,
        name: str,
        email: str,
        scope: Scope = "global",
        repo_path: str | None = None,
    ) -> tuple[bool, str]:
        cwd = repo_path if scope == "local" else None
        flag = "--global" if scope == "global" else "--local"

        if scope == "local" and not cls.is_git_repo(repo_path):
            return False, f"'{repo_path}' is not a git repository."

        ok_name, out_name = cls.run(["git", "config", flag, "user.name", name], cwd=cwd)
        ok_email, out_email = cls.run(["git", "config", flag, "user.email", email], cwd=cwd)
        if ok_name and ok_email:
            return True, "Identity updated."
        return False, (out_name + "\n" + out_email).strip()

    @staticmethod
    def is_git_repo(path: str | None) -> bool:
        if not path:
            return False
        return (Path(path) / ".git").exists()

    @classmethod
    def ssh_add_key(cls, key_path: str) -> tuple[bool, str]:
        if not key_path:
            return True, "No SSH key configured."
        expanded = str(Path(key_path).expanduser())
        if not Path(expanded).exists():
            return False, f"SSH key not found: {expanded}"
        ok, output = cls.run(["ssh-add", expanded])
        return ok, output or "SSH key added to agent."

    @classmethod
    def test_ssh(cls, host_alias: str) -> tuple[bool, str]:
        if not host_alias:
            return True, "No host alias configured."
        _, output = cls.run(["ssh", "-T", f"git@{host_alias}"])
        return True, output

    @staticmethod
    def normalize_host(host: str) -> str:
        parsed = urlparse(host if "://" in host else f"https://{host}")
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            return ""
        return parsed.netloc

    @classmethod
    def configured_credential_helpers(cls) -> list[str]:
        ok, helpers = cls.run(["git", "config", "--global", "--get-all", "credential.helper"])
        if not ok or not helpers.strip():
            return []
        return [line.strip() for line in helpers.splitlines() if line.strip()]

    @staticmethod
    def recommended_credential_helper() -> str:
        if SYSTEM == "Darwin":
            return "osxkeychain"
        if SYSTEM == "Windows":
            return "manager"
        libsecret = shutil.which("git-credential-libsecret")
        if libsecret:
            return libsecret
        return "libsecret"

    @classmethod
    def credential_storage_label(cls) -> str:
        labels = {
            "Darwin": "macOS Keychain",
            "Windows": "Git Credential Manager",
            "Linux": "system credential store",
        }
        return labels.get(SYSTEM, "Git credential helper")

    @classmethod
    def credential_helper_setup_hint(cls) -> str:
        hints = {
            "Darwin": "Run: git config --global credential.helper osxkeychain",
            "Windows": "Install Git for Windows with Git Credential Manager enabled.",
            "Linux": "Install libsecret support, e.g. sudo apt install git-credential-libsecret, "
            "then run: git config --global credential.helper /usr/share/git-core/contrib/credential/libsecret/git-credential-libsecret",
        }
        return hints.get(SYSTEM, "Configure a Git credential helper globally.")

    @classmethod
    def has_credential_helper(cls) -> bool:
        return bool(cls.configured_credential_helpers())

    @classmethod
    def ensure_credential_helper(cls) -> tuple[bool, str]:
        if cls.has_credential_helper():
            return True, ""

        helper = cls.recommended_credential_helper()
        ok, _ = cls.run(["git", "config", "--global", "--add", "credential.helper", helper])
        if ok and cls.has_credential_helper():
            return True, ""

        return False, (
            f"No Git credential helper is configured. PAT storage requires {cls.credential_storage_label()}. "
            f"{cls.credential_helper_setup_hint()}"
        )

    @staticmethod
    def _credential_payload(host: str, username: str, token: str = "") -> str:
        lines = [
            "protocol=https",
            f"host={host}",
            f"username={username}",
        ]
        if token:
            lines.append(f"password={token}")
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def store_pat(cls, host: str, username: str, token: str) -> tuple[bool, str]:
        normalized_host = cls.normalize_host(host)
        if not normalized_host or not username or not token:
            return False, "HTTPS host, username, and PAT are required."

        ok, message = cls.ensure_credential_helper()
        if not ok:
            return False, message

        credential = cls._credential_payload(normalized_host, username, token)
        ok, output = cls.run(["git", "credential", "approve"], input_text=credential)
        if not ok:
            return False, output or f"Could not save PAT via {cls.credential_storage_label()}."

        return True, f"PAT saved securely via {cls.credential_storage_label()}."

    @classmethod
    def activate_pat(
        cls,
        host: str,
        username: str,
        scope: Scope = "global",
        repo_path: str | None = None,
    ) -> tuple[bool, str]:
        normalized_host = cls.normalize_host(host)
        if not normalized_host or not username:
            return False, "PAT host and username are missing."
        cwd = repo_path if scope == "local" else None
        flag = "--local" if scope == "local" else "--global"
        key = f"credential.https://{normalized_host}.username"
        return cls.run(["git", "config", flag, key, username], cwd=cwd)

    @classmethod
    def delete_pat(cls, host: str, username: str) -> None:
        normalized_host = cls.normalize_host(host)
        if not normalized_host or not username:
            return
        credential = cls._credential_payload(normalized_host, username)
        cls.run(["git", "credential", "reject"], input_text=credential)
