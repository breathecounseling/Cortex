# executor/plugins/repo_analyzer/repo_analyzer.py
from __future__ import annotations
import os, re, json
from typing import Dict, Any

def scan_repo(base: str = "executor/plugins") -> Dict[str, Dict[str, Any]]:
    """
    Scan the repo for plugins. Prefer plugin.json manifests;
    fallback to scraping function/class names.
    Returns: { plugin_name: { "description": str, "capabilities": set(), "symbols": set() } }
    """
    idx: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(base):
        return idx

    for entry in os.listdir(base):
        plugin_dir = os.path.join(base, entry)
        if not os.path.isdir(plugin_dir):
            continue

        meta: Dict[str, Any] = {"description": "", "capabilities": set(), "symbols": set()}
        manifest_path = os.path.join(plugin_dir, "plugin.json")

        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                meta["description"] = manifest.get("description", "")
                meta["capabilities"] = set(manifest.get("capabilities", []))
            except Exception:
                pass

        # fallback: scrape symbols
        if not meta["capabilities"]:
            for root, _, files in os.walk(plugin_dir):
                for fn in files:
                    if fn.endswith(".py"):
                        try:
                            with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
                                src = f.read()
                            meta["symbols"].update(re.findall(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", src))
                            meta["symbols"].update(re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[\(:]", src))
                        except Exception:
                            continue

        idx[entry] = meta

    return idx