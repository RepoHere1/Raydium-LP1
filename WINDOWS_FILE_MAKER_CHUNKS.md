# Windows file-maker chunk workflow

Use this workflow when GitHub is empty and the coding container cannot push to GitHub.

The idea is:

1. The assistant creates a ZIP of the Raydium-LP1 project files.
2. The ZIP is converted to Base64 text.
3. You paste the Base64 into PowerShell in chunks.
4. PowerShell rebuilds the ZIP and expands it into `C:\Users\Taylor\Raydium-LP1`.
5. GitHub Desktop sees the files, then you commit as `Initial Raydium-LP1 files` and push.

## PowerShell rules

- Paste only the command contents, not Markdown fence lines like ```powershell.
- Run the chunks in order.
- If a chunk fails, stop and paste the error back.
- After extraction, run `Get-ChildItem -Force` and make sure you see `README.md`, `setup_wizard.ps1`, `scripts`, `src`, `config`, and `tests`.

## GitHub Desktop commit message

After the files exist in the folder, use this commit message in GitHub Desktop:

```text
Initial Raydium-LP1 files
```
