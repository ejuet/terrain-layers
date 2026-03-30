import bpy
from typing import Optional, Dict, Tuple, Set, List
from dataclasses import dataclass

# -----------------------------
# Generic upstream search utils
# -----------------------------


def _node_or_image_name_matches(
    tex_node: bpy.types.ShaderNodeTexImage, tokens: List[str]
) -> bool:
    """
    True if any token appearas (case-insensitive) in:
      - image.name
      - node.label
      - node.name
    """
    haystacks = []
    img = getattr(tex_node, "image", None)
    if img and getattr(img, "name", None):
        haystacks.append(img.name)
    if getattr(tex_node, "label", None):
        haystacks.append(tex_node.label)
    if getattr(tex_node, "name", None):
        haystacks.append(tex_node.name)

    joined = " ".join(haystacks).lower()
    return any(t.lower() in joined for t in tokens if t)


def _collect_upstream_image_nodes_from_socket(
    sock: bpy.types.NodeSocket,
    *,
    visited: Optional[Set[Tuple[int, int]]] = None,
    max_depth: int = 200,
    max_found: int = 64,
) -> List[bpy.types.ShaderNodeTexImage]:
    """
    Walk upstream from a socket and collect ALL ShaderNodeTexImage nodes found.
    Handles node groups by entering them via the corresponding Group Output socket.
    """
    if sock is None or max_depth <= 0:
        return []
    if visited is None:
        visited = set()

    # key by (node pointer, socket pointer) to avoid loops
    try:
        key = (sock.node.as_pointer(), sock.as_pointer())
        if key in visited:
            return []
        visited.add(key)
    except Exception:
        pass

    if not getattr(sock, "is_linked", False) or not sock.links:
        return []

    found: List[bpy.types.ShaderNodeTexImage] = []

    for link in sock.links:
        from_node = link.from_node
        from_sock = link.from_socket
        if from_node is None or from_sock is None:
            continue

        # Direct image texture
        if (
            from_node.bl_idname == "ShaderNodeTexImage"
            and getattr(from_node, "image", None) is not None
        ):
            found.append(from_node)  # type: ignore
            if len(found) >= max_found:
                return found
            # Don't return early; keep searching other branches.

        # If upstream is a Group node, jump inside the group:
        if from_node.bl_idname == "ShaderNodeGroup":
            group_tree = getattr(from_node, "node_tree", None)
            if group_tree:
                group_out = next(
                    (n for n in group_tree.nodes if n.bl_idname == "NodeGroupOutput"),
                    None,
                )
                if group_out and from_sock.name in group_out.inputs:
                    inner_sock = group_out.inputs[from_sock.name]
                    found.extend(
                        _collect_upstream_image_nodes_from_socket(
                            inner_sock,
                            visited=visited,
                            max_depth=max_depth - 1,
                            max_found=max_found - len(found),
                        )
                    )
                    if len(found) >= max_found:
                        return found

        # Otherwise, walk through inputs of the node we hit
        for inp in getattr(from_node, "inputs", []):
            if not getattr(inp, "is_linked", False):
                continue
            found.extend(
                _collect_upstream_image_nodes_from_socket(
                    inp,
                    visited=visited,
                    max_depth=max_depth - 1,
                    max_found=max_found - len(found),
                )
            )
            if len(found) >= max_found:
                return found

        # Also try continuing from the exact output socket we came from
        found.extend(
            _collect_upstream_image_nodes_from_socket(
                from_sock,
                visited=visited,
                max_depth=max_depth - 1,
                max_found=max_found - len(found),
            )
        )
        if len(found) >= max_found:
            return found

    return found


def _select_best_tex_node(
    candidates: List[bpy.types.ShaderNodeTexImage],
    *,
    prop_name: str,
) -> Optional[bpy.types.ShaderNodeTexImage]:
    """
    If multiple candidates exist, prefer the one whose name contains the property name
    (e.g. "normal") (plus some helpful variants). Otherwise return the first.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    p = (prop_name or "").strip().lower()
    # Primary requirement: property name in the texture/image name.
    # Add a few practical variants so base_color works with common filenames.
    token_variants: Dict[str, List[str]] = {
        "base_color": ["base_color", "basecolor", "albedo", "diffuse", "color"],
        "roughness": ["roughness", "rough"],
        "normal": ["normal", "nrm", "norm"],
        "displacement": ["displacement", "disp", "height"],
    }
    tokens = token_variants.get(p, [p]) if p else []

    # First pass: any match wins (keep original order, which is "closest-first-ish")
    for node in candidates:
        if _node_or_image_name_matches(node, tokens):
            return node

    # Fallback: no name match, just pick first discovered
    return candidates[0]


def _find_upstream_image_node_from_socket(
    sock: bpy.types.NodeSocket,
    visited: Optional[Set[Tuple[int, int]]] = None,
    max_depth: int = 200,
    *,
    prop_name: Optional[str] = None,
) -> Optional[bpy.types.ShaderNodeTexImage]:
    """
    Return the best ShaderNodeTexImage found upstream of sock.
    If multiple are found, prefer the one whose name contains prop_name (e.g. "normal").
    """
    candidates = _collect_upstream_image_nodes_from_socket(
        sock, visited=visited, max_depth=max_depth
    )
    return _select_best_tex_node(candidates, prop_name=(prop_name or ""))


def _get_active_material_output(nt: bpy.types.NodeTree) -> Optional[bpy.types.Node]:
    return next(
        (
            n
            for n in nt.nodes
            if n.bl_idname == "ShaderNodeOutputMaterial"
            and getattr(n, "is_active_output", False)
        ),
        None,
    ) or next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None)


def _find_principled_connected_to_output_surface(
    nt: bpy.types.NodeTree,
) -> Optional[bpy.types.Node]:
    """
    Try to locate a Principled BSDF that actually feeds the active Material Output Surface.
    Falls back to first Principled if wiring is complex.
    """
    out = _get_active_material_output(nt)
    if not out:
        return next(
            (n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None
        )

    surf = out.inputs.get("Surface")
    if surf and surf.is_linked and surf.links:
        n0 = surf.links[0].from_node
        if n0 and n0.bl_idname == "ShaderNodeBsdfPrincipled":
            return n0

        seen = set()
        queue = [surf]
        while queue:
            s = queue.pop(0)
            if not s.is_linked:
                continue
            for lk in s.links:  # type: ignore
                fn = lk.from_node
                if not fn:
                    continue
                ptr = fn.as_pointer()
                if ptr in seen:
                    continue
                seen.add(ptr)
                if fn.bl_idname == "ShaderNodeBsdfPrincipled":
                    return fn
                for inp in fn.inputs:
                    if inp.is_linked:
                        queue.append(inp)

    return next(
        (n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None
    )


# ----------------------------------------
# Public API: get maps from a material
# ----------------------------------------

PROPERTY_SPECS = {
    "base_color": {"kind": "principled_input", "socket": "Base Color"},
    "roughness": {"kind": "principled_input", "socket": "Roughness"},
    "normal": {"kind": "principled_input", "socket": "Normal"},
    "displacement": {"kind": "material_output_input", "socket": "Displacement"},
}


def get_material_image_for_property(
    material_name: str,
    prop: str,
) -> Optional[bpy.types.Image]:
    """
    Return the bpy.types.Image used upstream of a given material property, if found.
    """
    p = prop.strip().lower()
    aliases = {
        "albedo": "base_color",
        "color": "base_color",
        "base colour": "base_color",
        "base color": "base_color",
        "height": "displacement",
        "disp": "displacement",
    }
    p = aliases.get(p, p)
    if p not in PROPERTY_SPECS:
        raise ValueError(
            f"Unsupported property '{prop}'. Use one of: {', '.join(PROPERTY_SPECS.keys())}"
        )

    mat = bpy.data.materials.get(material_name)
    if mat is None:
        raise RuntimeError(
            f'Material "{material_name}" not found in bpy.data.materials'
        )
    if not mat.use_nodes or not mat.node_tree:
        raise RuntimeError(
            f'Material "{material_name}" has no node tree (use_nodes off or missing)'
        )

    nt = mat.node_tree
    spec = PROPERTY_SPECS[p]

    if spec["kind"] == "principled_input":
        principled = _find_principled_connected_to_output_surface(nt)
        if not principled:
            return None
        sock = principled.inputs.get(spec["socket"])
        tex_node = _find_upstream_image_node_from_socket(sock, prop_name=p)  # type: ignore
        return tex_node.image if tex_node and tex_node.image else None

    if spec["kind"] == "material_output_input":
        out = _get_active_material_output(nt)
        if not out:
            return None
        sock = out.inputs.get(spec["socket"])
        tex_node = _find_upstream_image_node_from_socket(sock, prop_name=p)  # type: ignore
        return tex_node.image if tex_node and tex_node.image else None

    return None


@dataclass(frozen=True, slots=True)
class MaterialPBRImages:
    base_color: Optional[bpy.types.Image]
    roughness: Optional[bpy.types.Image]
    normal: Optional[bpy.types.Image]
    displacement: Optional[bpy.types.Image]


def get_material_pbr_images(
    material_name: str,
    *,
    include_unlinked: bool = True,
) -> MaterialPBRImages:
    result = {}
    for key in ("base_color", "roughness", "normal", "displacement"):
        img = get_material_image_for_property(material_name, key)
        if include_unlinked or img is not None:
            result[key] = img
    return MaterialPBRImages(
        base_color=result.get("base_color"),
        roughness=result.get("roughness"),
        normal=result.get("normal"),
        displacement=result.get("displacement"),
    )
