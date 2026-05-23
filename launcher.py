from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
DEFAULT_SAFE = ROOT / "config" / "settings.safe.json"
DEFAULT_DEGEN = ROOT / "config" / "settings.degen.json"

class LauncherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Raydium-LP1 Launcher")
        self.root.geometry("760x360")
        self.root.minsize(760, 360)

        self.current_path = tk.StringVar(value="")
        self.status = tk.StringVar(value="Ready")
        self.selected_profile = tk.StringVar(value="custom")

        self._build_ui()
        self._set_current_path(self._initial_path())
        self._update_status("Ready", ok=True)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Raydium-LP1 Launcher", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Open a settings file, choose a custom JSON file, copy its path, or start the scanner.",
        ).pack(anchor="w", pady=(4, 12))

        file_box = ttk.LabelFrame(outer, text="Current selected file", padding=12)
        file_box.pack(fill="x", pady=(0, 12))

        path_row = ttk.Frame(file_box)
        path_row.pack(fill="x")

        self.path_entry = ttk.Entry(path_row, textvariable=self.current_path, state="readonly")
        self.path_entry.pack(side="left", fill="x", expand=True)

        ttk.Button(path_row, text="Copy path", command=self.copy_path).pack(side="left", padx=(8, 0))
        ttk.Button(path_row, text="Browse...", command=self.choose_file).pack(side="left", padx=(8, 0))

        ttk.Label(
            file_box,
            text="Preset buttons load the built-in safe/degen configs. Browse lets you pick any JSON file.",
        ).pack(anchor="w", pady=(8, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 12))

        ttk.Button(actions, text="Open safe settings", command=lambda: self.open_file(DEFAULT_SAFE)).pack(side="left")
        ttk.Button(actions, text="Open degen settings", command=lambda: self.open_file(DEFAULT_DEGEN)).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Choose settings file", command=self.choose_file).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Start scanner", command=self.start_scanner).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Exit", command=self.root.destroy).pack(side="right")

        status_box = ttk.LabelFrame(outer, text="Status", padding=12)
        status_box.pack(fill="x")

        self.status_label = ttk.Label(status_box, textvariable=self.status)
        self.status_label.pack(anchor="w")

        profile_row = ttk.Frame(status_box)
        profile_row.pack(fill="x", pady=(8, 0))
        ttk.Label(profile_row, text="Selected profile:").pack(side="left")
        for text, value in (("Safe", "safe"), ("Degen", "degen"), ("Custom", "custom")):
            ttk.Radiobutton(
                profile_row,
                text=text,
                value=value,
                variable=self.selected_profile,
                command=self.sync_profile,
            ).pack(side="left", padx=(8, 0))

    def _initial_path(self) -> Path:
        if DEFAULT_SAFE.exists():
            self.selected_profile.set("safe")
            return DEFAULT_SAFE
        if DEFAULT_DEGEN.exists():
            self.selected_profile.set("degen")
            return DEFAULT_DEGEN
        return Path("")

    def _set_current_path(self, path: Path | str):
        self.current_path.set(str(path) if path else "")

    def _update_status(self, text: str, ok: bool = True):
        self.status.set(text)
        self.status_label.configure(foreground="#148a08" if ok else "#b00020")

    def sync_profile(self):
        if self.selected_profile.get() == "safe":
            self._set_current_path(DEFAULT_SAFE)
            self._update_status("Safe settings selected.", ok=True)
        elif self.selected_profile.get() == "degen":
            self._set_current_path(DEFAULT_DEGEN)
            self._update_status("Degen settings selected.", ok=True)

    def copy_path(self):
        path = self.current_path.get().strip()
        if not path:
            self._update_status("No file selected to copy.", ok=False)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(path)
        self.root.update()
        self._update_status("Path copied to clipboard.", ok=True)

    def choose_file(self):
        initial_dir = str(ROOT / "config") if (ROOT / "config").exists() else str(ROOT)
        path = filedialog.askopenfilename(
            title="Choose settings file",
            initialdir=initial_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._set_current_path(path)
            self.selected_profile.set("custom")
            self._update_status(f"Selected: {path}", ok=True)

    def open_file(self, path: Path):
        if not path.exists():
            self._update_status(f"Missing file: {path}", ok=False)
            messagebox.showerror("Missing file", f"Could not find:\n{path}")
            return
        self._set_current_path(path)
        self.selected_profile.set("safe" if path == DEFAULT_SAFE else "degen" if path == DEFAULT_DEGEN else "custom")
        self._update_status(f"Selected: {path}", ok=True)
        self._launch_editor(path)

    def _launch_editor(self, path: Path):
        editor = os.environ.get("EDITOR", "").strip()
        try:
            if editor:
                subprocess.Popen([editor, str(path)], shell=False)
            else:
                if sys.platform.startswith("win"):
                    os.startfile(str(path))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(path)])
                else:
                    subprocess.Popen(["xdg-open", str(path)])
            self._update_status(f"Opened: {path}", ok=True)
        except Exception as exc:
            self._update_status(f"Failed to open file: {exc}", ok=False)
            messagebox.showerror("Open failed", str(exc))

    def start_scanner(self):
        config = ROOT / "config" / "settings.json"
        scan_ps1 = ROOT / "scripts" / "scan.ps1"

        if not config.exists():
            messagebox.showerror("Missing config", f"Missing settings file:\n{config}")
            return

        if scan_ps1.exists():
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(scan_ps1),
                "-Config",
                str(config),
            ]
        else:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT / "src")
            cmd = [
                sys.executable,
                "-c",
                "import sys; from pathlib import Path; sys.path.insert(0, str(Path(r'' / \"src\"))); import raydium_lp1.scanner as s; raise SystemExit(s.main())",
                "--config",
                str(config),
            ]

        subprocess.Popen(cmd, cwd=ROOT, env=env)
        self._update_status(f"Started scanner with {config}", ok=True)

def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    LauncherApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()




