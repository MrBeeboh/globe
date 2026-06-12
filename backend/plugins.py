"""Plugin registry — WWV-style extensibility for Globe layers & intel desk."""
import json
import os


def get_registry(root: str) -> dict:
    path = os.path.join(root, "data", "plugins.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)