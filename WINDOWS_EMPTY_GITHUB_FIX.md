# Fix: GitHub is empty and Windows folder only has `.git`

Your output confirms this exact situation:

```text
warning: You appear to have cloned an empty repository.
Get-ChildItem -Force shows only .git
```

That means GitHub currently has **no project files** in `https://github.com/RepoHere1/Raydium-LP1.git`.

## Important copy/paste rule

Do **not** paste Markdown fence lines into PowerShell.

Do not paste this line:

```text
```powershell
```

Do not paste this line either:

```text
```
```

Only paste the command lines inside the box.

## Why the setup script is missing

This command fails:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```

because your folder does not contain `setup_wizard.ps1` yet. Your PowerShell output showed the folder contains only:

```text
.git
```

So Windows is correct: the script does not exist on your machine yet.

## Why your earlier `git push` did not put this code on GitHub

These commands only push files that already exist and have been committed in **that same local folder**:

```powershell
git remote add origin https://github.com/RepoHere1/Raydium-LP1.git
git branch -M main
git push -u origin main
```

If `C:\Users\Taylor\Raydium-LP1` had no project files and no commit, then there was nothing useful to push.

## The real flow

Git can only move code like this:

```text
folder with real files + git commit -> git push -> GitHub -> git clone/pull -> Windows folder
```

Right now, your Windows folder has only `.git`, so it cannot be the source of the project code.

## What must happen next

The project files currently exist in the coding workspace, not in your Windows folder. They need to be pushed/uploaded to GitHub first.

After GitHub has files, this PowerShell block will work on your PC:

```powershell
cd C:\Users\Taylor
if (Test-Path .\Raydium-LP1) {
  Rename-Item .\Raydium-LP1 ("Raydium-LP1-empty-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
git clone https://github.com/RepoHere1/Raydium-LP1.git Raydium-LP1
cd .\Raydium-LP1
Get-ChildItem -Force
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```

If `git clone` still says the repository is empty, stop there. The code is still not on GitHub.

## How to check whether GitHub has code yet

Paste only this, without backticks:

```powershell
git ls-remote --heads https://github.com/RepoHere1/Raydium-LP1.git
```

If it prints nothing, GitHub has no branches/code yet.

If it prints something like `refs/heads/main`, then GitHub has a branch and clone/pull should bring files down.
