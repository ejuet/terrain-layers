# rearrange.py
import bpy


def _find_node_editor_context():
    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "NODE_EDITOR":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            space = next((s for s in area.spaces if s.type == "NODE_EDITOR"), None)
            if space is None:
                continue
            return window, screen, area, region, space
    return None


def _pick_area_to_temporarily_convert(screen):
    preferred = {
        "VIEW_3D",
        "OUTLINER",
        "PROPERTIES",
        "IMAGE_EDITOR",
        "TEXT_EDITOR",
        "DOPESHEET_EDITOR",
    }
    avoid = {"TOPBAR", "STATUSBAR"}
    candidates = [a for a in screen.areas if a.type not in avoid]
    if not candidates:
        return None
    preferred_candidates = [a for a in candidates if a.type in preferred]
    pool = preferred_candidates or candidates
    return max(pool, key=lambda a: a.width * a.height)


def _get_or_make_node_editor_context():
    ctx = _find_node_editor_context()
    if ctx is not None:
        return ctx, (lambda: None)

    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        area = _pick_area_to_temporarily_convert(screen)
        if area is None:
            continue

        old_type = area.type
        try:
            area.type = "NODE_EDITOR"
        except Exception:
            continue

        def restore(area=area, old_type=old_type):
            try:
                area.type = old_type
            except Exception:
                pass

        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        space = next((s for s in area.spaces if s.type == "NODE_EDITOR"), None)
        if region is None or space is None:
            restore()
            continue

        return (window, screen, area, region, space), restore

    raise RuntimeError(
        "arrange_nodes_in_shader_editor: Could not find or create a NODE_EDITOR area in any window."
    )


def _set_space_to_tree(space, node_tree):
    if hasattr(space, "node_tree"):
        space.node_tree = node_tree

    if hasattr(space, "tree_type"):
        tree_type = getattr(node_tree, "bl_idname", None) or getattr(
            space, "tree_type", None
        )
        if tree_type:
            try:
                space.tree_type = tree_type
            except Exception:
                pass


def _opfunc_from_bl_idname(bl_idname: str):
    """
    Convert 'node.some_op' -> bpy.ops.node.some_op
    Convert 'node_arrange.some_op' -> bpy.ops.node_arrange.some_op
    Return callable or None.
    """
    if not bl_idname or "." not in bl_idname:
        return None
    cat, op = bl_idname.split(".", 1)
    ops_cat = getattr(bpy.ops, cat, None)
    if ops_cat is None:
        return None
    return getattr(ops_cat, op, None)


def _discover_node_arrange_ops():
    """
    Find registered operators that look like "Node Arrange" in Blender 5.x Extensions.
    Prefer operators coming from bl_ext.blender_org.node_arrange.
    Return list of (bl_idname, op_callable).
    """
    target_mod = "bl_ext.blender_org.node_arrange"
    found = []

    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        if not isinstance(cls, type):
            continue
        # Operator classes are subclasses of bpy.types.Operator and have bl_idname
        try:
            if not issubclass(cls, bpy.types.Operator):
                continue
        except Exception:
            continue

        bl_idname = getattr(cls, "bl_idname", None)
        if not bl_idname:
            continue

        mod = getattr(cls, "__module__", "") or ""
        op = _opfunc_from_bl_idname(bl_idname)
        if op is None:
            continue

        # Heuristics: only keep "arrange-ish" operators
        lid = bl_idname.lower()
        if not any(k in lid for k in ("arrange", "layout", "auto", "na_")):
            continue

        # Score: prefer the extension module operators
        score = 0
        if mod.startswith(target_mod):
            score += 100
        if "arrange" in lid:
            score += 10
        if "layout" in lid:
            score += 5

        found.append((score, bl_idname, op))

    found.sort(key=lambda t: t[0], reverse=True)
    # de-dup by bl_idname
    dedup = []
    seen = set()
    for _, bl_idname, op in found:
        if bl_idname in seen:
            continue
        seen.add(bl_idname)
        dedup.append((bl_idname, op))
    return dedup


def _try_call_op(op_callable):
    """
    Try EXEC_DEFAULT then no-arg call.
    Return True on success. Raise on real failures.
    """
    try:
        try:
            op_callable("EXEC_DEFAULT")
        except TypeError:
            op_callable()
        return True
    except AttributeError as e:
        # wrapper exists but operator not actually registered
        if "could not be found" in str(e).lower():
            return False
        raise


def arrange_nodes(node_tree: bpy.types.NodeTree, *, do_redraw: bool = True):
    """
    Arrange nodes in the given node_tree using available Node Arrange operators.
    Prints a warning if no operator could be found.
    """
    try:
        _arrange_nodes(node_tree, do_redraw=do_redraw)
    except Exception as e:
        print(f"arrange_nodes_in_shader_editor: Warning: Could not arrange nodes: {e}")


def _arrange_nodes(node_tree: bpy.types.NodeTree, *, do_redraw: bool = True):
    if node_tree is None:
        raise ValueError("arrange_nodes_in_shader_editor: node_tree is None")

    (window, screen, area, region, space), restore_ui = (
        _get_or_make_node_editor_context()
    )

    nodes = node_tree.nodes
    prev_selected = {n: bool(n.select) for n in nodes}
    prev_active = nodes.active

    try:
        for n in nodes:
            n.select = True

        out = next(
            (
                n
                for n in nodes
                if n.bl_idname
                in {"ShaderNodeOutputMaterial", "CompositorNodeComposite"}
            ),
            None,
        )
        nodes.active = out or (nodes[0] if nodes else None)

        _set_space_to_tree(space, node_tree)

        with bpy.context.temp_override(
            window=window,
            screen=screen,
            area=area,
            region=region,
            space_data=space,
        ):
            if do_redraw:
                try:
                    bpy.ops.wm.redraw_timer(type="DRAW_WIN", iterations=1)
                except Exception:
                    pass

            # 1) Prefer dynamically discovered Node Arrange operators (works with Extensions naming)
            discovered = _discover_node_arrange_ops()
            for bl_idname, op in discovered:
                if _try_call_op(op):
                    return bl_idname  # return the operator id we used

            # 2) Final fallback: Blender built-in arrange (not the addon), if present
            # (Some versions have node.view_selected / align ops etc; this is intentionally minimal)
            raise RuntimeError(
                "arrange_nodes_in_shader_editor: Node Arrange extension is enabled, "
                "but no callable arrange/layout operator was found/registered."
            )

    finally:
        for n, sel in prev_selected.items():
            if n and n.id_data == node_tree:
                n.select = sel
        nodes.active = prev_active
        restore_ui()
