/**
 * Standalone Git Switch ops (no Python). Used when the marketplace
 * install cannot find the local gitswitch package.
 */
import { execFile, spawn } from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { promisify } from "util";
import * as vscode from "vscode";
import type { AddPayload, PublicAccount, StatusPayload, SwitchPayload } from "./bridge";

const execFileAsync = promisify(execFile);
const GITHUB_CLIENT_ID = "178c6fc778ccc68e1d6a";
const OAUTH_SCOPES = "repo read:user user:email";
const ACCOUNTS_FILE = path.join(os.homedir(), ".gitswitch", "accounts.json");

type StoredAccount = {
  id: string;
  label: string;
  name: string;
  email: string;
  auth_method?: string;
  ssh_key?: string;
  host_alias?: string;
  pat_host?: string;
  pat_username?: string;
  has_pat?: boolean;
};

async function runGit(
  args: string[],
  cwd?: string,
  input?: string,
): Promise<{ ok: boolean; output: string }> {
  if (!input) {
    try {
      const { stdout, stderr } = await execFileAsync("git", args, {
        cwd,
        timeout: 15_000,
        maxBuffer: 1024 * 1024,
      });
      return { ok: true, output: ((stdout || "") + (stderr || "")).trim() };
    } catch (error) {
      const err = error as { stdout?: string; stderr?: string; message?: string };
      return {
        ok: false,
        output: ((err.stdout || "") + (err.stderr || "") + (err.message || "")).trim(),
      };
    }
  }

  return new Promise((resolve) => {
    const child = spawn("git", args, { cwd });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      resolve({ ok: false, output: error.message });
    });
    child.on("close", (code) => {
      resolve({
        ok: code === 0,
        output: (stdout + stderr).trim(),
      });
    });
    child.stdin.write(input);
    child.stdin.end();
  });
}

function isGitRepo(repoPath?: string): boolean {
  if (!repoPath) {
    return false;
  }
  return fs.existsSync(path.join(repoPath, ".git"));
}

function findGitRoot(start?: string): string | undefined {
  if (!start) {
    return undefined;
  }
  let current = path.resolve(start);
  for (;;) {
    if (fs.existsSync(path.join(current, ".git"))) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return undefined;
    }
    current = parent;
  }
}

function loadAccounts(): StoredAccount[] {
  try {
    const raw = JSON.parse(fs.readFileSync(ACCOUNTS_FILE, "utf8")) as unknown;
    if (!Array.isArray(raw)) {
      return [];
    }
    return raw.filter((item) => item && typeof item === "object") as StoredAccount[];
  } catch {
    return [];
  }
}

function saveAccounts(accounts: StoredAccount[]): void {
  const dir = path.dirname(ACCOUNTS_FILE);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(ACCOUNTS_FILE, JSON.stringify(accounts, null, 2));
}

function toPublic(account: StoredAccount): PublicAccount {
  const auth =
    account.auth_method ||
    (account.has_pat ? "pat" : account.ssh_key ? "ssh" : "none");
  return {
    id: account.id,
    label: account.label,
    name: account.name,
    email: account.email,
    auth_method: auth,
    has_pat: Boolean(account.has_pat),
    ssh_key: Boolean(account.ssh_key),
    host_alias: account.host_alias || "",
    pat_host: account.pat_host || "",
    pat_username: account.pat_username || "",
  };
}

function matchByEmail(email: string, accounts: StoredAccount[]): StoredAccount | undefined {
  const needle = email.trim().toLowerCase();
  if (!needle) {
    return undefined;
  }
  return accounts.find((account) => account.email.trim().toLowerCase() === needle);
}

function newId(): string {
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}

async function getIdentity(
  scope: "global" | "local",
  repoPath?: string,
): Promise<{ name: string; email: string }> {
  const flag = scope === "global" ? "--global" : "--local";
  const cwd = scope === "local" ? repoPath : undefined;
  const name = await runGit(["config", flag, "user.name"], cwd);
  const email = await runGit(["config", flag, "user.email"], cwd);
  return {
    name: name.ok ? name.output : "",
    email: email.ok ? email.output : "",
  };
}

export async function nativeStatus(repoPath?: string): Promise<StatusPayload> {
  const root = findGitRoot(repoPath);
  const scope: "global" | "local" = root ? "local" : "global";
  const accounts = loadAccounts();
  const identity = await getIdentity(scope, root);
  const matched = matchByEmail(identity.email, accounts);
  return {
    ok: true,
    scope,
    repo_path: root || null,
    name: identity.name,
    email: identity.email,
    matched: matched ? toPublic(matched) : null,
    accounts: accounts.map(toPublic),
  };
}

export async function nativeSwitch(
  accountId: string,
  repoPath?: string,
): Promise<SwitchPayload> {
  const accounts = loadAccounts();
  const account = accounts.find((item) => item.id === accountId);
  if (!account) {
    return { ok: false, summary: `No account found for id '${accountId}'.` };
  }

  const root = findGitRoot(repoPath);
  const scope: "global" | "local" = root ? "local" : "global";
  if (scope === "local" && !isGitRepo(root)) {
    return { ok: false, summary: `'${repoPath}' is not a git repository.`, scope };
  }

  const flag = scope === "global" ? "--global" : "--local";
  const cwd = scope === "local" ? root : undefined;
  const nameOk = await runGit(["config", flag, "user.name", account.name], cwd);
  const emailOk = await runGit(["config", flag, "user.email", account.email], cwd);
  if (!nameOk.ok || !emailOk.ok) {
    return {
      ok: false,
      summary: (nameOk.output + "\n" + emailOk.output).trim() || "Could not set identity.",
      scope,
      account: toPublic(account),
    };
  }

  let detail = "";
  let authOk = true;
  const auth = account.auth_method || (account.has_pat ? "pat" : account.ssh_key ? "ssh" : "none");

  if (auth === "ssh" && account.ssh_key) {
    const key = account.ssh_key.replace(/^~(?=\/|\\)/, os.homedir());
    try {
      const { stdout, stderr } = await execFileAsync("ssh-add", [key], { timeout: 15_000 });
      detail = ((stdout || "") + (stderr || "")).trim() || "SSH key added.";
    } catch (error) {
      authOk = false;
      const err = error as { stderr?: string; message?: string };
      detail = (err.stderr || err.message || "ssh-add failed").trim();
    }
  } else if (auth === "pat") {
    if (!account.has_pat || !account.pat_host || !account.pat_username) {
      authOk = false;
      detail = "No HTTPS token saved for this account.";
    } else {
      const host = account.pat_host.replace(/^https?:\/\//, "").replace(/\/$/, "");
      const key = `credential.https://${host}.username`;
      const result = await runGit(["config", flag, key, account.pat_username], cwd);
      authOk = result.ok;
      detail = result.ok
        ? `HTTPS credentials activated for '${account.pat_username}' on ${host}.`
        : result.output;
    }
  }

  let summary = `Switched to '${account.label}' (${scope}).`;
  if (auth === "none") {
    summary += " Identity only: commit author updated.";
  } else if (auth === "ssh") {
    summary += ` Commit author updated. SSH: ${authOk ? "OK" : "FAILED"}.`;
  } else if (auth === "pat") {
    summary += authOk
      ? " Commit author updated. HTTPS credentials activated."
      : " Commit author updated, but HTTPS credentials were NOT activated.";
  }

  return {
    ok: true,
    summary,
    detail,
    scope,
    account: toPublic(account),
  };
}

async function postForm(url: string, data: Record<string, string>): Promise<Record<string, string>> {
  const body = new URLSearchParams(data).toString();
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });
  const json = (await response.json()) as Record<string, string>;
  return json;
}

async function storePat(host: string, username: string, token: string): Promise<{ ok: boolean; message: string }> {
  const payload = [
    "protocol=https",
    `host=${host}`,
    `username=${username}`,
    `password=${token}`,
    "",
  ].join("\n");
  const result = await runGit(["credential", "approve"], undefined, payload);
  if (!result.ok) {
    return { ok: false, message: result.output || "Could not save token via git credential helper." };
  }
  return { ok: true, message: "Token saved via Git credential helper." };
}

export async function nativeAddGithub(
  onStatus?: (message: string) => void,
): Promise<AddPayload> {
  const notify = onStatus || (() => undefined);
  notify("Requesting GitHub device code…");

  const device = await postForm("https://github.com/login/device/code", {
    client_id: GITHUB_CLIENT_ID,
    scope: OAUTH_SCOPES,
  });
  if (!device.device_code || !device.user_code) {
    return { ok: false, summary: "GitHub did not return a device login code." };
  }

  const userCode = device.user_code;
  const verifyUrl = `https://github.com/login/device?user_code=${encodeURIComponent(userCode)}`;
  notify(`Code ${userCode} — confirm in your browser…`);
  await vscode.env.openExternal(vscode.Uri.parse(verifyUrl));
  notify(`Browser opened. Enter code ${userCode} if asked, then approve…`);

  const interval = Math.max(1, Number(device.interval || 5)) * 1000;
  const expires = Date.now() + Math.max(30, Number(device.expires_in || 900)) * 1000;
  let token = "";

  while (Date.now() < expires) {
    await new Promise((resolve) => setTimeout(resolve, interval));
    const poll = await postForm("https://github.com/login/oauth/access_token", {
      client_id: GITHUB_CLIENT_ID,
      device_code: device.device_code,
      grant_type: "urn:ietf:params:oauth:grant-type:device_code",
    });
    if (poll.access_token) {
      token = poll.access_token;
      break;
    }
    if (poll.error && poll.error !== "authorization_pending" && poll.error !== "slow_down") {
      return { ok: false, summary: poll.error_description || poll.error };
    }
    const remaining = Math.max(0, Math.round((expires - Date.now()) / 1000));
    notify(`Waiting for browser approval… ${remaining}s left`);
  }

  if (!token) {
    return { ok: false, summary: "Timed out waiting for GitHub authorization." };
  }

  notify("Authorized — loading GitHub profile…");
  const profileRes = await fetch("https://api.github.com/user", {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "Git-Switch",
    },
  });
  const profile = (await profileRes.json()) as {
    login?: string;
    name?: string;
    email?: string;
  };
  if (!profile.login) {
    return { ok: false, summary: "Could not load GitHub profile." };
  }

  let email = profile.email || "";
  if (!email) {
    const emailsRes = await fetch("https://api.github.com/user/emails", {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "Git-Switch",
      },
    });
    const emails = (await emailsRes.json()) as Array<{ email: string; primary?: boolean; verified?: boolean }>;
    const preferred =
      emails.find((item) => item.primary && item.verified) ||
      emails.find((item) => item.verified) ||
      emails[0];
    email = preferred?.email || `${profile.login}@users.noreply.github.com`;
  }

  notify("Saving GitHub account…");
  const stored = await storePat("github.com", profile.login, token);
  if (!stored.ok) {
    return { ok: false, summary: stored.message };
  }

  const accounts = loadAccounts();
  const existing = accounts.find(
    (item) =>
      (item.auth_method === "pat" || item.has_pat) &&
      (item.pat_username || "").toLowerCase() === profile.login!.toLowerCase() &&
      (item.pat_host || "github.com") === "github.com",
  );

  const account: StoredAccount = {
    id: existing?.id || newId(),
    label: profile.login,
    name: profile.name || profile.login,
    email,
    auth_method: "pat",
    pat_host: "github.com",
    pat_username: profile.login,
    has_pat: true,
    ssh_key: "",
    host_alias: "",
  };

  if (existing) {
    Object.assign(existing, account);
  } else {
    accounts.push(account);
  }
  saveAccounts(accounts);

  return {
    ok: true,
    summary: `${existing ? "Updated" : "Added"} GitHub account '${account.label}'.`,
    action: existing ? "Updated" : "Added",
    account: toPublic(account),
    detail: profile.email ? "" : "Using GitHub email (or noreply) from profile.",
  };
}
