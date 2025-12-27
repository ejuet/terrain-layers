import bpy

# -----------------------------
# Small utilities (Blender 5.0)
# -----------------------------


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
