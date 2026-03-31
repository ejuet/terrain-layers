def _build_repro_mesh_object(name: str, location: tuple[float, float, float]):
    import bpy

    mesh = bpy.data.meshes.get(name)
    if mesh is None:
        mesh = bpy.data.meshes.new(name)
    mesh.clear_geometry()
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)],
        [],
        [(0, 1, 2)],
    )
    mesh.update()

    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
    else:
        obj.data = mesh
    obj.location = location
    return obj


def _clear_node_tree(tree):
    for item in list(tree.interface.items_tree):
        tree.interface.remove(item)
    tree.nodes.clear()


def _rebuild_shared_source_group(group_name: str, source_object, *, output_name: str):
    import bpy

    group = bpy.data.node_groups.get(group_name)
    if group is None:
        group = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    _clear_node_tree(group)
    group.interface.new_socket(
        name=output_name,
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    nodes = group.nodes
    links = group.links
    group_output = nodes.new("NodeGroupOutput")
    object_info = nodes.new("GeometryNodeObjectInfo")
    object_info.transform_space = "RELATIVE"
    object_info.inputs["Object"].default_value = source_object
    links.new(object_info.outputs["Geometry"], group_output.inputs[output_name])
    return group


def _build_modifier_using_shared_group(
    target_object,
    *,
    modifier_name: str,
    shared_group_name: str,
    source_object,
    source_output_name: str,
):
    import bpy

    modifier = target_object.modifiers.get(modifier_name)
    if modifier is None or modifier.type != "NODES":
        modifier = target_object.modifiers.new(modifier_name, "NODES")

    tree = bpy.data.node_groups.get(modifier_name)
    if tree is None:
        tree = bpy.data.node_groups.new(modifier_name, "GeometryNodeTree")

    _clear_node_tree(tree)
    tree.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    tree.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    nodes = tree.nodes
    links = tree.links
    group_input = nodes.new("NodeGroupInput")
    group_output = nodes.new("NodeGroupOutput")
    join_geometry = nodes.new("GeometryNodeJoinGeometry")
    shared_group_node = nodes.new("GeometryNodeGroup")

    # try to get the shared group by name
    # comment this out to observe the issue
    shared_group = bpy.data.node_groups.get(shared_group_name)
    if shared_group is not None:
        print(
            f"Shared group '{shared_group_name}' already exists, reusing it for modifier '{modifier_name}'"
        )
        shared_group_node.node_tree = shared_group
    else:
        shared_group_node.node_tree = _rebuild_shared_source_group(
            shared_group_name,
            source_object,
            output_name=source_output_name,
        )

    links.new(group_input.outputs["Geometry"], join_geometry.inputs["Geometry"])
    source_socket = shared_group_node.outputs.get(source_output_name)
    if source_socket is not None:
        links.new(source_socket, join_geometry.inputs["Geometry"])
    links.new(join_geometry.outputs["Geometry"], group_output.inputs["Geometry"])

    modifier.node_group = tree
    return tree


def _inspect_modifier_connection(tree, *, source_output_name: str):
    shared_group_node = next(
        (node for node in tree.nodes if node.bl_idname == "GeometryNodeGroup"),
        None,
    )
    join_geometry = next(
        (node for node in tree.nodes if node.bl_idname == "GeometryNodeJoinGeometry"),
        None,
    )
    source_socket = (
        None
        if shared_group_node is None
        else shared_group_node.outputs.get(source_output_name)
    )
    join_inputs = [] if join_geometry is None else list(join_geometry.inputs)
    join_has_shared_input = any(
        socket.is_linked
        and any(link.from_node == shared_group_node for link in socket.links)
        for socket in join_inputs
    )
    return {
        "tree_name": tree.name,
        "source_output_present": source_socket is not None,
        "source_output_is_linked": (
            False if source_socket is None else source_socket.is_linked
        ),
        "join_has_shared_input": join_has_shared_input,
        "shared_group_tree": (
            None
            if shared_group_node is None or shared_group_node.node_tree is None
            else shared_group_node.node_tree.name
        ),
    }


def reproduce_shared_group_reuse_issue():
    import bpy

    prefix = "TL_Repro_"
    target_object = _build_repro_mesh_object(
        f"{prefix}Target",
        location=(0.0, 0.0, 0.0),
    )
    source_a = _build_repro_mesh_object(
        f"{prefix}Source_A",
        location=(2.0, 0.0, 0.0),
    )
    source_b = _build_repro_mesh_object(
        f"{prefix}Source_B",
        location=(4.0, 0.0, 0.0),
    )

    shared_group_name = f"{prefix}SharedSource"

    print("\n=== Repro: same shared node-group name across two modifiers ===")
    modifier_a_tree = _build_modifier_using_shared_group(
        target_object,
        modifier_name=f"{prefix}Modifier_A",
        shared_group_name=shared_group_name,
        source_object=source_a,
        source_output_name="Geometry",
    )
    bpy.context.view_layer.update()
    print("After building modifier A:")
    print(_inspect_modifier_connection(modifier_a_tree, source_output_name="Geometry"))

    modifier_b_tree = _build_modifier_using_shared_group(
        target_object,
        modifier_name=f"{prefix}Modifier_B",
        shared_group_name=shared_group_name,
        source_object=source_b,
        source_output_name="Geometry",
    )
    bpy.context.view_layer.update()
    print("After building modifier B with the same shared group name:")
    print(_inspect_modifier_connection(modifier_a_tree, source_output_name="Geometry"))
    print(_inspect_modifier_connection(modifier_b_tree, source_output_name="Geometry"))
