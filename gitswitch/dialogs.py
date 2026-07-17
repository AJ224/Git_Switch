from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from gitswitch.backend import GitBackend
from gitswitch.models import Account, AuthMethod, ValidationResult, validate_account


class AccountDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, account: Account | None = None) -> None:
        super().__init__(parent)
        self.title("Edit account" if account else "Add account")
        self.resizable(False, False)
        self.result: Account | None = None
        self.pat_token = ""
        self.existing = account
        self.validation_var = tk.StringVar()

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

        self.ssh_frame = ttk.Frame(auth)
        self.ssh_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Label(self.ssh_frame, text="SSH key path").grid(row=0, column=0, sticky="w")
        self.fields["ssh_key"] = ttk.Entry(self.ssh_frame, width=36)
        self.fields["ssh_key"].grid(row=0, column=1, sticky="ew", padx=(10, 6))
        ttk.Button(self.ssh_frame, text="Browse", command=self._browse_key).grid(row=0, column=2)
        ttk.Label(self.ssh_frame, text="Host alias (optional)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.fields["host_alias"] = ttk.Entry(self.ssh_frame, width=36)
        self.fields["host_alias"].grid(row=1, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(8, 0))
        self.ssh_frame.columnconfigure(1, weight=1)

        self.pat_frame = ttk.Frame(auth)
        self.pat_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        pat_rows = [
            ("pat_host", "HTTPS host"),
            ("pat_username", "Username"),
            ("pat", "Personal access token"),
        ]
        for row, (key, label) in enumerate(pat_rows):
            ttk.Label(self.pat_frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(self.pat_frame, width=36, show="•" if key == "pat" else "")
            entry.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
            if account and key != "pat":
                entry.insert(0, getattr(account, key))
            self.fields[key] = entry
        self.pat_frame.columnconfigure(1, weight=1)

        helper_hint = GitBackend.credential_helper_setup_hint()
        storage_label = GitBackend.credential_storage_label()
        helper_status = (
            f"PATs are stored through Git's {storage_label}."
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
        self.pat_helper_label.grid(row=len(pat_rows), column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.validation_label = ttk.Label(container, textvariable=self.validation_var, style="Error.TLabel")
        self.validation_label.pack(anchor="w", pady=(0, 8))

        buttons = ttk.Frame(container)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save account", style="Accent.TButton", command=self._save).pack(side="right", padx=(0, 8))

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
        if method == AuthMethod.SSH:
            self.ssh_frame.grid()
            self.pat_frame.grid_remove()
        elif method == AuthMethod.PAT:
            self.pat_frame.grid()
            self.ssh_frame.grid_remove()
        else:
            self.ssh_frame.grid_remove()
            self.pat_frame.grid_remove()

    def _browse_key(self) -> None:
        path = filedialog.askopenfilename(
            title="Select SSH private key",
            initialdir=str(Path.home() / ".ssh"),
        )
        if path:
            self.fields["ssh_key"].delete(0, tk.END)
            self.fields["ssh_key"].insert(0, path)

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
        validation = self._validate()
        if not validation.ok:
            self.validation_var.set(validation.message)
            return

        account = Account(
            id=self.existing.id if self.existing else "",
            label=self.fields["label"].get().strip(),
            name=self.fields["name"].get().strip(),
            email=self.fields["email"].get().strip(),
            auth_method=method,
            ssh_key=self.fields["ssh_key"].get().strip() if method == AuthMethod.SSH else "",
            host_alias=self.fields["host_alias"].get().strip() if method == AuthMethod.SSH else "",
            pat_host=self.fields["pat_host"].get().strip() if method == AuthMethod.PAT else "",
            pat_username=self.fields["pat_username"].get().strip() if method == AuthMethod.PAT else "",
            has_pat=self.existing.has_pat if self.existing else False,
        )
        self.pat_token = self.fields["pat"].get().strip()
        self.result = account
        self.destroy()
