"""Rename legacy Pi05 camera features in a local checkpoint, keeping backups."""
import argparse
import json
import shutil
from pathlib import Path


NAMES = {
    "observation.images.base_0_rgb": "observation.images.top",
    "observation.images.left_wrist_0_rgb": "observation.images.left_wrist",
    "observation.images.right_wrist_0_rgb": "observation.images.right_wrist",
}


def rename(value):
    if isinstance(value, str):
        for old, new in NAMES.items():
            if value == old or value.startswith(old + "."):
                return new + value[len(old):]
        return value
    if isinstance(value, list):
        return [rename(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            new_key = rename(key)
            if new_key in result:
                raise ValueError(f"Camera rename would overwrite {new_key}")
            result[new_key] = rename(item)
        return result
    return value


def migrate(path):
    path = Path(path).resolve()
    if not (path / "config.json").is_file():
        raise FileNotFoundError(path / "config.json")
    changes = []
    for file in sorted(path.glob("*.json")):
        original = json.loads(file.read_text(encoding="utf-8"))
        updated = rename(original)
        if updated != original:
            changes.append((file, json.dumps(updated, indent=4, ensure_ascii=False) + "\n", None))
    # Processor statistics store feature names in tensor keys; model weights do not.
    for file in sorted(path.glob("policy_*processor*.safetensors")):
        from safetensors import safe_open
        from safetensors.torch import load_file

        with safe_open(str(file), framework="pt", device="cpu") as handle:
            keys = list(handle.keys())
            metadata = handle.metadata()
        if any(rename(key) != key for key in keys):
            changes.append((file, rename(load_file(str(file))), metadata))
    # Validate everything before writing, and never overwrite an earlier backup.
    for file, _, _ in changes:
        backup = file.with_name(file.name + ".bak")
        if backup.exists():
            raise FileExistsError(f"Backup already exists: {backup}")
    for file, _, _ in changes:
        shutil.copy2(file, file.with_name(file.name + ".bak"))
    for file, updated, metadata in changes:
        if isinstance(updated, str):
            file.write_text(updated, encoding="utf-8")
        else:
            from safetensors.torch import save_file

            save_file(updated, str(file), metadata=metadata)
        print(f"Updated {file.name} (backup: {file.name}.bak)")
    if not changes:
        print("No legacy camera names found; no files changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    migrate(parser.parse_args().checkpoint)
