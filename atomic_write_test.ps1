from pathlib import Path
import json
import os
import tempfile

def atomic_write_json(path: Path, obj: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(obj, indent=2, sort_keys=True))
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass

p = Path("atomic_test.json")
atomic_write_json(p, {"a": 1, "b": {"c": 2}})
print(p.read_text(encoding="utf-8"))
print(json.loads(p.read_text(encoding="utf-8")))
