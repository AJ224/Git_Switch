from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from gitswitch.backend import GitBackend
from gitswitch.dialogs import AccountDialog
from gitswitch.models import Account, AuthMethod, Scope
from gitswitch.store import AccountStore, ThemePreferenceStore
from gitswitch.theme import DARK, LIGHT, ThemeManager, toggle_theme

CARD_FRAME = "Card.TFrame"
CARD_LABEL = "Card.TLabel"
SECTION_LABEL = "Section.TLabel"


class GitSwitcherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Git Account Switcher")
        self._set_initial_geometry()

        self.store = AccountStore()
        self.theme_store = ThemePreferenceStore()
        self.backend = GitBackend
        self.accounts: list[Account] = []
        self.theme_name = self.theme_store.load()
        self.theme = ThemeManager(self)
        self.theme.apply(DARK if self.theme_name == "dark" else LIGHT)

        self.repo_path = tk.StringVar(value=os.getcwd())
        self.scope = tk.StringVar(value="global")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready.")
        self.detail_vars = {key: tk.StringVar() for key in ("label", "name", "email", "auth", "extra")}

        self._build_ui()
        self._refresh_accounts()
        self._refresh_current_identity()

    def _set_initial_geometry(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(1080, max(780, screen_width - 120))
        height = min(700, max(540, screen_height - 160))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(780, width), min(540, height))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        header_copy = ttk.Frame(header)
        header_copy.pack(side="left", fill="x", expand=True)
        ttk.Label(header_copy, text="Git Account Switcher", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header_copy,
            text="Switch Git identity, SSH keys, and HTTPS credentials from one place.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        self.theme_button = ttk.Button(header, text="Dark mode", command=self._toggle_theme)
        self.theme_button.pack(side="right")
        self._sync_theme_button()

        context = ttk.Frame(root, style=CARD_FRAME, padding=14)
        context.pack(fill="x", pady=(14, 12))
        ttk.Label(context, text="Active context", style=SECTION_LABEL).pack(anchor="w")
        self.current_identity_label = ttk.Label(context, text="Loading...", style="Active.TLabel")
        self.current_identity_label.pack(anchor="w", pady=(6, 10))

        scope_row = ttk.Frame(context, style=CARD_FRAME)
        scope_row.pack(fill="x")
        ttk.Label(scope_row, text="Apply changes to", style=CARD_LABEL).pack(side="left")
        ttk.Radiobutton(
            scope_row,
            text="Global",
            variable=self.scope,
            value="global",
            command=self._on_scope_change,
        ).pack(side="left", padx=(10, 4))
        ttk.Radiobutton(
            scope_row,
            text="Repository",
            variable=self.scope,
            value="local",
            command=self._on_scope_change,
        ).pack(side="left")
        self.repo_controls = ttk.Frame(scope_row, style=CARD_FRAME)
        self.repo_entry = ttk.Entry(self.repo_controls, textvariable=self.repo_path, width=42)
        self.repo_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self.repo_controls, text="Choose repo", command=self._choose_repo).pack(
            side="left", padx=(6, 0)
        )

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, style=CARD_FRAME, padding=12)
        left.pack(side="left", fill="both")
        ttk.Label(left, text="Accounts", style=SECTION_LABEL).pack(anchor="w")
        ttk.Label(left, text="Search accounts", style="CardMuted.TLabel").pack(
            anchor="w", pady=(8, 4)
        )
        search_entry = ttk.Entry(left, textvariable=self.search_var, width=30)
        search_entry.pack(fill="x", pady=(0, 8))
        self.search_var.trace_add("write", lambda *_args: self._refresh_accounts())

        self.listbox = tk.Listbox(left, width=34, height=18, exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.theme.bind_listbox(self.listbox)

        left_actions = ttk.Frame(left, style=CARD_FRAME)
        left_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(left_actions, text="Add account", command=self._add_account).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(left_actions, text="Refresh", command=self._refresh_all).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        for column in range(2):
            left_actions.columnconfigure(column, weight=1)

        right = ttk.Frame(body, style=CARD_FRAME, padding=12)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        ttk.Label(right, text="Selected account", style=SECTION_LABEL).pack(anchor="w")

        self.empty_state = ttk.Label(
            right,
            text="No account selected.\nAdd an account to get started.",
            style="CardMuted.TLabel",
            justify="left",
        )
        self.empty_state.pack(anchor="w", pady=(12, 0))

        self.details_frame = ttk.Frame(right, style=CARD_FRAME)
        identity = ttk.LabelFrame(self.details_frame, text="Identity", padding=10)
        identity.pack(fill="x", pady=(10, 8))
        for row, (label, key) in enumerate((("Label", "label"), ("Name", "name"), ("Email", "email"))):
            ttk.Label(identity, text=f"{label}:", style=CARD_LABEL).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Label(identity, textvariable=self.detail_vars[key], style=CARD_LABEL).grid(
                row=row, column=1, sticky="w", padx=(8, 0), pady=3
            )

        auth = ttk.LabelFrame(self.details_frame, text="Authentication", padding=10)
        auth.pack(fill="x", pady=(0, 8))
        ttk.Label(auth, text="Method:", style=CARD_LABEL).grid(row=0, column=0, sticky="w", pady=3)
        self.auth_badge = ttk.Label(auth, textvariable=self.detail_vars["auth"], style="Badge.TLabel")
        self.auth_badge.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)
        ttk.Label(auth, text="Details:", style=CARD_LABEL).grid(row=1, column=0, sticky="nw", pady=3)
        ttk.Label(auth, textvariable=self.detail_vars["extra"], style=CARD_LABEL, wraplength=420, justify="left").grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=3
        )

        actions = ttk.Frame(self.details_frame, style=CARD_FRAME)
        actions.pack(fill="x", pady=(4, 0))
        self.switch_btn = ttk.Button(
            actions,
            text="Switch account",
            style="Accent.TButton",
            command=self._switch_account,
            state="disabled",
        )
        self.switch_btn.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self.test_ssh_btn = ttk.Button(actions, text="Test SSH", command=self._test_ssh, state="disabled")
        self.test_ssh_btn.grid(row=1, column=0, sticky="ew")
        ttk.Button(actions, text="Edit", command=self._edit_account).grid(
            row=1, column=1, sticky="ew", padx=6
        )
        ttk.Button(actions, text="Delete", style="Danger.TButton", command=self._delete_account).grid(
            row=1, column=2, sticky="ew"
        )
        for column in range(3):
            actions.columnconfigure(column, weight=1)

        status = ttk.Frame(root, style=CARD_FRAME, padding=(12, 8))
        status.pack(fill="x", pady=(12, 0))
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w")
        self._on_scope_change()

    def _sync_theme_button(self) -> None:
        self.theme_button.configure(text="Light mode" if self.theme_name == "dark" else "Dark mode")

    def _toggle_theme(self) -> None:
        palette = toggle_theme(self.theme_name)
        self.theme_name = palette.name
        self.theme.apply(palette)
        self.theme_store.save(self.theme_name)
        self.theme.bind_listbox(self.listbox)
        self._sync_theme_button()

    def _on_scope_change(self) -> None:
        is_local = self.scope.get() == "local"
        if is_local:
            self.repo_controls.pack(side="left", fill="x", expand=True, padx=(12, 0))
        else:
            self.repo_controls.pack_forget()
        self._refresh_current_identity()

    def _choose_repo(self) -> None:
        path = filedialog.askdirectory(title="Choose a git repository")
        if path:
            self.repo_path.set(path)
            self._refresh_current_identity()

    def _refresh_all(self) -> None:
        self._refresh_accounts()
        self._refresh_current_identity()

    def _filtered_accounts(self) -> list[Account]:
        query = self.search_var.get().strip().lower()
        if not query:
            return self.accounts
        return [
            account
            for account in self.accounts
            if query in account.label.lower()
            or query in account.email.lower()
            or query in account.name.lower()
        ]

    def _refresh_accounts(self, select_id: str | None = None) -> None:
        previous_id = select_id
        if previous_id is None:
            selected = self._selected_account()
            previous_id = selected.id if selected else None

        self.accounts = self.store.load()
        visible = self._filtered_accounts()
        self.listbox.delete(0, tk.END)
        for account in visible:
            self.listbox.insert(tk.END, f"{account.label}  ·  {account.email}")

        if not visible:
            self._clear_details()
            return

        index = next((i for i, account in enumerate(visible) if account.id == previous_id), 0)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self._on_select()

    def _clear_details(self) -> None:
        for var in self.detail_vars.values():
            var.set("")
        self.details_frame.pack_forget()
        self.empty_state.pack(anchor="w", pady=(12, 0))
        self.switch_btn.configure(state="disabled")
        self.test_ssh_btn.configure(state="disabled")

    def _refresh_current_identity(self) -> None:
        scope: Scope = "local" if self.scope.get() == "local" else "global"
        repo = self.repo_path.get() if scope == "local" else None
        name, email = self.backend.get_current_identity(scope=scope, repo_path=repo)
        if name or email:
            self.current_identity_label.configure(
                text=f"{name or '(no name)'}  <{email or 'no email'}>  ·  {scope}"
            )
        else:
            self.current_identity_label.configure(text=f"No identity configured for {scope} scope.")

    def _selected_account(self) -> Account | None:
        selection = self.listbox.curselection()
        if not selection:
            return None
        visible = self._filtered_accounts()
        if selection[0] >= len(visible):
            return None
        return visible[selection[0]]

    def _auth_summary(self, account: Account) -> tuple[str, str]:
        if account.auth_method == AuthMethod.SSH:
            return "SSH", f"Key: {account.ssh_key or '—'}\nHost alias: {account.host_alias or '—'}"
        if account.auth_method == AuthMethod.PAT:
            store = self.backend.credential_storage_label()
            status = f"Saved in {store}" if account.has_pat else "Not saved"
            return "HTTPS / PAT", f"Host: {account.pat_host or '—'}\nUsername: {account.pat_username or '—'}\nPAT: {status}"
        return "Identity only", "No SSH key or PAT configured."

    def _on_select(self, _event: object | None = None) -> None:
        account = self._selected_account()
        if not account:
            self._clear_details()
            return

        self.empty_state.pack_forget()
        self.details_frame.pack(fill="both", expand=True)
        self.detail_vars["label"].set(account.label)
        self.detail_vars["name"].set(account.name)
        self.detail_vars["email"].set(account.email)
        auth, extra = self._auth_summary(account)
        self.detail_vars["auth"].set(auth)
        self.detail_vars["extra"].set(extra)
        self.switch_btn.configure(state="normal")
        self.test_ssh_btn.configure(state="normal" if account.auth_method == AuthMethod.SSH else "disabled")

    def _prepare_pat(self, account: Account, token: str, existing: Account | None = None) -> bool:
        if account.auth_method != AuthMethod.PAT:
            account.has_pat = False
            account.pat_host = ""
            account.pat_username = ""
            return True

        if not token:
            account.has_pat = bool(existing and existing.has_pat)
            if existing:
                account.pat_host = existing.pat_host
                account.pat_username = existing.pat_username
            return True

        ok, output = self.backend.store_pat(account.pat_host, account.pat_username, token)
        if not ok:
            messagebox.showerror("Could not save PAT", output)
            return False

        account.pat_host = self.backend.normalize_host(account.pat_host)
        account.has_pat = True
        return True

    def _add_account(self) -> None:
        dialog = AccountDialog(self)
        self.wait_window(dialog)
        if not dialog.result:
            return
        account = dialog.result
        if not self._prepare_pat(account, dialog.pat_token):
            return
        saved = self.store.add(account)
        self._refresh_accounts(select_id=saved.id)
        self.status_var.set(f"Added account '{saved.label}'.")

    def _edit_account(self) -> None:
        account = self._selected_account()
        if not account:
            messagebox.showinfo("No selection", "Select an account to edit.")
            return
        dialog = AccountDialog(self, account=account)
        self.wait_window(dialog)
        if not dialog.result:
            return
        updated = dialog.result
        if not self._prepare_pat(updated, dialog.pat_token, existing=account):
            return
        self.store.update(account.id, updated)
        self._refresh_accounts(select_id=account.id)
        self.status_var.set(f"Updated account '{updated.label}'.")

    def _delete_account(self) -> None:
        account = self._selected_account()
        if not account:
            messagebox.showinfo("No selection", "Select an account to delete.")
            return
        if not messagebox.askyesno("Delete account", f"Delete '{account.label}'?"):
            return
        if account.has_pat:
            self.backend.delete_pat(account.pat_host, account.pat_username)
        self.store.delete(account.id)
        self._refresh_accounts()
        self.status_var.set(f"Deleted account '{account.label}'.")

    def _switch_account(self) -> None:
        account = self._selected_account()
        if not account:
            return

        scope: Scope = "local" if self.scope.get() == "local" else "global"
        repo = self.repo_path.get() if scope == "local" else None
        if scope == "local" and not self.backend.is_git_repo(repo):
            messagebox.showerror("Not a git repo", f"'{repo}' is not a git repository.")
            return

        ok, message = self.backend.set_identity(account.name, account.email, scope=scope, repo_path=repo)
        if not ok:
            messagebox.showerror("Switch failed", message)
            return

        auth_ok, auth_message = self._activate_authentication(account, scope, repo)
        summary = self._switch_summary(account, scope, auth_ok)
        self._refresh_current_identity()
        self.status_var.set(summary)
        details = f"{summary}\n{auth_message}" if auth_message else summary
        messagebox.showinfo("Account switched", details)

    def _activate_authentication(
        self,
        account: Account,
        scope: Scope,
        repo: str | None,
    ) -> tuple[bool, str]:
        if account.auth_method == AuthMethod.SSH and account.ssh_key:
            return self.backend.ssh_add_key(account.ssh_key)
        if account.auth_method == AuthMethod.PAT and account.has_pat:
            return self.backend.activate_pat(
                account.pat_host,
                account.pat_username,
                scope=scope,
                repo_path=repo,
            )
        return True, ""

    @staticmethod
    def _switch_summary(account: Account, scope: Scope, auth_ok: bool) -> str:
        summary = f"Switched to '{account.label}' ({scope})."
        if account.auth_method == AuthMethod.SSH and account.ssh_key:
            summary += f" SSH: {'OK' if auth_ok else 'FAILED'}."
        if account.auth_method == AuthMethod.PAT and account.has_pat:
            summary += f" PAT: {'OK' if auth_ok else 'FAILED'}."
        return summary

    def _test_ssh(self) -> None:
        account = self._selected_account()
        if not account:
            return
        host = account.host_alias or "github.com"
        self.status_var.set(f"Testing SSH connection to {host}...")
        self.update_idletasks()
        _, output = self.backend.test_ssh(host)
        messagebox.showinfo(f"SSH test: {host}", output or "(no output)")
        self.status_var.set("Ready.")


def run_app() -> None:
    app = GitSwitcherApp()
    app.mainloop()
