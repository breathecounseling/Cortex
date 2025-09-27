import os, json, re
from typing import Dict, Any

def scan_repo(base: str = "executor/plugins") -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(base):
        # Defensive: in test environments executor/plugins may not exist
        return idx
    for entry in os.listdir(base):
        pdir = os.path.join(base, entry)
        if not os.path.isdir(pdir):
            continue
        meta = {"description": "", "capabilities": set(), "symbols": set()}
        manifest = os.path.join(pdir, "plugin.json")
        if os.path.exists(manifest):
            try:
                with open(manifest, "r", encoding="utf-8") as f:
                    man = json.load(f)
                meta["description"] = man.get("description", "")
                meta["capabilities"] = set(man.get("capabilities", []))
            except Exception:
                pass
        for root, _, files in os.walk(pdir):
            for fn in files:
                if fn.endswith(".py"):
                    try:
                        with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
                            src = f.read()
                        meta["symbols"].update(re.findall(r"def\s+([A-Za-z_][\w]*)\s*\(", src))
                        meta["symbols"].update(re.findall(r"class\s+([A-Za-z_][\w]*)\s*[\(:]", src))
                    except Exception:
                        continue
        idx[entry] = meta
    return idx
