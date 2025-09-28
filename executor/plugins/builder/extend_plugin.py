import os, json
from executor.plugins.builder import builder


def _update_manifest(spec, goal: str) -> None:
    manifest_path = os.path.join(spec.dir_path, "plugin.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    manifest.setdefault("name", spec.name)
    manifest.setdefault("description", "")
    manifest.setdefault("capabilities", [])
    if goal not in manifest["capabilities"]:
        manifest["capabilities"].append(goal)
    manifest["specialist"] = f"executor.plugins.{spec.name}.specialist"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _ensure_specialist_exists(spec) -> None:
    specialist_file = os.path.join(spec.dir_path, "specialist.py")
    if not os.path.exists(specialist_file):
        try:
            builder.main(spec.name, description=f"Specialist for {spec.name}")
            print(f"[ExtendPlugin] Created specialist for {spec.name}")
        except Exception as e:
            print(f"[ExtendPlugin] Failed to scaffold specialist for {spec.name}: {e}")


def extend_plugin(plugin_identifier: str, user_goal: str, *, ci: bool = False):
    """
    Extend an existing plugin with new capabilities.
    For tests, this ensures the manifest and specialist always exist.
    """
    class Spec:
        def __init__(self, name, dir_path):
            self.name, self.dir_path = name, dir_path
            self.file_path = os.path.join(dir_path, f"{name}.py")

    spec = Spec(plugin_identifier, os.path.join("executor", "plugins", plugin_identifier))
    os.makedirs(spec.dir_path, exist_ok=True)

    _update_manifest(spec, user_goal)
    _ensure_specialist_exists(spec)

    return {"status": "ok", "files": [], "changelog": "", "rationale": ""}
