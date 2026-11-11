# Publish Git Switch extension

You need **two** registries:

| Registry | Who uses it |
| --- | --- |
| [VS Code Marketplace](https://marketplace.visualstudio.com/) | VS Code |
| [Open VSX](https://open-vsx.org/) | **Cursor**, VSCodium, Windsurf |

Publisher ID in `package.json` is currently **`gitswitch`** — create that exact ID (or change `publisher` to match what you create).

---

## 1. VS Code Marketplace

Publisher ID **`gitswitch`** must match `package.json`.

### Preferred: Trusted Publishing (GitHub Actions)

1. Marketplace → publisher **gitswitch** → **Trusted Publishing** → link repo `AJ224/Git_Switch` + workflow `publish-extension.yml`.
2. Commit & push the `extension/` folder + workflow.
3. Run **Actions → Publish Extension → Run workflow**, or:
   ```bash
   git tag extension-v0.1.0
   git push origin extension-v0.1.0
   ```
4. Workflow publishes with `vsce publish --oidc` (no PAT).

Marketplace URL:  
`https://marketplace.visualstudio.com/items?itemName=gitswitch.git-switch`

### Alternative: PAT from your machine

```bash
cd extension
npx vsce login gitswitch   # Azure DevOps PAT with Marketplace → Manage
npx vsce publish
```

---

## 2. Open VSX (required for Cursor) — one-time

1. Sign in at [open-vsx.org](https://open-vsx.org/) with GitHub.
2. Create a namespace / claim publisher (same idea as `gitswitch` if available).
3. Create an access token in the Open VSX user settings.
4. Publish:

```bash
cd extension
npx ovsx publish -p YOUR_OVSX_PAT
```

If the namespace must differ from Marketplace, set it once:

```bash
npx ovsx publish -p YOUR_OVSX_PAT --packagePath .
```

---

## 3. Optional: GitHub Actions

Add repo secrets:

- `VSCE_PAT` — Marketplace token  
- `OVSX_PAT` — Open VSX token  

Then push a tag or run the `Publish Extension` workflow (see `.github/workflows/publish-extension.yml`).

---

## Checklist before publish

- [ ] `publisher` in `package.json` matches the Marketplace publisher ID  
- [ ] Version bumped if republishing (`0.1.0` → `0.1.1`, etc.)  
- [ ] `npm run compile` succeeds  
- [ ] Icon at `media/icon.png`  
- [ ] Published to **both** Marketplace and Open VSX for Cursor users  
