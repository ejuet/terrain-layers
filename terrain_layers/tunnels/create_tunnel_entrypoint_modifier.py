from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from terrain_layers.tunnels.create_tunnel_modifier import (
    create_tunnel_portal_cutter_group,
)
from terrain_layers.tunnels.tunnel_types import MineShaftEntry, TunnelShape
from terrain_layers.shader.material_types import GroundMaterial
from terrain_layers.paths.path_source import ensure_curve_object
from terrain_layers.utility.object_info_group import add_object_info_nodes
from terrain_layers.utility.frame_nodes import frame_nodes
from terrain_layers.utility.geo_nodes import (
    ensure_geo_nodes_modifier,
    get_terrain_object,
    remove_node_group,
)
from terrain_layers.utility.rearrange import arrange_nodes

if TYPE_CHECKING:
    from terrain_layers.config.config_types import TerrainConfig


MINE_SHAFT_LOG_MATERIAL_NAME = "TerrainTunnelMineShaftLog"
MINE_SHAFT_ENTRIES_COLLECTION_NAME = "TerrainTunnelMineShaftEntries"
LEGACY_MINESHAFT_ENTRIES_COLLECTION_NAME = "TerrainTunnelMineshaftEntries"


def _get_mineshaft_log_material(
    ground_material: GroundMaterial | None = None,
) -> bpy.types.Material:
    """Return the configured log material or the simple brown fallback."""
    if ground_material is not None:
        # Imported lazily to keep tunnel configuration independent from the
        # shader implementation.
        from terrain_layers.shader.create_shader import create_ground_material_shader

        return create_ground_material_shader(
            ground_material,
            MINE_SHAFT_LOG_MATERIAL_NAME,
        )

    material = bpy.data.materials.get(MINE_SHAFT_LOG_MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(MINE_SHAFT_LOG_MATERIAL_NAME)
    material.diffuse_color = (0.20, 0.105, 0.045, 1.0)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.inputs["Base Color"].default_value = (0.20, 0.105, 0.045, 1.0)
    principled.inputs["Roughness"].default_value = 0.8
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    return material


def _clear_mineshaft_entries() -> bpy.types.Collection:
    legacy_collection = bpy.data.collections.get(LEGACY_MINESHAFT_ENTRIES_COLLECTION_NAME)
    if legacy_collection is not None:
        for entry in list(legacy_collection.objects):
            bpy.data.objects.remove(entry, do_unlink=True)
        bpy.data.collections.remove(legacy_collection)
    collection = bpy.data.collections.get(MINE_SHAFT_ENTRIES_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(MINE_SHAFT_ENTRIES_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(collection)
    for entry in list(collection.objects):
        bpy.data.objects.remove(entry, do_unlink=True)
    return collection


def _add_cube_log(
    collection: bpy.types.Collection,
    *,
    name: str,
    center: Vector,
    right: Vector,
    forward: Vector,
    up: Vector,
    dimensions: tuple[float, float, float],
    material: bpy.types.Material,
) -> None:
    mesh = bpy.data.meshes.new(name)
    half = tuple(dimension / 2 for dimension in dimensions)
    vertices = [
        (x, y, z)
        for x in (-half[0], half[0])
        for y in (-half[1], half[1])
        for z in (-half[2], half[2])
    ]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    log = bpy.data.objects.new(name, mesh)
    collection.objects.link(log)
    orientation = Matrix((right, forward, up)).transposed().to_4x4()
    # Bake dimensions into the mesh instead of object scale. The PBR material
    # samples Object coordinates, so applied dimensions preserve a consistent
    # real-world texture scale across the thin and long sides of each beam.
    log.matrix_world = Matrix.Translation(center) @ orientation


def _create_mineshaft_entry_objects(
    terrain: bpy.types.Object,
    curve: bpy.types.Object,
    tunnel_width: float,
    tunnel_height: float,
    entry: MineShaftEntry,
    collection: bpy.types.Collection,
) -> None:
    """Create three-log frames at exact curve-segment/terrain intersections."""
    material = _get_mineshaft_log_material(entry.ground_material)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    terrain_eval = terrain.evaluated_get(depsgraph)
    terrain_mesh = terrain_eval.to_mesh()
    curve_eval = curve.evaluated_get(depsgraph)
    curve_mesh = curve_eval.to_mesh()
    try:
        bvh = BVHTree.FromPolygons(
            [vertex.co for vertex in terrain_mesh.vertices],
            [polygon.vertices[:] for polygon in terrain_mesh.polygons],
            all_triangles=False,
        )
        terrain_from_curve = terrain.matrix_world.inverted() @ curve.matrix_world
        vertex_degrees: dict[int, int] = {}
        for edge in curve_mesh.edges:
            for vertex_index in edge.vertices:
                vertex_degrees[vertex_index] = vertex_degrees.get(vertex_index, 0) + 1
        intersections: list[tuple[Vector, Vector]] = []
        for edge in curve_mesh.edges:
            start = terrain_from_curve @ curve_mesh.vertices[edge.vertices[0]].co
            end = terrain_from_curve @ curve_mesh.vertices[edge.vertices[1]].co
            delta = end - start
            length = delta.length
            if length <= 1e-6:
                continue
            direction = delta / length
            travelled = 1e-5
            while travelled < length - 1e-5:
                hit = bvh.ray_cast(
                    start + direction * travelled,
                    direction,
                    length - travelled,
                )
                if hit[0] is None:
                    break
                location = hit[0]
                remaining_distance = length - travelled
                # A curve can finish while still underground, with its final
                # point touching the terrain mesh. That is not a tunnel
                # portal: there is no path outside the terrain beyond it.
                # Keep crossings at internal tessellation vertices, but ignore
                # a hit at the actual end of the path.
                if (
                    hit[3] >= remaining_distance - 1e-4
                    and vertex_degrees[edge.vertices[1]] == 1
                ):
                    break
                if not any((location - previous[0]).length < 1e-3 for previous in intersections):
                    intersections.append((location, direction))
                travelled += hit[3] + 1e-4
    finally:
        terrain_eval.to_mesh_clear()
        curve_eval.to_mesh_clear()

    # A terrain can contain stacked surfaces, internal faces, or touching
    # triangles along a segment. The exterior tunnel portals are the first
    # and last intersections encountered while traversing the path.
    if len(intersections) > 2:
        intersections = [intersections[0], intersections[-1]]

    if entry.log_thickness <= 0:
        raise ValueError("MineShaftEntry.log_thickness must be greater than zero.")
    thickness = entry.log_thickness
    local_up = Vector((0.0, 0.0, 1.0))
    terrain_linear = terrain.matrix_world.to_3x3()

    def surface_point(point: Vector, direction: Vector) -> Vector:
        hits = []
        for ray_direction in (direction, -direction):
            hit = bvh.ray_cast(point + ray_direction * 1e-4, ray_direction, 10000.0)
            if hit[0] is not None:
                hits.append((hit[3], hit[0]))
        return min(hits, key=lambda value: value[0])[1] if hits else point

    for index, (location, local_tangent) in enumerate(intersections):
        # Match the cutter's "Z Up" orientation: project local Z into the
        # plane perpendicular to the tunnel path before deriving its side.
        # This must happen in terrain-local space, where Geometry Nodes
        # evaluates both the Object Info curve and Set Curve Normal node.
        up_local = local_up - local_tangent * local_tangent.dot(local_up)
        if up_local.length < 1e-5:
            continue
        up_local.normalize()
        right_local = local_tangent.cross(up_local)

        corners = [
            surface_point(location + right_local * x + up_local * z, local_tangent)
            for x, z in (
                (-tunnel_width / 2, tunnel_height / 2),
                (-tunnel_width / 2, -tunnel_height / 2),
                (tunnel_width / 2, tunnel_height / 2),
                (tunnel_width / 2, -tunnel_height / 2),
            )
        ]
        top_left, bottom_left, top_right, bottom_right = [
            terrain.matrix_world @ corner for corner in corners
        ]
        top_edge = top_right - top_left
        left_edge = bottom_left - top_left
        portal_normal = top_edge.cross(left_edge)
        if portal_normal.length < 1e-5:
            continue
        portal_normal.normalize()

        def add_post(name: str, top: Vector, bottom: Vector) -> None:
            up = top - bottom
            if up.length < 1e-5:
                return
            up.normalize()
            right = portal_normal.cross(up)
            if right.length < 1e-5:
                return
            right.normalize()
            _add_cube_log(
                collection,
                name=name,
                center=(top + bottom) / 2,
                right=right,
                forward=portal_normal,
                up=up,
                dimensions=(thickness, thickness, (top - bottom).length + thickness),
                material=material,
            )

        add_post(f"MineShaft_{index:02d}_Left", top_left, bottom_left)
        add_post(f"MineShaft_{index:02d}_Right", top_right, bottom_right)
        right = top_edge.normalized()
        up = portal_normal.cross(right).normalized()
        _add_cube_log(
            collection,
            name=f"MineShaft_{index:02d}_Lintel",
            center=(top_left + top_right) / 2,
            right=right,
            forward=portal_normal,
            up=up,
            dimensions=(top_edge.length + thickness, thickness, thickness),
            material=material,
        )


def _add_mineshaft_entry_nodes(
    ng: bpy.types.NodeTree,
    *,
    path_socket: bpy.types.NodeSocket,
    terrain_socket: bpy.types.NodeSocket,
    width: float,
    height: float,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    """Build two upright logs and a lintel at each end of a rectangular path.

    The local Z axis follows the tunnel direction and local X is aligned to
    world up. This keeps the posts vertical even when the entry path reverses.
    """
    nodes, links = ng.nodes, ng.links
    log_thickness = min(max(min(width, height) * 0.12, 0.12), 0.3)

    endpoints = nodes.new("GeometryNodeCurveToPoints")
    # Sample the entire path. A portal is where one of these short, tangent
    # rays crosses the terrain surface; this also handles curves which bend
    # substantially between their control endpoint and the tunnel entrance.
    endpoints.mode = "COUNT"
    endpoints.inputs["Count"].default_value = 128
    links.new(path_socket, endpoints.inputs["Curve"])

    position = nodes.new("GeometryNodeInputPosition")
    raycast = nodes.new("GeometryNodeRaycast")
    raycast.data_type = "FLOAT"
    # The near-hit test below, rather than ray length, limits candidates to
    # actual surface crossings. This constant remains valid after the curve
    # has been converted into sampled points.
    raycast.inputs["Ray Length"].default_value = 10000.0
    links.new(terrain_socket, raycast.inputs["Target Geometry"])
    links.new(position.outputs["Position"], raycast.inputs["Source Position"])
    links.new(endpoints.outputs["Tangent"], raycast.inputs["Ray Direction"])

    portal_points = nodes.new("GeometryNodeSetPosition")
    links.new(endpoints.outputs["Points"], portal_points.inputs["Geometry"])
    links.new(raycast.outputs["Hit Position"], portal_points.inputs["Position"])
    near_surface = nodes.new("FunctionNodeCompare")
    near_surface.data_type = "FLOAT"
    near_surface.operation = "LESS_THAN"
    near_surface.inputs[1].default_value = max(width, height)
    links.new(raycast.outputs["Hit Distance"], near_surface.inputs[0])
    surface_alignment = nodes.new("ShaderNodeVectorMath")
    surface_alignment.operation = "DOT_PRODUCT"
    links.new(raycast.outputs["Hit Normal"], surface_alignment.inputs[0])
    links.new(endpoints.outputs["Tangent"], surface_alignment.inputs[1])
    absolute_alignment = nodes.new("ShaderNodeMath")
    absolute_alignment.operation = "ABSOLUTE"
    links.new(surface_alignment.outputs["Value"], absolute_alignment.inputs[0])
    faces_tunnel = nodes.new("FunctionNodeCompare")
    faces_tunnel.data_type = "FLOAT"
    faces_tunnel.operation = "GREATER_THAN"
    faces_tunnel.inputs[1].default_value = 0.5
    links.new(absolute_alignment.outputs["Value"], faces_tunnel.inputs[0])
    is_portal = nodes.new("FunctionNodeBooleanMath")
    is_portal.operation = "AND"
    links.new(raycast.outputs["Is Hit"], is_portal.inputs[0])
    links.new(near_surface.outputs["Result"], is_portal.inputs[1])
    faces_portal = nodes.new("FunctionNodeBooleanMath")
    faces_portal.operation = "AND"
    links.new(is_portal.outputs["Boolean"], faces_portal.inputs[0])
    links.new(faces_tunnel.outputs["Result"], faces_portal.inputs[1])
    non_portal = nodes.new("FunctionNodeBooleanMath")
    non_portal.operation = "NOT"
    links.new(faces_portal.outputs["Boolean"], non_portal.inputs[0])
    delete_non_portals = nodes.new("GeometryNodeDeleteGeometry")
    delete_non_portals.domain = "POINT"
    links.new(portal_points.outputs["Geometry"], delete_non_portals.inputs["Geometry"])
    links.new(non_portal.outputs["Boolean"], delete_non_portals.inputs["Selection"])
    merge_portals = nodes.new("GeometryNodeMergeByDistance")
    merge_portals.inputs["Distance"].default_value = max(width, height) * 2.0
    links.new(delete_non_portals.outputs["Geometry"], merge_portals.inputs["Geometry"])

    # Align Z with the tunnel direction, then lock X to world up.  The latter
    # makes the decoration read as a timber doorway rather than rolling with
    # the curve's tilt.
    align_tangent = nodes.new("FunctionNodeAlignEulerToVector")
    align_tangent.axis = "Z"
    links.new(endpoints.outputs["Tangent"], align_tangent.inputs["Vector"])
    align_up = nodes.new("FunctionNodeAlignEulerToVector")
    align_up.axis = "X"
    align_up.pivot_axis = "Z"
    align_up.inputs["Vector"].default_value = (0.0, 0.0, 1.0)
    links.new(align_tangent.outputs["Rotation"], align_up.inputs["Rotation"])

    def log(size: tuple[float, float, float], translation: tuple[float, float, float]):
        cube = nodes.new("GeometryNodeMeshCube")
        cube.inputs["Size"].default_value = size
        transform = nodes.new("GeometryNodeTransform")
        transform.inputs["Translation"].default_value = translation
        links.new(cube.outputs["Mesh"], transform.inputs["Geometry"])
        return transform

    post_height = height + log_thickness
    side_offset = width / 2 + log_thickness / 2
    left_post = log((post_height, log_thickness, log_thickness), (0.0, -side_offset, 0.0))
    right_post = log((post_height, log_thickness, log_thickness), (0.0, side_offset, 0.0))
    lintel = log(
        (log_thickness, width + 2 * log_thickness, log_thickness),
        (height / 2 + log_thickness / 2, 0.0, 0.0),
    )

    join_logs = nodes.new("GeometryNodeJoinGeometry")
    for node in (left_post, right_post, lintel):
        links.new(node.outputs["Geometry"], join_logs.inputs["Geometry"])

    instances = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(merge_portals.outputs["Geometry"], instances.inputs["Points"])
    links.new(join_logs.outputs["Geometry"], instances.inputs["Instance"])
    links.new(align_up.outputs["Rotation"], instances.inputs["Rotation"])

    realize = nodes.new("GeometryNodeRealizeInstances")
    links.new(instances.outputs["Instances"], realize.inputs["Geometry"])
    set_material = nodes.new("GeometryNodeSetMaterial")
    set_material.inputs["Material"].default_value = _get_mineshaft_log_material()
    links.new(realize.outputs["Geometry"], set_material.inputs["Geometry"])
    return set_material.outputs["Geometry"], [
        endpoints,
        position,
        raycast,
        portal_points,
        near_surface,
        surface_alignment,
        absolute_alignment,
        faces_tunnel,
        is_portal,
        faces_portal,
        non_portal,
        delete_non_portals,
        merge_portals,
        align_tangent,
        align_up,
        left_post,
        right_post,
        lintel,
        join_logs,
        instances,
        realize,
        set_material,
    ]


def _move_modifier_before(
    obj: bpy.types.Object,
    modifier_name: str,
    before_modifier_name: str,
) -> None:
    from_index = obj.modifiers.find(modifier_name)
    to_index = obj.modifiers.find(before_modifier_name)
    if from_index == -1 or to_index == -1 or from_index <= to_index:
        return
    try:
        obj.modifiers.move(from_index, to_index)
    except Exception:
        pass


def _ensure_cave_object(cave_object_name: str) -> bpy.types.Object:
    cave = bpy.data.objects.get(cave_object_name)
    if cave is None:
        raise RuntimeError(f"Tunnel references missing cave object '{cave_object_name}'.")
    if cave.type != "MESH":
        raise RuntimeError(
            f"Tunnel cave object '{cave_object_name}' must be MESH, got: {cave.type}"
        )
    return cave


def _configure_exact_boolean(
    node: bpy.types.Node,
    operation: str,
    *,
    self_intersection: bool = True,
) -> None:
    try:
        node.operation = operation
    except Exception:
        pass
    try:
        node.solver = "EXACT"
    except Exception:
        pass
    if hasattr(node, "self_intersection"):
        try:
            node.self_intersection = self_intersection
        except Exception:
            pass


def create_tunnel_entrypoint_modifier(config: "TerrainConfig"):
    tunnel = config.tunnel
    if tunnel is None:
        return None

    obj = get_terrain_object(config.object_name)
    curves = [ensure_curve_object(name) for name in tunnel.curve_object_names]
    caves = [_ensure_cave_object(name) for name in tunnel.cave_object_names]
    for cave in caves:
        cave.hide_render = True
        cave.hide_set(True)

    mod_name = config.tunnel_entrypoint_modifier_name
    previous_modifier = obj.modifiers.get(mod_name)
    if previous_modifier is not None:
        previous_modifier.show_viewport = False
        bpy.context.view_layer.update()
    remove_node_group(mod_name)
    ng = bpy.data.node_groups.new(mod_name, "GeometryNodeTree")

    for it in list(ng.interface.items_tree):
        ng.interface.remove(it)
    ng.nodes.clear()

    ng.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    ng.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")

    cutter_group = create_tunnel_portal_cutter_group(
        shape=tunnel.shape,
        keep_floor_level=tunnel.keep_floor_level,
    )

    path_geometry, source_nodes = add_object_info_nodes(
        ng,
        objects=curves,
        transform_space="RELATIVE",
        as_instance=False,
        frame_label="Tunnel Paths",
    )

    entry = tunnel.entry_decoration
    if isinstance(entry, MineShaftEntry) and tunnel.shape != TunnelShape.RECTANGLE:
        raise ValueError("MineShaftEntry decoration requires a rectangular tunnel.")

    portal_cutter = nodes.new("GeometryNodeGroup")
    portal_cutter.node_tree = cutter_group
    portal_cutter.label = "Tunnel Portal Cutter"
    links.new(path_geometry, portal_cutter.inputs["Path Geometry"])

    dimensions = (
        {"Radius": tunnel.radius}
        if tunnel.shape == TunnelShape.CIRCLE
        else {"Width": tunnel.width, "Height": tunnel.height}
    )
    dimension_nodes = []
    for name, size in dimensions.items():
        value = nodes.new("ShaderNodeValue")
        value.label = f"Tunnel {name}"
        value.outputs[0].default_value = float(size)

        clearance = nodes.new("ShaderNodeMath")
        clearance.operation = "MULTIPLY"
        clearance.inputs[1].default_value = 1.02
        links.new(value.outputs[0], clearance.inputs[0])
        links.new(clearance.outputs["Value"], portal_cutter.inputs[name])
        dimension_nodes.extend((value, clearance))

    # Import lazily to avoid a configuration <-> tunnel module import cycle.
    from terrain_layers.shader.create_shader import create_ground_material_shader

    tunnel_material = create_ground_material_shader(
        tunnel.ground_material,
        f"{config.shader_name}_Tunnel",
        tunnel.texture_scale,
    )
    material_cutter = nodes.new("GeometryNodeSetMaterial")
    material_cutter.label = f"Tunnel Material: {tunnel.ground_material.material_name}"
    material_cutter.inputs["Material"].default_value = tunnel_material
    links.new(portal_cutter.outputs["Cutter Mesh"], material_cutter.inputs["Geometry"])

    # Preserve smooth normals on the swept tunnel while leaving cave faces
    # sharp. Box-projected textures use these normals to choose projections.
    smooth_tunnel = nodes.new("GeometryNodeSetShadeSmooth")
    smooth_tunnel.label = "Smooth Tunnel Cut"
    smooth_tunnel.inputs["Shade Smooth"].default_value = True
    links.new(material_cutter.outputs["Geometry"], smooth_tunnel.inputs["Mesh"])

    tunnel_boolean = nodes.new("GeometryNodeMeshBoolean")
    tunnel_boolean.label = "Cut Tunnel"
    _configure_exact_boolean(tunnel_boolean, "DIFFERENCE")
    links.new(gin.outputs["Geometry"], tunnel_boolean.inputs["Mesh 1"])
    links.new(smooth_tunnel.outputs["Mesh"], tunnel_boolean.inputs["Mesh 2"])

    cut_geometry = tunnel_boolean.outputs["Mesh"]
    cave_nodes = []
    if caves:
        cave_geometry, cave_source_nodes = add_object_info_nodes(
            ng,
            objects=caves,
            transform_space="RELATIVE",
            as_instance=False,
            # A fused multi-cave cut feeds every source directly to the
            # Boolean UNION, so creating a Join Geometry here would be dead
            # graph state.
            join_multiple=not (tunnel.fuse_caves and len(caves) > 1),
        )
        if cave_geometry is None and not (tunnel.fuse_caves and len(caves) > 1):
            raise RuntimeError("Expected joined cave geometry.")
        fused_cave_geometry = cave_geometry
        cave_union_nodes = []
        if tunnel.fuse_caves and len(caves) > 1:
            cave_union = nodes.new("GeometryNodeMeshBoolean")
            cave_union.label = "Fuse Overlapping Caves"
            _configure_exact_boolean(cave_union, "UNION", self_intersection=False)
            # Feed each cave as its own UNION operand.  Joining them first
            # leaves their overlapping interior surfaces intact.
            for source_node in cave_source_nodes:
                if source_node.bl_idname == "GeometryNodeObjectInfo":
                    links.new(source_node.outputs["Geometry"], cave_union.inputs[1])
            fused_cave_geometry = cave_union.outputs["Mesh"]
            cave_union_nodes.append(cave_union)

        cave_material = nodes.new("GeometryNodeSetMaterial")
        cave_material.label = f"Cave Material: {tunnel.ground_material.material_name}"
        cave_material.inputs["Material"].default_value = tunnel_material
        links.new(fused_cave_geometry, cave_material.inputs["Geometry"])

        flat_cave = nodes.new("GeometryNodeSetShadeSmooth")
        flat_cave.label = "Keep Cave Faces Flat"
        flat_cave.inputs["Shade Smooth"].default_value = False
        links.new(cave_material.outputs["Geometry"], flat_cave.inputs["Mesh"])

        # Sequential subtraction is set-equivalent to subtracting a union of
        # the tunnel and caves, while remaining reliable when cutters overlap.
        cave_boolean = nodes.new("GeometryNodeMeshBoolean")
        cave_boolean.label = "Cut Caves"
        _configure_exact_boolean(cave_boolean, "DIFFERENCE")
        links.new(cut_geometry, cave_boolean.inputs["Mesh 1"])
        links.new(flat_cave.outputs["Mesh"], cave_boolean.inputs["Mesh 2"])
        cut_geometry = cave_boolean.outputs["Mesh"]
        cave_nodes = [
            *cave_source_nodes,
            *cave_union_nodes,
            cave_material,
            flat_cave,
            cave_boolean,
        ]

    if isinstance(entry, MineShaftEntry):
        entry_collection = _clear_mineshaft_entries()
        for curve in curves:
            _create_mineshaft_entry_objects(
                obj,
                curve,
                tunnel.width,
                tunnel.height,
                entry,
                entry_collection,
            )
    links.new(cut_geometry, gout.inputs["Geometry"])

    entrypoint_nodes = [
        *dimension_nodes,
        portal_cutter,
        material_cutter,
        smooth_tunnel,
        *cave_nodes,
        tunnel_boolean,
    ]
    frame_nodes(ng, "Tunnel Entrypoints MVP", entrypoint_nodes)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    mod.show_viewport = True
    mod.show_render = True
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
