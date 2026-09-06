import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gitswitch.backend import GitBackend
from gitswitch.models import Account, AuthMethod, validate_account
from gitswitch.github_signin import (
    account_payload_from_oauth,
    describe_signin_requirements,
    resolve_github_client_id,
    sign_in_with_github,
)
from gitswitch.oauth import (
    OAuthError,
    OAuthResult,
    build_authorize_url,
    exchange_code_for_token,
    generate_pkce_pair,
)
from gitswitch.store import AccountStore, OAuthConfigStore, ThemePreferenceStore
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

    def test_oauth_client_id_round_trip(self) -> None:
        oauth_file = self.config_dir / "oauth.json"
        with patch("gitswitch.store.CONFIG_DIR", self.config_dir), patch(
            "gitswitch.store.OAUTH_FILE", oauth_file
        ):
            store = OAuthConfigStore()
            store.save_github_client_id("Iv1.example", callback_port=8741)
            self.assertEqual(store.github_client_id(), "Iv1.example")
            self.assertEqual(store.callback_port(), 8741)


class OAuthHelperTests(unittest.TestCase):
    def test_pkce_challenge_is_s256(self) -> None:
        verifier, challenge = generate_pkce_pair()
        self.assertTrue(verifier)
        self.assertTrue(challenge)
        self.assertNotIn("=", challenge)
        self.assertNotEqual(verifier, challenge)

    def test_authorize_url_includes_pkce_params(self) -> None:
        url = build_authorize_url(
            client_id="abc123",
            redirect_uri="http://127.0.0.1:8741/callback",
            state="state-value",
            code_challenge="challenge-value",
        )
        self.assertIn("client_id=abc123", url)
        self.assertIn("code_challenge=challenge-value", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=state-value", url)

    def test_exchange_code_rejects_error_payload(self) -> None:
        with patch(
            "gitswitch.oauth._post_form",
            return_value={"error": "incorrect_client_credentials", "error_description": "Bad client"},
        ):
            with self.assertRaises(OAuthError) as ctx:
                exchange_code_for_token(
                    "abc",
                    "code",
                    "http://127.0.0.1:8741/callback",
                    "verifier",
                )
        self.assertIn("Bad client", str(ctx.exception))


class GitHubSignInHelperTests(unittest.TestCase):
    def test_resolve_client_id_prefers_env(self) -> None:
        with patch.dict("os.environ", {"GITSWITCH_GITHUB_CLIENT_ID": "env-id"}), patch(
            "gitswitch.github_signin.DEFAULT_GITHUB_CLIENT_ID", ""
        ), patch.object(OAuthConfigStore, "github_client_id", return_value="file-id"):
            self.assertEqual(resolve_github_client_id(), "env-id")

    def test_describe_requirements(self) -> None:
        text = describe_signin_requirements()
        self.assertIn("browser", text.lower())
        self.assertIn("add with github", text.lower())

    def test_account_payload_from_oauth(self) -> None:
        result = OAuthResult(
            username="octocat",
            token="gho_example",
            name="The Octocat",
            email="octocat@users.noreply.github.com",
        )
        payload = account_payload_from_oauth(result)
        self.assertEqual(payload["label"], "octocat")
        self.assertEqual(payload["name"], "The Octocat")
        self.assertEqual(payload["email"], "octocat@users.noreply.github.com")
        self.assertEqual(payload["pat_host"], "github.com")
        self.assertEqual(payload["pat_username"], "octocat")
        self.assertEqual(payload["token"], "gho_example")

    def test_sign_in_uses_device_flow(self) -> None:
        fake = OAuthResult(username="octocat", token="gho_x", name="Octo", email="o@example.com")
        with patch("gitswitch.github_signin.github_device_login", return_value=fake) as device_login, patch(
            "gitswitch.github_signin.github_browser_login"
        ) as oauth_login:
            result, method = sign_in_with_github()
        self.assertEqual(method, "device")
        self.assertEqual(result.username, "octocat")
        device_login.assert_called_once()
        oauth_login.assert_not_called()


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

    def test_activate_pat_sets_credential_username(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], cwd: str | None = None, input_text: str | None = None) -> tuple[bool, str]:
            calls.append(cmd)
            return True, ""

        with patch.object(GitBackend, "run", side_effect=fake_run), patch(
            "gitswitch.backend.SYSTEM", "Darwin"
        ):
            ok, message = GitBackend.activate_pat("github.com", "octocat", scope="global")

        self.assertTrue(ok)
        self.assertIn("octocat", message)
        self.assertIn("https", message.lower())
        self.assertEqual(
            calls[0],
            ["git", "config", "--global", "credential.https://github.com.username", "octocat"],
        )

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
