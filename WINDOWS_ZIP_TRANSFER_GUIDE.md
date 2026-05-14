# Get these files into GitHub Desktop's empty Windows folder

If GitHub Desktop is already connected to this local folder:

```text
C:\Users\Taylor\Raydium-LP1
```

but the folder only contains `.git`, GitHub Desktop is connected correctly but there are no project files to commit.

Because this coding container cannot push to GitHub, the practical workaround is:

1. create a ZIP of the project files from the coding workspace,
2. expand that ZIP into `C:\Users\Taylor\Raydium-LP1`,
3. open GitHub Desktop,
4. commit the files,
5. push/publish to GitHub.

## Important

Do not paste Markdown fence lines into PowerShell. Paste only the actual command lines.

## After files are copied into the folder

Use PowerShell to confirm the files are there:

```powershell
cd C:\Users\Taylor\Raydium-LP1
Get-ChildItem -Force
```

You should see files/folders like:

```text
README.md
setup_wizard.ps1
scripts
src
config
```

Then GitHub Desktop should show many changed files. Commit them with a message like:

```text
Initial Raydium-LP1 files
```

Then click **Push origin** or **Publish branch**.

After GitHub has the files, the normal setup command will work:

```powershell
cd C:\Users\Taylor\Raydium-LP1
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_wizard.ps1
```
