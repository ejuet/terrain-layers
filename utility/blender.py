import bpy

# todo only used in anti_repetition, remove this
# -----------------------------
# Small utilities (Blender 5.0)
# -----------------------------


def add_socket(
    ng,
    *,
    in_out: str,
    name: str,
    socket_type: str,
    default=None,
    min_val=None,
    max_val=None
):
    s = ng.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if default is not None and hasattr(s, "default_value"):
        s.default_value = default
    if min_val is not None and hasattr(s, "min_value"):
        s.min_value = min_val
    if max_val is not None and hasattr(s, "max_value"):
        s.max_value = max_val
    return s


def get_or_create_group(group_name: str, build_fn):
    ng = bpy.data.node_groups.get(group_name)
    if ng and ng.bl_idname == "ShaderNodeTree":
        return ng
    return build_fn()


def rebuild_group_if_missing_inputs(
    group_name: str, required_inputs: set[str], build_fn
):
    ng = bpy.data.node_groups.get(group_name)
    if ng and ng.bl_idname == "ShaderNodeTree":
        iface_inputs = {
            s.name
            for s in ng.interface.items_tree
            if getattr(s, "in_out", None) == "INPUT"
        }
        if not required_inputs.issubset(iface_inputs):
            bpy.data.node_groups.remove(ng, do_unlink=True)
            return build_fn()
        return ng
    return build_fn()


def frame_nodes(nt, title: str, nodes_to_frame: list):
    """
    Put given nodes into a NodeFrame with a label/title.
    Returns the created frame.
    """
    if not nodes_to_frame:
        return None

    frame = nt.nodes.new("NodeFrame")
    frame.label = title
    frame.name = title

    # Place the frame roughly around the first node; Blender will grow/shrink visually.
    first = nodes_to_frame[0]
    frame.location = (first.location.x - 120, first.location.y + 120)

    for n in nodes_to_frame:
        if n:
            n.parent = frame

    return frame
