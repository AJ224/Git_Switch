from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from gitswitch.backend import GitBackend
from gitswitch.github_signin import describe_signin_requirements, sign_in_with_github
from gitswitch.models import Account, AuthMethod, ValidationResult, validate_account
from gitswitch.oauth import OAuthError, OAuthResult


class AccountDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, account: Account | None = None) -> None:
        super().__init__(parent)
        self.title("Edit account" if account else "Add account")
        self.resizable(False, False)
        self.result: Account | None = None
        self.pat_token = ""
        self.existing = account
        self.validation_var = tk.StringVar()
        self._oauth_in_progress = False
        self._oauth_cancel = threading.Event()

        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)

        identity = ttk.LabelFrame(container, text="Account identity", padding=12)
        identity.pack(fill="x", pady=(0, 10))

        self.fields: dict[str, ttk.Entry] = {}
        for row, (key, label) in enumerate(
            [
                ("label", "Label"),
                ("name", "Git user.name"),
                ("email", "Git user.email"),
            ]
        ):
            ttk.Label(identity, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(identity, width=44)
            entry.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
            if account:
                entry.insert(0, getattr(account, key))
            self.fields[key] = entry
        identity.columnconfigure(1, weight=1)

        auth = ttk.LabelFrame(container, text="Authentication", padding=12)
        auth.pack(fill="x", pady=(0, 10))

        initial_method = account.auth_method.value if account else AuthMethod.NONE.value
        self.auth_method = tk.StringVar(value=initial_method)
        for index, method in enumerate(AuthMethod):
            ttk.Radiobutton(
                auth,
                text=self._auth_label(method),
                value=method.value,
                variable=self.auth_method,
                command=self._toggle_auth_sections,
            ).grid(row=0, column=index, sticky="w", padx=(0, 12))

        self.auth_hint_var = tk.StringVar()
        self.auth_hint_label = ttk.Label(
            auth,
            textvariable=self.auth_hint_var,
            style="CardMuted.TLabel",
            wraplength=420,
            justify="left",
        )
        self.auth_hint_label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        self.ssh_frame = ttk.Frame(auth)
        self.ssh_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Label(self.ssh_frame, text="SSH key path").grid(row=0, column=0, sticky="w")
        self.fields["ssh_key"] = ttk.Entry(self.ssh_frame, width=36)
        self.fields["ssh_key"].grid(row=0, column=1, sticky="ew", padx=(10, 6))
        ttk.Button(self.ssh_frame, text="Browse", command=self._browse_key).grid(row=0, column=2)
        ttk.Label(self.ssh_frame, text="Host alias (optional)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.fields["host_alias"] = ttk.Entry(self.ssh_frame, width=36)
        self.fields["host_alias"].grid(row=1, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(8, 0))
        self.ssh_frame.columnconfigure(1, weight=1)

        self.pat_frame = ttk.Frame(auth)
        self.pat_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        self.oauth_btn = ttk.Button(
            self.pat_frame,
            text="Sign in with GitHub (browser)",
            style="Accent.TButton",
            command=self._start_github_oauth,
        )
        self.oauth_btn.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            self.pat_frame,
            text=describe_signin_requirements(),
            style="CardMuted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        editing_pat = bool(account and account.auth_method == AuthMethod.PAT)
        self.show_advanced = tk.BooleanVar(value=editing_pat)
        ttk.Checkbutton(
            self.pat_frame,
            text="Advanced: paste a token manually",
            variable=self.show_advanced,
            command=self._toggle_advanced_pat,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.advanced_pat = ttk.Frame(self.pat_frame)
        pat_rows = [
            ("pat_host", "HTTPS host"),
            ("pat_username", "Username"),
            ("pat", "Personal access token"),
        ]
        for row, (key, label) in enumerate(pat_rows):
            ttk.Label(self.advanced_pat, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(self.advanced_pat, width=36, show="•" if key == "pat" else "")
            entry.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
            if account and key != "pat":
                entry.insert(0, getattr(account, key))
            elif key == "pat_host" and not account:
                entry.insert(0, "github.com")
            self.fields[key] = entry
        self.advanced_pat.columnconfigure(1, weight=1)

        helper_hint = GitBackend.credential_helper_setup_hint()
        storage_label = GitBackend.credential_storage_label()
        helper_status = (
            f"Tokens are stored through Git's {storage_label}."
            if GitBackend.has_credential_helper()
            else f"No Git credential helper detected. {helper_hint}"
        )
        self.pat_helper_label = ttk.Label(
            self.pat_frame,
            text=helper_status,
            style="Error.TLabel" if not GitBackend.has_credential_helper() else "CardMuted.TLabel",
            wraplength=420,
            justify="left",
        )
        self.pat_helper_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.pat_frame.columnconfigure(0, weight=1)

        self.validation_label = ttk.Label(container, textvariable=self.validation_var, style="Error.TLabel")
        self.validation_label.pack(anchor="w", pady=(0, 8))

        buttons = ttk.Frame(container)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save account", style="Accent.TButton", command=self._save).pack(
            side="right", padx=(0, 8)
        )

        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.transient(parent)
        self.grab_set()
        self._toggle_auth_sections()
        self.fields["label"].focus_set()

    @staticmethod
    def _auth_label(method: AuthMethod) -> str:
        labels = {
            AuthMethod.NONE: "Identity only",
            AuthMethod.SSH: "SSH key",
            AuthMethod.PAT: "HTTPS / PAT",
        }
        return labels[method]

    def _toggle_auth_sections(self) -> None:
        method = AuthMethod(self.auth_method.get())
        hints = {
            AuthMethod.NONE: (
                "Identity only updates git user.name and user.email for commits. "
                "It does NOT change push/pull authentication. Use SSH or HTTPS / PAT "
                "if you need access to that account's repositories."
            ),
            AuthMethod.SSH: (
                "Switching will load this SSH key into ssh-agent for push/pull over SSH."
            ),
            AuthMethod.PAT: (
                "Sign in with GitHub opens your browser — approve access, done. "
                "No Client ID or Homepage URL."
            ),
        }
        self.auth_hint_var.set(hints[method])
        self.auth_hint_label.configure(
            style="Error.TLabel" if method == AuthMethod.NONE else "CardMuted.TLabel"
        )
        if method == AuthMethod.SSH:
            self.ssh_frame.grid()
            self.pat_frame.grid_remove()
        elif method == AuthMethod.PAT:
            self.pat_frame.grid()
            self.ssh_frame.grid_remove()
            self._toggle_advanced_pat()
        else:
            self.ssh_frame.grid_remove()
            self.pat_frame.grid_remove()

    def _toggle_advanced_pat(self) -> None:
        if self.show_advanced.get():
            self.advanced_pat.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        else:
            self.advanced_pat.grid_remove()

    def _browse_key(self) -> None:
        path = filedialog.askopenfilename(
            title="Select SSH private key",
            initialdir=str(Path.home() / ".ssh"),
        )
        if path:
            self.fields["ssh_key"].delete(0, tk.END)
            self.fields["ssh_key"].insert(0, path)

    def _start_github_oauth(self) -> None:
        if self._oauth_in_progress:
            self.validation_var.set("Sign-in already in progress…")
            return

        self._oauth_in_progress = True
        self._oauth_cancel = threading.Event()
        self.oauth_btn.configure(state="disabled")
        self.validation_var.set("Opening GitHub in your browser…")

        cancel_event = self._oauth_cancel

        def on_status(message: str) -> None:
            self.after(0, lambda m=message: self.validation_var.set(m))

        def reset_ui() -> None:
            self._oauth_in_progress = False
            try:
                self.oauth_btn.configure(state="normal")
            except tk.TclError:
                pass

        def worker() -> None:
            try:
                result, _method = sign_in_with_github(
                    on_status=on_status,
                    cancel_event=cancel_event,
                )
                self.after(0, lambda r=result: self._on_oauth_success(r))
            except OAuthError as exc:
                message = str(exc)
                self.after(0, lambda m=message: self._on_oauth_failure(m))
            except Exception as exc:  # noqa: BLE001
                message = f"{type(exc).__name__}: {exc}"
                self.after(0, lambda m=message: self._on_oauth_failure(m))
            finally:
                self.after(0, reset_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _set_entry(self, key: str, value: str, overwrite: bool = False) -> None:
        entry = self.fields[key]
        if not overwrite and entry.get().strip():
            return
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _on_oauth_success(self, result: OAuthResult) -> None:
        try:
            self._oauth_in_progress = False
            self.oauth_btn.configure(state="normal")
            self.auth_method.set(AuthMethod.PAT.value)
            self._toggle_auth_sections()
            self._set_entry("pat_host", "github.com", overwrite=True)
            self._set_entry("pat_username", result.username, overwrite=True)
            self._set_entry("pat", result.token, overwrite=True)
            self._set_entry("label", result.username)
            self._set_entry("name", result.name or result.username)
            if result.email:
                self._set_entry("email", result.email)
            self.show_advanced.set(True)
            self._toggle_advanced_pat()
            self.validation_var.set(
                f"Signed in as {result.username}. Review the fields, then click Save account."
            )
        except Exception as exc:  # noqa: BLE001
            self._oauth_in_progress = False
            try:
                self.oauth_btn.configure(state="normal")
            except tk.TclError:
                pass
            self.validation_var.set(str(exc))
            messagebox.showerror("GitHub sign-in failed", str(exc), parent=self)

    def _on_oauth_failure(self, message: str) -> None:
        self._oauth_in_progress = False
        try:
            self.oauth_btn.configure(state="normal")
        except tk.TclError:
            pass
        self.validation_var.set(message)
        if "cancelled" in message.lower():
            return
        messagebox.showerror("GitHub sign-in failed", message, parent=self)

    def _validate(self) -> ValidationResult:
        method = AuthMethod(self.auth_method.get())
        existing_has_pat = bool(self.existing and self.existing.has_pat)
        credentials_changed = bool(
            self.existing
            and existing_has_pat
            and (
                self.fields["pat_host"].get().strip() != self.existing.pat_host
                or self.fields["pat_username"].get().strip() != self.existing.pat_username
            )
        )
        return validate_account(
            label=self.fields["label"].get(),
            name=self.fields["name"].get(),
            email=self.fields["email"].get(),
            auth_method=method,
            ssh_key=self.fields["ssh_key"].get(),
            host_alias=self.fields["host_alias"].get(),
            pat_host=self.fields["pat_host"].get(),
            pat_username=self.fields["pat_username"].get(),
            pat_token=self.fields["pat"].get(),
            existing_has_pat=existing_has_pat,
            pat_credentials_changed=credentials_changed,
        )

    def _save(self) -> None:
        if self._oauth_in_progress:
            self.validation_var.set("Finish browser sign-in before saving.")
            return

        validation = self._validate()
        if not validation.ok:
            self.validation_var.set(validation.message)
            return

        method = AuthMethod(self.auth_method.get())
        account = Account(
            id=self.existing.id if self.existing else str(uuid4()),
            label=self.fields["label"].get().strip(),
            name=self.fields["name"].get().strip(),
            email=self.fields["email"].get().strip(),
            auth_method=method,
            ssh_key=self.fields["ssh_key"].get().strip() if method == AuthMethod.SSH else "",
            host_alias=self.fields["host_alias"].get().strip() if method == AuthMethod.SSH else "",
            pat_host=self.fields["pat_host"].get().strip() if method == AuthMethod.PAT else "",
            pat_username=self.fields["pat_username"].get().strip() if method == AuthMethod.PAT else "",
            has_pat=bool(self.existing and self.existing.has_pat and method == AuthMethod.PAT),
        )
        self.pat_token = self.fields["pat"].get().strip()
        self.result = account
        self.destroy()
