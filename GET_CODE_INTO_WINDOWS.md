# Get the Raydium-LP1 code into `C:\Users\Taylor\Raydium-LP1`

If your Windows folder is empty, that is expected until the repo files are **cloned, pulled, downloaded, or copied** onto your computer.

I am editing files inside this coding workspace at:

```text
/workspace/.github
```

That is **not the same folder** as your Windows folder:

```text
C:\Users\Taylor\Raydium-LP1
```

PowerShell cannot see `/workspace/.github` unless the files are pushed to GitHub or otherwise copied to Windows.

## First: check whether your Windows folder is empty

Paste this in PowerShell:

```powershell
cd C:\Users\Taylor\Raydium-LP1
Get-ChildItem -Force
```

If it prints nothing or only `.git`, then the project files are not on your PC yet.

## Best fix if GitHub has the project files

This deletes only the local empty folder and reclones the GitHub repo fresh.

Only run this if you do **not** have personal files inside `C:\Users\Taylor\Raydium-LP1` that you need to keep.

```powershell
cd C:\Users\Taylor
if (Test-Path .\Raydium-LP1) {
  Rename-Item .\Raydium-LP1 ("Raydium-LP1-empty-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
git clone https://github.com/RepoHere1/Raydium-LP1.git Raydium-LP1
cd .\Raydium-LP1
Get-ChildItem -Force
```

After the code appears, run setup:

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```

## If GitHub is still empty

If `git clone` gives you an empty folder, then the code has not been pushed to GitHub yet.

In that case, the missing step is:

1. The code must be pushed from the coding workspace to `https://github.com/RepoHere1/Raydium-LP1.git`.
2. Then your PC can run `git clone` or `git pull`.

You can check whether GitHub has branches with:

```powershell
cd C:\Users\Taylor\Raydium-LP1
git ls-remote --heads https://github.com/RepoHere1/Raydium-LP1.git
```

If that prints nothing, GitHub has no branch with the code yet.

## Why `setup_wizard.ps1` failed

This failed:

```powershell
setup_wizard.ps1
```

because either:

1. the file is not in your Windows folder yet, or
2. PowerShell needs current-folder scripts to start with `./` or `.\`.

After the code exists locally, use:

```powershell
cd C:\Users\Taylor\Raydium-LP1
.\setup_wizard.ps1
```

or:

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```
