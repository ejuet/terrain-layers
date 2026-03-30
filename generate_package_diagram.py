#!/usr/bin/env python3

import ast
import sys
from collections import defaultdict
from pathlib import Path


palette = {
    "biomes": ("#d97706", "#fff2e2", "#f4b26a"),
    "config": ("#2563eb", "#e8f0ff", "#7aa5ff"),
    "masks": ("#16a34a", "#e9f8ee", "#7ed798"),
    "paths": ("#dc2626", "#fdecec", "#f2a2a2"),
    "preview_shader": ("#7c3aed", "#f2eafe", "#b9a0f6"),
    "shader": ("#0891b2", "#e8f7fb", "#78cfe2"),
    "utility": ("#4b5563", "#eef1f4", "#aab3bf"),
}
default_colors = ("#6b7280", "#f3f4f6", "#cbd5e1")


def module_name(path: Path, root_dir: Path) -> str:
    rel = path.relative_to(root_dir).with_suffix("")
    parts = rel.parts
    if parts[-1] == "__init__":
        return ".".join(parts[:-1])
    return ".".join(parts)


def resolve_local_import(module: str, node: ast.ImportFrom) -> str | None:
    if node.level:
        base = module.split(".")[:-node.level]
        if node.module:
            return ".".join(base + node.module.split("."))
        return ".".join(base)
    return node.module


def nearest_known(name: str | None, modules: set[str]) -> str | None:
    current = name or ""
    while current:
        if current in modules:
            return current
        if "." not in current:
            return None
        current = current.rsplit(".", 1)[0]
    return None


def top_level_group(name: str) -> str:
    parts = name.split(".")
    return parts[1] if len(parts) > 1 else parts[0]


def colors_for(name: str) -> tuple[str, str, str]:
    return palette.get(top_level_group(name), default_colors)


def dot_id(name: str) -> str:
    return name.replace(".", "_")


def node_label(mod: str, packages: set[str]) -> str:
    if mod in packages:
        return "__init__"
    return mod.split(".")[-1]


def build_dot(root_dir: Path, project_name: str) -> str:
    package_dir = root_dir / project_name

    module_paths = {}
    for path in sorted(package_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module_paths[module_name(path, root_dir)] = path

    modules = set(module_paths)
    packages = set()
    children = defaultdict(set)
    for mod in modules:
        parts = mod.split(".")
        for i in range(1, len(parts)):
            packages.add(".".join(parts[:i]))
        if "." in mod:
            children[".".join(parts[:-1])].add(mod)

    subpackages = defaultdict(set)
    for pkg in sorted(packages):
        if "." in pkg:
            subpackages[pkg.rsplit(".", 1)[0]].add(pkg)

    edges = set()
    for mod, path in module_paths.items():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dep = nearest_known(alias.name, modules)
                    if dep and dep != mod:
                        edges.add((mod, dep))
            elif isinstance(node, ast.ImportFrom):
                dep = nearest_known(resolve_local_import(mod, node), modules)
                if dep and dep != mod:
                    edges.add((mod, dep))

    lines = [
        "digraph packages_terrain_layers {",
        '  graph [',
        '    rankdir=LR,',
        '    splines=polyline,',
        '    compound=true,',
        '    newrank=true,',
        '    ranksep=1.1,',
        '    nodesep=0.4,',
        '    pad=0.3,',
        '    fontname="Helvetica",',
        '    labelloc=t,',
        f'    label="Package Dependencies: {project_name}"',
        '  ];',
        '  node [',
        '    shape=box,',
        '    style="rounded,filled",',
        '    fontname="Helvetica",',
        '    fontsize=11,',
        '    margin="0.10,0.06",',
        '    color="#475569",',
        '    fillcolor="white"',
        '  ];',
        '  edge [',
        '    color="#475569",',
        '    arrowsize=0.7,',
        '    penwidth=1.1',
        '  ];',
        f'  "{project_name}" [label="__init__", fillcolor="#f8fafc", color="#475569", penwidth=1.4];',
        f'  "{project_name}.pipeline" [label="pipeline", fillcolor="white", color="#475569", penwidth=1.3];',
    ]

    def emit_cluster(pkg: str, depth: int = 0) -> None:
        accent, background, border = colors_for(pkg)
        indent = "  " * (depth + 1)
        lines.append(f'{indent}subgraph cluster_{dot_id(pkg)} {{')
        lines.append(f'{indent}  label="{pkg.split(".")[-1]}";')
        lines.append(f'{indent}  style="rounded,filled";')
        lines.append(f'{indent}  color="{border}";')
        lines.append(f'{indent}  pencolor="{accent}";')
        lines.append(f'{indent}  fillcolor="{background}";')
        lines.append(f'{indent}  fontname="Helvetica-Bold";')
        lines.append(f'{indent}  fontsize=13;')

        if pkg in modules:
            lines.append(
                f'{indent}  "{pkg}" [label="__init__", fillcolor="{background}", color="{accent}", penwidth=1.4];'
            )

        for child_pkg in sorted(subpackages.get(pkg, ())):
            emit_cluster(child_pkg, depth + 1)

        direct_modules = sorted(mod for mod in children.get(pkg, ()) if mod not in packages)
        for mod in direct_modules:
            lines.append(
                f'{indent}  "{mod}" [label="{node_label(mod, packages)}", fillcolor="white", color="{accent}", penwidth=1.2];'
            )

        lines.append(f"{indent}}}")

    for child_pkg in sorted(subpackages.get(project_name, ())):
        emit_cluster(child_pkg)

    for source, target in sorted(edges):
        same_group = source.rsplit(".", 1)[0] == target.rsplit(".", 1)[0]
        edge_attrs = ["minlen=2"]
        if same_group:
            edge_attrs.extend(['color="#94a3b8"', "penwidth=1.0"])
        else:
            edge_attrs.extend(['color="#334155"', "penwidth=1.2"])
        lines.append(f'  "{source}" -> "{target}" [{", ".join(edge_attrs)}];')

    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: generate_package_diagram.py <root_dir> <project_name> <output_dot_path>",
            file=sys.stderr,
        )
        return 1

    root_dir = Path(sys.argv[1]).resolve()
    project_name = sys.argv[2]
    output_path = Path(sys.argv[3])
    output_path.write_text(build_dot(root_dir, project_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
