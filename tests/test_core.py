import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gitswitch.backend import GitBackend
from gitswitch.models import Account, AuthMethod, validate_account
from gitswitch.store import AccountStore, ThemePreferenceStore
from gitswitch.theme import toggle_theme


class HostNormalizationTests(unittest.TestCase):
    def test_accepts_plain_host(self) -> None:
        self.assertEqual(GitBackend.normalize_host("github.com"), "github.com")

    def test_accepts_https_url(self) -> None:
        self.assertEqual(GitBackend.normalize_host("https://gitlab.com/"), "gitlab.com")

    def test_rejects_invalid_host(self) -> None:
        self.assertEqual(GitBackend.normalize_host("http://github.com"), "")
        self.assertEqual(GitBackend.normalize_host("https://github.com/path"), "")


class ValidationTests(unittest.TestCase):
    def test_requires_core_identity_fields(self) -> None:
        result = validate_account("", "", "", AuthMethod.NONE)
        self.assertFalse(result.ok)

    def test_requires_pat_fields(self) -> None:
        result = validate_account(
            "Work",
            "Dev",
            "dev@example.com",
            AuthMethod.PAT,
            pat_host="github.com",
            pat_username="dev",
        )
        self.assertFalse(result.ok)

    def test_requires_pat_again_when_credentials_change(self) -> None:
        result = validate_account(
            "Work",
            "Dev",
            "dev@example.com",
            AuthMethod.PAT,
            pat_host="gitlab.com",
            pat_username="dev",
            existing_has_pat=True,
            pat_credentials_changed=True,
        )
        self.assertFalse(result.ok)


class AccountModelTests(unittest.TestCase):
    def test_migrates_legacy_ssh_account(self) -> None:
        account = Account.from_dict(
            {
                "label": "Work",
                "name": "Dev",
                "email": "dev@example.com",
                "ssh_key": "/Users/dev/.ssh/id_ed25519",
            }
        )
        self.assertEqual(account.auth_method, AuthMethod.SSH)

    def test_migrates_legacy_pat_account(self) -> None:
        account = Account.from_dict(
            {
                "label": "Work",
                "name": "Dev",
                "email": "dev@example.com",
                "has_pat": True,
                "pat_host": "github.com",
                "pat_username": "dev",
            }
        )
        self.assertEqual(account.auth_method, AuthMethod.PAT)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_dir = Path(self.temp_dir.name) / ".gitswitch"
        self.config_file = self.config_dir / "accounts.json"
        self.theme_file = self.config_dir / "theme.json"

    def test_does_not_persist_pat_token(self) -> None:
        with patch("gitswitch.store.CONFIG_DIR", self.config_dir), patch(
            "gitswitch.store.CONFIG_FILE", self.config_file
        ):
            store = AccountStore()
            account = Account(
                label="Work",
                name="Dev",
                email="dev@example.com",
                auth_method=AuthMethod.PAT,
                pat_host="github.com",
                pat_username="dev",
                has_pat=True,
            )
            store.add(account)

        raw = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.assertNotIn("pat", raw[0])
        self.assertTrue(raw[0]["has_pat"])

    def test_theme_preference_round_trip(self) -> None:
        with patch("gitswitch.store.CONFIG_DIR", self.config_dir), patch(
            "gitswitch.store.THEME_FILE", self.theme_file
        ):
            store = ThemePreferenceStore()
            store.save("dark")
            self.assertEqual(store.load(), "dark")

    def test_theme_defaults_to_dark(self) -> None:
        with patch("gitswitch.store.CONFIG_DIR", self.config_dir), patch(
            "gitswitch.store.THEME_FILE", self.theme_file
        ):
            self.assertEqual(ThemePreferenceStore().load(), "dark")


class ThemeTests(unittest.TestCase):
    def test_toggle_theme(self) -> None:
        dark = toggle_theme("light")
        light = toggle_theme("dark")
        self.assertEqual(dark.name, "dark")
        self.assertEqual(light.name, "light")


class CredentialPayloadTests(unittest.TestCase):
    def test_store_payload_includes_token(self) -> None:
        payload = GitBackend._credential_payload("github.com", "dev", "secret-token")
        self.assertIn("protocol=https", payload)
        self.assertIn("host=github.com", payload)
        self.assertIn("username=dev", payload)
        self.assertIn("password=secret-token", payload)

    def test_erase_payload_omits_token(self) -> None:
        payload = GitBackend._credential_payload("github.com", "dev")
        self.assertIn("username=dev", payload)
        self.assertNotIn("password=", payload)


class CredentialHelperTests(unittest.TestCase):
    def test_has_helper_when_configured(self) -> None:
        with patch.object(GitBackend, "configured_credential_helpers", return_value=["osxkeychain"]):
            self.assertTrue(GitBackend.has_credential_helper())

    def test_missing_helper_returns_actionable_message(self) -> None:
        with patch.object(GitBackend, "configured_credential_helpers", return_value=[]), patch.object(
            GitBackend, "run", return_value=(False, "config failed")
        ), patch("gitswitch.backend.SYSTEM", "Linux"):
            ok, message = GitBackend.ensure_credential_helper()
            self.assertFalse(ok)
            self.assertIn("credential helper", message.lower())
            self.assertIn("libsecret", message.lower())

    def test_store_pat_uses_git_credential_approve(self) -> None:
        calls: list[tuple[list[str], str | None]] = []

        def fake_run(cmd: list[str], cwd: str | None = None, input_text: str | None = None) -> tuple[bool, str]:
            calls.append((cmd, input_text))
            if cmd[:3] == ["git", "config", "--global"]:
                return True, ""
            return True, ""

        with patch.object(GitBackend, "run", side_effect=fake_run), patch.object(
            GitBackend, "configured_credential_helpers", return_value=["manager"]
        ):
            ok, message = GitBackend.store_pat("github.com", "dev", "secret-token")

        self.assertTrue(ok)
        self.assertIn("saved securely", message.lower())
        approve_call = next(call for call in calls if call[0][:3] == ["git", "credential", "approve"])
        self.assertIn("password=secret-token", approve_call[1] or "")

    def test_store_pat_fails_without_helper(self) -> None:
        with patch.object(GitBackend, "configured_credential_helpers", return_value=[]), patch.object(
            GitBackend, "run", return_value=(False, "config failed")
        ), patch("gitswitch.backend.SYSTEM", "Windows"):
            ok, message = GitBackend.store_pat("github.com", "dev", "secret-token")

        self.assertFalse(ok)
        self.assertIn("credential helper", message.lower())

    def test_delete_pat_uses_git_credential_reject(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], cwd: str | None = None, input_text: str | None = None) -> tuple[bool, str]:
            calls.append(cmd)
            return True, ""

        with patch.object(GitBackend, "run", side_effect=fake_run):
            GitBackend.delete_pat("github.com", "dev")

        self.assertEqual(calls[0][:3], ["git", "credential", "reject"])

    def test_recommended_helper_per_platform(self) -> None:
        with patch("gitswitch.backend.SYSTEM", "Darwin"):
            self.assertEqual(GitBackend.recommended_credential_helper(), "osxkeychain")
        with patch("gitswitch.backend.SYSTEM", "Windows"):
            self.assertEqual(GitBackend.recommended_credential_helper(), "manager")

    def test_storage_label_per_platform(self) -> None:
        with patch("gitswitch.backend.SYSTEM", "Darwin"):
            self.assertEqual(GitBackend.credential_storage_label(), "macOS Keychain")
        with patch("gitswitch.backend.SYSTEM", "Windows"):
            self.assertEqual(GitBackend.credential_storage_label(), "Git Credential Manager")


if __name__ == "__main__":
    unittest.main()
