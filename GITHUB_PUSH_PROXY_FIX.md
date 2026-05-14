# Fixing `git push` blocked by `CONNECT tunnel failed, response 403`

This error happened in the coding container, not in your Windows PowerShell:

```text
fatal: unable to access 'https://github.com/RepoHere1/Raydium-LP1.git/': CONNECT tunnel failed, response 403
```

It means the network between this container and GitHub is blocked by a proxy/firewall. It is not a Python, Raydium, or script error.

## Can you fix the container proxy from PowerShell?

No. Your Windows PowerShell cannot change this container's network proxy.

The fix is to push from somewhere that can reach GitHub:

1. your Windows PC,
2. GitHub Desktop,
3. VS Code on your PC,
4. another dev environment with GitHub access,
5. or this container only if the platform/network owner unblocks GitHub push access.

## The core rule

GitHub can only receive files from a folder that actually has the files.

```text
folder with Raydium-LP1 files -> git add -> git commit -> git push -> GitHub
```

Your Windows folder currently has only `.git`, so it has nothing useful to push yet.

## If you get the Raydium-LP1 files onto Windows

After the project files exist in `C:\Users\Taylor\Raydium-LP1`, paste this in PowerShell. Do not paste Markdown backticks.

```powershell
cd C:\Users\Taylor\Raydium-LP1
Get-ChildItem -Force
git status
git add .
git commit -m "Initial Raydium-LP1 files"
git branch -M main
git remote remove origin 2>$null
git remote add origin https://github.com/RepoHere1/Raydium-LP1.git
git push -u origin main
```

If `git commit` says your name/email are missing, run:

```powershell
git config --global user.name "Taylor"
git config --global user.email "YOUR_EMAIL_HERE"
git commit -m "Initial Raydium-LP1 files"
git push -u origin main
```

If GitHub asks for login, use GitHub's browser login, Git Credential Manager, GitHub Desktop, or a GitHub Personal Access Token.

## If Windows Git also has a proxy problem

Check whether Windows Git has a bad proxy configured:

```powershell
git config --global --get http.proxy
git config --global --get https.proxy
```

If either command prints an old proxy you do not use, remove it:

```powershell
git config --global --unset http.proxy
git config --global --unset https.proxy
```

Then try:

```powershell
git push -u origin main
```

## If GitHub still shows empty

Check remote branches:

```powershell
git ls-remote --heads https://github.com/RepoHere1/Raydium-LP1.git
```

If it prints nothing, GitHub still has no pushed branch.

## Easiest no-command option

If command-line Git keeps being painful, use GitHub Desktop:

1. Install GitHub Desktop.
2. Sign in to GitHub.
3. Add the local repository folder that contains the Raydium-LP1 files.
4. Commit all files.
5. Publish/push to `RepoHere1/Raydium-LP1`.

GitHub Desktop handles login better than raw PowerShell for beginners.
