import { execFile, spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { promisify } from "util";
import * as vscode from "vscode";
import { nativeAddGithub, nativeStatus, nativeSwitch } from "./native";

const execFileAsync = promisify(execFile);

export type PublicAccount = {
  id: string;
  label: string;
  name: string;
  email: string;
  auth_method: string;
  has_pat: boolean;
  ssh_key: boolean;
  host_alias: string;
  pat_host: string;
  pat_username: string;
};

export type StatusPayload = {
  ok: boolean;
  scope: "global" | "local";
  repo_path: string | null;
  name: string;
  email: string;
  matched: PublicAccount | null;
  accounts: PublicAccount[];
};

export type SwitchPayload = {
  ok: boolean;
  summary: string;
  detail?: string;
  scope?: "global" | "local";
  account?: PublicAccount;
};

export type AddPayload = {
  ok: boolean;
  summary: string;
  detail?: string;
  action?: string;
  account?: PublicAccount;
};

function packageRootCandidates(extensionPath: string): string[] {
  const configured = vscode.workspace
    .getConfiguration("gitSwitch")
    .get<string>("packageRoot", "")
    .trim();
  const candidates = [
    configured,
    path.resolve(extensionPath, ".."),
    path.resolve(extensionPath, "../.."),
  ].filter(Boolean);
  return [...new Set(candidates)];
}

export function resolvePackageRoot(extensionPath: string): string | undefined {
  for (const candidate of packageRootCandidates(extensionPath)) {
    const marker = path.join(candidate, "gitswitch", "__main__.py");
    if (fs.existsSync(marker)) {
      return candidate;
    }
  }
  return undefined;
}

function pythonPath(): string {
  return (
    vscode.workspace.getConfiguration("gitSwitch").get<string>("pythonPath", "python3") ||
    "python3"
  );
}

function bridgeEnv(root: string): NodeJS.ProcessEnv {
  return {
    ...process.env,
    PYTHONPATH: [root, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  };
}

async function runBridge(
  extensionPath: string,
  args: string[],
  timeoutMs = 20_000,
): Promise<{ code: number; payload: Record<string, unknown> } | undefined> {
  const root = resolvePackageRoot(extensionPath);
  if (!root) {
    return undefined;
  }

  try {
    const { stdout } = await execFileAsync(pythonPath(), ["-m", "gitswitch", ...args], {
      env: bridgeEnv(root),
      cwd: root,
      timeout: timeoutMs,
      maxBuffer: 2 * 1024 * 1024,
    });
    return { code: 0, payload: JSON.parse(stdout) as Record<string, unknown> };
  } catch (error) {
    const err = error as {
      code?: number;
      stdout?: string;
      stderr?: string;
      message?: string;
    };
    if (err.stdout) {
      try {
        return {
          code: typeof err.code === "number" ? err.code : 1,
          payload: JSON.parse(err.stdout) as Record<string, unknown>,
        };
      } catch {
        // fall through to native
      }
    }
    return undefined;
  }
}

export async function fetchStatus(
  extensionPath: string,
  repoPath?: string,
): Promise<StatusPayload> {
  const args = ["status"];
  if (repoPath) {
    args.push("--repo", repoPath);
  }
  const bridged = await runBridge(extensionPath, args);
  if (bridged) {
    return bridged.payload as unknown as StatusPayload;
  }
  return nativeStatus(repoPath);
}

export async function switchAccount(
  extensionPath: string,
  accountId: string,
  repoPath?: string,
): Promise<SwitchPayload> {
  const args = ["switch", "--id", accountId];
  if (repoPath) {
    args.push("--repo", repoPath);
  }
  const bridged = await runBridge(extensionPath, args);
  if (bridged) {
    return bridged.payload as unknown as SwitchPayload;
  }
  return nativeSwitch(accountId, repoPath);
}

export async function addGithubAccount(
  extensionPath: string,
  onStatus?: (message: string) => void,
): Promise<AddPayload> {
  const root = resolvePackageRoot(extensionPath);
  if (!root) {
    return nativeAddGithub(onStatus);
  }

  return new Promise((resolve, reject) => {
    const child = spawn(pythonPath(), ["-m", "gitswitch", "add-github"], {
      env: bridgeEnv(root),
      cwd: root,
    });

    let stdout = "";
    let stderr = "";
    let stderrBuffer = "";

    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("GitHub sign-in timed out. Approve in the browser and try again."));
    }, 10 * 60 * 1000);

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });

    child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      stderr += text;
      stderrBuffer += text;
      const lines = stderrBuffer.split("\n");
      stderrBuffer = lines.pop() || "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
          continue;
        }
        try {
          const event = JSON.parse(trimmed) as { type?: string; message?: string };
          if (event.type === "status" && event.message && onStatus) {
            onStatus(event.message);
          }
        } catch {
          // ignore non-JSON stderr
        }
      }
    });

    child.on("error", () => {
      clearTimeout(timer);
      void nativeAddGithub(onStatus).then(resolve, reject);
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      try {
        if (stdout.trim()) {
          resolve(JSON.parse(stdout) as AddPayload);
          return;
        }
      } catch {
        // fall through
      }
      void nativeAddGithub(onStatus).then(resolve, () =>
        reject(new Error((stderr || stdout || `add-github exited with code ${code}`).trim())),
      );
    });
  });
}

export function workspaceRepoPath(): string | undefined {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder?.uri.fsPath;
}
