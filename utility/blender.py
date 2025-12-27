import bpy

# -----------------------------
# Small utilities (Blender 5.0)
# -----------------------------


# todo only used in anti_repetition, remove this
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
