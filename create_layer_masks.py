import bpy


def _active_mesh_object():
    obj = bpy.context.object
    if obj is None:
        raise RuntimeError("No active object. Select a mesh object first.")
    if obj.type != "MESH":
        raise RuntimeError(f"Active object must be a MESH, got: {obj.type}")
    return obj


def _remove_node_group(name: str):
    ng = bpy.data.node_groups.get(name)
    if ng is not None:
        bpy.data.node_groups.remove(ng)


def _ensure_geo_nodes_modifier(obj, name: str):
    mod = obj.modifiers.get(name)
    if mod is None or mod.type != "NODES":
        mod = obj.modifiers.new(name, "NODES")
    return mod


def _new_geom_group(name: str):
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")

    # clear interface + nodes
    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    # interface sockets (Blender 5.0)
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    s_prev_en = ng.interface.new_socket(name="Preview Enabled", in_out="INPUT", socket_type="NodeSocketBool")
    s_prev_en.default_value = True

    s_prev_layer = ng.interface.new_socket(name="Preview Layer", in_out="INPUT", socket_type="NodeSocketInt")
    s_prev_layer.default_value = 0
    try:
        s_prev_layer.min_value = 0
    except Exception:
        pass

    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    return ng


def _make_height_mask_field(nt, mask_def: dict, location=(-900, 0)):
    """
    Height mask field (float 0..1):
      z -> map_range(min_height..max_height -> 0..1, clamp)
      then: clamp((v - ramp_low) / (ramp_high - ramp_low), 0..1)
    """
    nodes, links = nt.nodes, nt.links

    min_h = float(mask_def.get("min_height", 0.0))
    max_h = float(mask_def.get("max_height", 10.0))
    ramp_low = float(mask_def.get("ramp_low", 0.4))
    ramp_high = float(mask_def.get("ramp_high", 0.6))

    pos = nodes.new("GeometryNodeInputPosition")
    pos.location = (location[0], location[1])

    sep = nodes.new("ShaderNodeSeparateXYZ")  # allowed in geo trees
    sep.location = (location[0] + 200, location[1])

    mapr = nodes.new("ShaderNodeMapRange")    # allowed in geo trees
    mapr.location = (location[0] + 420, location[1])
    mapr.clamp = True
    mapr.inputs["From Min"].default_value = min_h
    mapr.inputs["From Max"].default_value = max_h
    mapr.inputs["To Min"].default_value = 0.0
    mapr.inputs["To Max"].default_value = 1.0

    low_sub = nodes.new("ShaderNodeMath")
    low_sub.location = (location[0] + 660, location[1] + 90)
    low_sub.operation = "SUBTRACT"
    low_sub.inputs[1].default_value = ramp_low

    high_sub = nodes.new("ShaderNodeMath")
    high_sub.location = (location[0] + 660, location[1] - 30)
    high_sub.operation = "SUBTRACT"
    high_sub.inputs[0].default_value = ramp_high
    high_sub.inputs[1].default_value = ramp_low

    div = nodes.new("ShaderNodeMath")
    div.location = (location[0] + 880, location[1] + 30)
    div.operation = "DIVIDE"
    div.use_clamp = True

    clamp = nodes.new("ShaderNodeClamp")
    clamp.location = (location[0] + 1080, location[1] + 30)

    links.new(pos.outputs["Position"], sep.inputs["Vector"])
    links.new(sep.outputs["Z"], mapr.inputs["Value"])
    links.new(mapr.outputs["Result"], low_sub.inputs[0])
    links.new(low_sub.outputs["Value"], div.inputs[0])
    links.new(high_sub.outputs["Value"], div.inputs[1])
    links.new(div.outputs["Value"], clamp.inputs["Value"])

    return clamp.outputs["Result"]


def _constant_float_field(nt, value: float, location=(-900, 0)):
    # Shader Value node isn't allowed in GeometryNodeTree in Blender 5.0,
    # use a Math node instead: ADD(0, value) => constant field.
    nodes = nt.nodes
    n = nodes.new("ShaderNodeMath")
    n.location = (location[0], location[1])
    n.operation = "ADD"
    n.inputs[0].default_value = 0.0
    n.inputs[1].default_value = float(value)
    return n.outputs["Value"]


def _math(nt, op: str, a, b, location=(0, 0), clamp=False, label=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.location = location
    n.operation = op
    n.use_clamp = bool(clamp)
    if label:
        n.label = label

    if isinstance(a, (int, float)):
        n.inputs[0].default_value = float(a)
    else:
        nt.links.new(a, n.inputs[0])

    if isinstance(b, (int, float)):
        n.inputs[1].default_value = float(b)
    else:
        nt.links.new(b, n.inputs[1])

    return n.outputs["Value"]


def _float_to_grayscale_vector(nt, x_float_socket, location=(0, 0)):
    """
    Geometry node trees can't add shader-only color combine nodes.
    Instead, store preview as a FLOAT_VECTOR attribute (x,x,x).
    """
    nodes, links = nt.nodes, nt.links

    comb = nodes.new("ShaderNodeCombineXYZ")
    comb.location = location

    links.new(x_float_socket, comb.inputs["X"])
    links.new(x_float_socket, comb.inputs["Y"])
    links.new(x_float_socket, comb.inputs["Z"])

    return comb.outputs["Vector"]


def create_terrain_layers(config):
    obj = _active_mesh_object()

    mod_name = str(config.get("geometry_modifier_name", "Terrain_Layer_Masks"))
    layers = list(config.get("layers", []))
    if not layers:
        raise RuntimeError("Config has no layers.")

    group_name = f"NG_{mod_name}"
    _remove_node_group(group_name)
    ng = _new_geom_group(group_name)

    nodes, links = ng.nodes, ng.links

    gin = nodes.new("NodeGroupInput")
    gin.location = (-1400, 0)

    gout = nodes.new("NodeGroupOutput")
    gout.location = (1900, 0)

    prev_geo = gin.outputs["Geometry"]

    # preview_mask = 0.0 initially
    preview_mask = _constant_float_field(ng, 0.0, location=(-1100, -520))

    x_base = -900
    y_base = 420
    y_step = -250

    for i, layer in enumerate(layers):
        layer_name = (str(layer.get("name", f"Layer_{i:02d}")).strip() or f"Layer_{i:02d}")
        mask_def = layer.get("mask")

        if isinstance(mask_def, dict) and mask_def.get("type") == "height":
            mask = _make_height_mask_field(ng, mask_def, location=(x_base, y_base + i * y_step))
        else:
            mask = _constant_float_field(ng, 0.0, location=(x_base, y_base + i * y_step))

        # Store per-layer float attribute
        store = nodes.new("GeometryNodeStoreNamedAttribute")
        store.location = (x_base + 600, y_base + i * y_step)
        store.domain = "POINT"
        store.data_type = "FLOAT"
        store.inputs["Name"].default_value = layer_name

        links.new(prev_geo, store.inputs["Geometry"])
        links.new(mask, store.inputs["Value"])
        prev_geo = store.outputs["Geometry"]

        # Preview selection: if (Preview Layer == i) then preview_mask = mask else keep
        cmp = nodes.new("ShaderNodeMath")
        cmp.location = (x_base + 280, y_base + i * y_step - 150)
        cmp.operation = "COMPARE"
        cmp.use_clamp = True
        links.new(gin.outputs["Preview Layer"], cmp.inputs[0])  # A
        cmp.inputs[1].default_value = float(i)                  # B
        cmp.inputs[2].default_value = 0.5                       # Threshold

        one_minus = _math(ng, "SUBTRACT", 1.0, cmp.outputs["Value"], location=(x_base + 500, y_base + i * y_step - 190))
        a_part = _math(ng, "MULTIPLY", one_minus, preview_mask, location=(x_base + 720, y_base + i * y_step - 220))
        b_part = _math(ng, "MULTIPLY", cmp.outputs["Value"], mask, location=(x_base + 720, y_base + i * y_step - 140))
        preview_mask = _math(ng, "ADD", a_part, b_part, location=(x_base + 940, y_base + i * y_step - 180))

    # Apply preview enabled (bool coerces to 0/1)
    preview_enabled = _math(ng, "MULTIPLY", preview_mask, gin.outputs["Preview Enabled"], location=(900, -520))

    # Store a grayscale VECTOR attribute (x,x,x) for easy visualization
    preview_vec = _float_to_grayscale_vector(ng, preview_enabled, location=(1120, -520))

    store_preview = nodes.new("GeometryNodeStoreNamedAttribute")
    store_preview.location = (1420, -520)
    store_preview.domain = "POINT"
    store_preview.data_type = "FLOAT_VECTOR"
    store_preview.inputs["Name"].default_value = "TerrainMaskPreview"

    links.new(prev_geo, store_preview.inputs["Geometry"])
    links.new(preview_vec, store_preview.inputs["Value"])

    links.new(store_preview.outputs["Geometry"], gout.inputs["Geometry"])

    # assign to modifier
    mod = _ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name

    return ng


def run():
    config = {
        "geometry_modifier_name": "Terrain_Layer_Masks",
        "layers": [
            {"name": "Underwater"},
            {
                "name": "Beach",
                "mask": {"type": "height", "min_height": 1.5, "max_height": 7.5, "ramp_low": 0.35, "ramp_high": 0.55},
            },
            {
                "name": "Grass",
                "mask": {"type": "height", "min_height": 3.5, "max_height": 8.0, "ramp_low": 0.45, "ramp_high": 0.65},
            },
            {
                "name": "Snow",
                "mask": {"type": "height", "min_height": 9.0, "max_height": 15.0, "ramp_low": 0.45, "ramp_high": 0.65},
            },
        ],
    }

    create_terrain_layers(config)


# Uncomment to run in Blender's text editor:
# run()
