import * as vscode from "vscode";
import {
  addGithubAccount,
  fetchStatus,
  PublicAccount,
  resolvePackageRoot,
  StatusPayload,
  switchAccount,
  workspaceRepoPath,
} from "./bridge";

let statusBar: vscode.StatusBarItem;
let extensionPath = "";

export function activate(context: vscode.ExtensionContext): void {
  extensionPath = context.extensionPath;
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.command = "gitSwitch.switchAccount";
  statusBar.tooltip = "Switch or add Git account";
  statusBar.text = "$(account) Git Switch";
  statusBar.show();

  context.subscriptions.push(
    statusBar,
    vscode.commands.registerCommand("gitSwitch.switchAccount", () => accountMenu()),
    vscode.commands.registerCommand("gitSwitch.addAccount", () => addFlow()),
    vscode.commands.registerCommand("gitSwitch.refresh", () => refreshStatus()),
    vscode.workspace.onDidChangeWorkspaceFolders(() => refreshStatus()),
  );

  void refreshStatus();
}

export function deactivate(): void {
  // nothing to clean up beyond disposables
}

async function refreshStatus(): Promise<void> {
  try {
    ensureBridge();
    const status = await fetchStatus(extensionPath, workspaceRepoPath());
    updateStatusBar(status);
  } catch (error) {
    statusBar.text = "$(warning) Git Switch";
    statusBar.tooltip = errorMessage(error);
  }
}

function updateStatusBar(status: StatusPayload): void {
  if (!status.accounts.length) {
    statusBar.text = "$(account) Add account";
    statusBar.tooltip = "No accounts yet. Click to add with GitHub.";
    return;
  }

  if (status.matched) {
    statusBar.text = `$(account) ${status.matched.label}`;
    statusBar.tooltip = `${status.name} <${status.email}> · ${status.scope}\nClick to switch or add`;
    return;
  }

  if (status.email) {
    statusBar.text = `$(account) ${status.email}`;
    statusBar.tooltip = `Current Git identity is not a saved account.\n${status.name} <${status.email}> · ${status.scope}\nClick to switch or add`;
    return;
  }

  statusBar.text = "$(account) Git Switch";
  statusBar.tooltip = "Click to switch or add a Git account.";
}

async function accountMenu(): Promise<void> {
  try {
    ensureBridge();
    const status = await fetchStatus(extensionPath, workspaceRepoPath());

    if (!status.accounts.length) {
      const start = await vscode.window.showInformationMessage(
        "No accounts yet. Add one with GitHub?",
        "Add with GitHub",
      );
      if (start === "Add with GitHub") {
        await addFlow();
      }
      return;
    }

    const picked = await pickAccountOrAdd(status.accounts, status.matched?.id);
    if (!picked) {
      return;
    }
    if (picked === "add") {
      await addFlow();
      return;
    }

    const result = await switchAccount(extensionPath, picked.id, workspaceRepoPath());
    if (!result.ok) {
      await vscode.window.showErrorMessage(result.summary || "Switch failed.");
      return;
    }

    await refreshStatus();
    const detail = result.detail ? ` ${result.detail}` : "";
    vscode.window.setStatusBarMessage(`$(check) ${result.summary}${detail}`, 4000);
  } catch (error) {
    await vscode.window.showErrorMessage(errorMessage(error));
  }
}

async function addFlow(): Promise<void> {
  try {
    ensureBridge();
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Git Switch",
        cancellable: false,
      },
      async (progress) => {
        progress.report({ message: "Starting GitHub sign-in…" });
        const result = await addGithubAccount(extensionPath, (message) => {
          progress.report({ message });
          // Surface the one-time code clearly once.
          if (message.startsWith("Code ")) {
            const code = message.split("—", 1)[0].replace("Code", "").trim();
            void vscode.window.showInformationMessage(
              `Approve in your browser. If asked, enter code: ${code}`,
            );
          }
        });

        if (!result.ok) {
          await vscode.window.showErrorMessage(result.summary || "Could not add account.");
          return;
        }

        await refreshStatus();

        const switchNow = await vscode.window.showInformationMessage(
          result.summary + (result.detail ? `\n${result.detail}` : ""),
          "Switch now",
          "Later",
        );
        if (switchNow === "Switch now" && result.account) {
          const switched = await switchAccount(
            extensionPath,
            result.account.id,
            workspaceRepoPath(),
          );
          if (!switched.ok) {
            await vscode.window.showErrorMessage(switched.summary || "Switch failed.");
            return;
          }
          await refreshStatus();
          vscode.window.setStatusBarMessage(`$(check) ${switched.summary}`, 4000);
        }
      },
    );
  } catch (error) {
    await vscode.window.showErrorMessage(errorMessage(error));
  }
}

async function pickAccountOrAdd(
  accounts: PublicAccount[],
  activeId?: string,
): Promise<PublicAccount | "add" | undefined> {
  type Item = vscode.QuickPickItem & { account?: PublicAccount; add?: boolean };
  const items: Item[] = accounts.map((account) => ({
    label: account.label,
    description: account.email,
    detail: authHint(account),
    account,
    picked: account.id === activeId,
  }));
  items.push({
    label: "$(add) Add with GitHub…",
    description: "Approve in browser",
    detail: "Same one-click sign-in as the desktop app",
    add: true,
    alwaysShow: true,
  });

  const choice = await vscode.window.showQuickPick(items, {
    placeHolder: "Switch account — or add a new one",
    matchOnDescription: true,
    matchOnDetail: true,
  });
  if (!choice) {
    return undefined;
  }
  if (choice.add) {
    return "add";
  }
  return choice.account;
}

function authHint(account: PublicAccount): string {
  if (account.auth_method === "ssh") {
    return "SSH";
  }
  if (account.auth_method === "pat") {
    return account.has_pat ? "HTTPS" : "HTTPS (token missing)";
  }
  return "Identity only";
}

function ensureBridge(): void {
  // Native fallback works without the Python package (marketplace installs).
  void resolvePackageRoot(extensionPath);
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
