from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal
from uuid import uuid4


Scope = Literal["global", "local"]


class AuthMethod(str, Enum):
    NONE = "none"
    SSH = "ssh"
    PAT = "pat"


@dataclass
class Account:
    label: str
    name: str
    email: str
    id: str = field(default_factory=lambda: str(uuid4()))
    auth_method: AuthMethod = AuthMethod.NONE
    ssh_key: str = ""
    host_alias: str = ""
    pat_host: str = ""
    pat_username: str = ""
    has_pat: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "name": self.name,
            "email": self.email,
            "auth_method": self.auth_method.value,
            "ssh_key": self.ssh_key,
            "host_alias": self.host_alias,
            "pat_host": self.pat_host,
            "pat_username": self.pat_username,
            "has_pat": self.has_pat,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Account:
        auth_raw = str(data.get("auth_method", AuthMethod.NONE.value))
        auth_method = AuthMethod(auth_raw) if auth_raw in AuthMethod._value2member_map_ else AuthMethod.NONE

        ssh_key = str(data.get("ssh_key", "") or "")
        host_alias = str(data.get("host_alias", "") or "")
        pat_host = str(data.get("pat_host", "") or "")
        pat_username = str(data.get("pat_username", "") or "")
        has_pat = bool(data.get("has_pat", False))

        if auth_method == AuthMethod.NONE:
            if has_pat:
                auth_method = AuthMethod.PAT
            elif ssh_key:
                auth_method = AuthMethod.SSH

        return cls(
            id=str(data.get("id") or uuid4()),
            label=str(data.get("label", "")),
            name=str(data.get("name", "")),
            email=str(data.get("email", "")),
            auth_method=auth_method,
            ssh_key=ssh_key,
            host_alias=host_alias,
            pat_host=pat_host,
            pat_username=pat_username,
            has_pat=has_pat,
        )


@dataclass
class ValidationResult:
    ok: bool
    message: str = ""


def validate_account(
    label: str,
    name: str,
    email: str,
    auth_method: AuthMethod,
    ssh_key: str = "",
    host_alias: str = "",
    pat_host: str = "",
    pat_username: str = "",
    pat_token: str = "",
    existing_has_pat: bool = False,
    pat_credentials_changed: bool = False,
) -> ValidationResult:
    if not label.strip():
        return ValidationResult(False, "Label is required.")
    if not name.strip():
        return ValidationResult(False, "Git user.name is required.")
    if not email.strip() or "@" not in email:
        return ValidationResult(False, "A valid git user.email is required.")

    if auth_method == AuthMethod.SSH and not ssh_key.strip():
        return ValidationResult(False, "SSH key path is required for SSH authentication.")

    if auth_method == AuthMethod.PAT:
        if not pat_host.strip():
            return ValidationResult(False, "HTTPS host is required for PAT authentication.")
        if not pat_username.strip():
            return ValidationResult(False, "PAT username is required.")
        if not pat_token.strip() and not existing_has_pat:
            return ValidationResult(False, "PAT token is required.")
        if pat_credentials_changed and not pat_token.strip():
            return ValidationResult(False, "Enter the PAT again after changing host or username.")

    if auth_method == AuthMethod.SSH and host_alias.strip() and " " in host_alias:
        return ValidationResult(False, "SSH host alias cannot contain spaces.")

    return ValidationResult(True)
