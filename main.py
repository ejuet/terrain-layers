import importlib
import pkgutil
import sys
from pathlib import Path

REPO_ROOT = Path("/home/lisa/Repositories/Private/terrain-layers").resolve()
PACKAGE_NAME = "terrain_layers"

"""
Reload all modules to reflect recent changes without restarting Blender.
"Ctrl+shift+O > reopen current world" is not sufficient.
"""


def ensure_repo_on_path() -> None:
    repo_root_str = str(REPO_ROOT)
    if repo_root_str in sys.path:
        sys.path.remove(repo_root_str)
    sys.path.insert(0, repo_root_str)


def purge_package_modules(package_name: str) -> None:
    # Blender can keep stale modules alive across text reloads.
    for module_name in list(sys.modules):
        if module_name == package_name or module_name.startswith(f"{package_name}."):
            del sys.modules[module_name]


def import_package_tree(package_name: str):
    package = importlib.import_module(package_name)
    module_names = sorted(
        module_info.name
        for module_info in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{package_name}.",
        )
    )

    imported_modules = {package_name: package}
    for module_name in module_names:
        imported_modules[module_name] = importlib.import_module(module_name)

    return imported_modules


ensure_repo_on_path()
purge_package_modules(PACKAGE_NAME)
modules = import_package_tree(PACKAGE_NAME)
modules[f"{PACKAGE_NAME}.pipeline"].run()
