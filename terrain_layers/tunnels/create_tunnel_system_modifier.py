from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from terrain_layers.tunnels.create_tunnel_path_cutter import (
    create_tunnel_path_cutter_group,
)
from terrain_layers.tunnels.tunnel_types import (
    MineShaftEntry,
    TunnelEntryDecoration,
    TunnelShape,
    TUNNEL_INTERIOR_MATERIAL_MARKER,
)
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
_PREVIOUS_SYSTEM_MODIFIER_NAME = "Terrain_Tunnel_Entrypoints"
_TEMPORARY_SOLIDIFY_MATERIAL_NAME = "TerrainTemporarySolidify"


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


def _get_temporary_solidify_material() -> bpy.types.Material:
    material = bpy.data.materials.get(_TEMPORARY_SOLIDIFY_MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(_TEMPORARY_SOLIDIFY_MATERIAL_NAME)
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


def _configure_boolean(
    node: bpy.types.Node,
    operation: str,
    *,
    self_intersection: bool = True,
    solver: str = "EXACT",
    hole_tolerant: bool = False,
) -> None:
    try:
        node.operation = operation
    except Exception:
        pass
    try:
        node.solver = solver
    except Exception:
        pass
    if hasattr(node, "self_intersection"):
        try:
            node.self_intersection = self_intersection
        except Exception:
            pass
    hole_tolerant_input = node.inputs.get("Hole Tolerant")
    if hole_tolerant_input is not None:
        hole_tolerant_input.default_value = hole_tolerant


@dataclass(frozen=True, slots=True)
class _ResolvedPath:
    config: object
    object: bpy.types.Object
    shape: TunnelShape
    radius: float
    width: float
    height: float
    keep_floor_level: bool
    ground_material: GroundMaterial
    texture_scale: float
    entry_decoration: TunnelEntryDecoration | None

    @property
    def batch_key(self) -> tuple[object, ...]:
        return (
            self.shape,
            self.radius if self.shape == TunnelShape.CIRCLE else None,
            self.width if self.shape == TunnelShape.RECTANGLE else None,
            self.height if self.shape == TunnelShape.RECTANGLE else None,
            self.keep_floor_level if self.shape == TunnelShape.RECTANGLE else None,
            self.ground_material,
            self.texture_scale,
        )


@dataclass(frozen=True, slots=True)
class _ResolvedCave:
    config: object
    object: bpy.types.Object
    ground_material: GroundMaterial
    texture_scale: float
    fuse_group: str | None


def _resolve_tunnel_system(
    config: "TerrainConfig",
) -> tuple[list[_ResolvedPath], list[_ResolvedCave]]:
    system = config.tunnel_system
    if system is None:
        return [], []
    if system.solidify_depth <= 0:
        raise ValueError("Tunnel system solidify_depth must be positive.")

    seen_names: set[str] = set()

    def unique(name: str) -> None:
        if name in seen_names:
            raise ValueError(f"Tunnel system references object '{name}' more than once.")
        seen_names.add(name)

    paths: list[_ResolvedPath] = []
    for path in system.paths:
        unique(path.curve_object_name)
        shape = TunnelShape(path.shape if path.shape is not None else system.shape)
        radius = float(path.radius if path.radius is not None else system.radius)
        width = float(path.width if path.width is not None else system.width)
        height = float(path.height if path.height is not None else system.height)
        if (shape == TunnelShape.CIRCLE and radius <= 0) or (
            shape == TunnelShape.RECTANGLE and (width <= 0 or height <= 0)
        ):
            raise ValueError(
                f"Tunnel path '{path.curve_object_name}' has non-positive resolved dimensions."
            )
        decoration = (
            system.entry_decoration
            if path.entry_decoration is None
            else path.entry_decoration
        )
        if decoration is False:
            decoration = None
        elif not isinstance(decoration, (TunnelEntryDecoration, type(None))):
            raise ValueError(
                f"Tunnel path '{path.curve_object_name}' has an invalid entry decoration."
            )
        if isinstance(decoration, MineShaftEntry) and shape != TunnelShape.RECTANGLE:
            raise ValueError(
                "MineShaftEntry decoration requires a rectangular tunnel "
                f"(path '{path.curve_object_name}')."
            )
        paths.append(
            _ResolvedPath(
                path,
                ensure_curve_object(path.curve_object_name),
                shape,
                radius,
                width,
                height,
                bool(
                    path.keep_floor_level
                    if path.keep_floor_level is not None
                    else system.keep_floor_level
                ),
                path.ground_material or system.ground_material,
                float(
                    path.texture_scale
                    if path.texture_scale is not None
                    else system.texture_scale
                ),
                decoration,
            )
        )

    caves: list[_ResolvedCave] = []
    group_settings: dict[str, tuple[GroundMaterial, float]] = {}
    for cave in system.caves:
        unique(cave.cave_object_name)
        if cave.fuse_group is not None and not cave.fuse_group:
            raise ValueError("Tunnel cave fuse_group must be a non-empty name or None.")
        resolved = _ResolvedCave(
            cave,
            _ensure_cave_object(cave.cave_object_name),
            cave.ground_material or system.ground_material,
            float(
                cave.texture_scale
                if cave.texture_scale is not None
                else system.texture_scale
            ),
            cave.fuse_group,
        )
        if resolved.fuse_group is not None:
            settings = (resolved.ground_material, resolved.texture_scale)
            previous = group_settings.setdefault(resolved.fuse_group, settings)
            if previous != settings:
                raise ValueError(
                    f"Tunnel cave fuse group '{resolved.fuse_group}' must resolve to one material and texture scale."
                )
        caves.append(resolved)
    return paths, caves


def _solidify_terrain(
    ng: bpy.types.GeometryNodeTree,
    geometry: bpy.types.NodeSocket,
    depth: float,
    temporary_material: bpy.types.Material,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    """Close the terrain surface with a volume extending below it.

    Mesh booleans need a closed first operand.  A terrain is normally only a
    surface, so cutters that fall below its lowest point would otherwise have
    no volume to subtract from.
    """
    # Extrude Mesh replaces the selected top faces with the offset faces. Keep
    # the input terrain separately, then join and weld it to the generated
    # bottom and perimeter so the visible terrain never moves.
    bounds = ng.nodes.new("GeometryNodeBoundBox")
    bounds.label = "Terrain Bounds"
    ng.links.new(geometry, bounds.inputs["Geometry"])
    minimum = ng.nodes.new("ShaderNodeSeparateXYZ")
    minimum.label = "Terrain Minimum"
    ng.links.new(bounds.outputs["Min"], minimum.inputs["Vector"])
    maximum = ng.nodes.new("ShaderNodeSeparateXYZ")
    maximum.label = "Terrain Maximum"
    ng.links.new(bounds.outputs["Max"], maximum.inputs["Vector"])
    height = ng.nodes.new("ShaderNodeMath")
    height.label = "Terrain Height"
    height.operation = "SUBTRACT"
    ng.links.new(maximum.outputs["Z"], height.inputs[0])
    ng.links.new(minimum.outputs["Z"], height.inputs[1])
    extrusion_depth = ng.nodes.new("ShaderNodeMath")
    extrusion_depth.label = "Solidify Extrusion Depth"
    extrusion_depth.operation = "ADD"
    extrusion_depth.inputs[1].default_value = depth
    ng.links.new(height.outputs["Value"], extrusion_depth.inputs[0])
    downward_depth = ng.nodes.new("ShaderNodeMath")
    downward_depth.label = "Downward Extrusion"
    downward_depth.operation = "MULTIPLY"
    downward_depth.inputs[1].default_value = -1.0
    ng.links.new(extrusion_depth.outputs["Value"], downward_depth.inputs[0])
    extrusion_offset = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new(downward_depth.outputs["Value"], extrusion_offset.inputs["Z"])

    extrude = ng.nodes.new("GeometryNodeExtrudeMesh")
    extrude.label = "Solidify Terrain"
    extrude.inputs["Selection"].default_value = True
    extrude.inputs["Individual"].default_value = False
    ng.links.new(geometry, extrude.inputs["Mesh"])
    ng.links.new(extrusion_offset.outputs["Vector"], extrude.inputs["Offset"])

    # Only the vertices generated at the bottom are below the original
    # terrain's minimum Z. Put those on a single plane to avoid a serrated
    # lower rim without altering the original terrain or the side-wall tops.
    position = ng.nodes.new("GeometryNodeInputPosition")
    position_xyz = ng.nodes.new("ShaderNodeSeparateXYZ")
    ng.links.new(position.outputs["Position"], position_xyz.inputs["Vector"])
    bottom_vertices = ng.nodes.new("FunctionNodeCompare")
    bottom_vertices.label = "Generated Bottom Vertices"
    bottom_vertices.data_type = "FLOAT"
    bottom_vertices.operation = "LESS_THAN"
    ng.links.new(position_xyz.outputs["Z"], bottom_vertices.inputs[0])
    ng.links.new(minimum.outputs["Z"], bottom_vertices.inputs[1])
    bottom_z = ng.nodes.new("ShaderNodeMath")
    bottom_z.label = "Terrain Bottom Z"
    bottom_z.operation = "SUBTRACT"
    bottom_z.inputs[1].default_value = depth
    ng.links.new(minimum.outputs["Z"], bottom_z.inputs[0])
    bottom_position = ng.nodes.new("ShaderNodeCombineXYZ")
    bottom_position.label = "Flat Terrain Bottom"
    ng.links.new(position_xyz.outputs["X"], bottom_position.inputs["X"])
    ng.links.new(position_xyz.outputs["Y"], bottom_position.inputs["Y"])
    ng.links.new(bottom_z.outputs["Value"], bottom_position.inputs["Z"])
    flatten_bottom = ng.nodes.new("GeometryNodeSetPosition")
    flatten_bottom.label = "Flatten Generated Bottom"
    ng.links.new(extrude.outputs["Mesh"], flatten_bottom.inputs["Geometry"])
    ng.links.new(bottom_vertices.outputs["Result"], flatten_bottom.inputs["Selection"])
    ng.links.new(bottom_position.outputs["Vector"], flatten_bottom.inputs["Position"])

    # The downward extrusion retains the source face winding, so its bottom
    # initially points up. Flip only horizontal, upward-facing faces: the
    # bottom points down afterwards while the perimeter normals stay outward.
    normal = ng.nodes.new("GeometryNodeInputNormal")
    normal_xyz = ng.nodes.new("ShaderNodeSeparateXYZ")
    ng.links.new(normal.outputs["Normal"], normal_xyz.inputs["Vector"])
    upward_faces = ng.nodes.new("FunctionNodeCompare")
    upward_faces.label = "Generated Bottom Faces"
    upward_faces.data_type = "FLOAT"
    upward_faces.operation = "GREATER_THAN"
    upward_faces.inputs[1].default_value = 0.5
    ng.links.new(normal_xyz.outputs["Z"], upward_faces.inputs[0])
    flip_bottom = ng.nodes.new("GeometryNodeFlipFaces")
    flip_bottom.label = "Orient Terrain Bottom Outward"
    ng.links.new(flatten_bottom.outputs["Geometry"], flip_bottom.inputs["Mesh"])
    ng.links.new(upward_faces.outputs["Result"], flip_bottom.inputs["Selection"])

    mark_temporary = ng.nodes.new("GeometryNodeSetMaterial")
    mark_temporary.label = "Mark Temporary Solidify"
    mark_temporary.inputs["Material"].default_value = temporary_material
    ng.links.new(flip_bottom.outputs["Mesh"], mark_temporary.inputs["Geometry"])

    join = ng.nodes.new("GeometryNodeJoinGeometry")
    join.label = "Join Terrain and Temporary Solidify"
    ng.links.new(geometry, join.inputs["Geometry"])
    ng.links.new(mark_temporary.outputs["Geometry"], join.inputs["Geometry"])
    merge = ng.nodes.new("GeometryNodeMergeByDistance")
    merge.label = "Weld Terrain Solidify"
    merge.inputs["Distance"].default_value = 0.0001
    ng.links.new(join.outputs["Geometry"], merge.inputs["Geometry"])
    return merge.outputs["Geometry"], [
        bounds,
        minimum,
        maximum,
        height,
        extrusion_depth,
        downward_depth,
        extrusion_offset,
        extrude,
        position,
        position_xyz,
        bottom_vertices,
        bottom_z,
        bottom_position,
        flatten_bottom,
        normal,
        normal_xyz,
        upward_faces,
        flip_bottom,
        mark_temporary,
        join,
        merge,
    ]


def _remove_temporary_solidify_geometry(
    ng: bpy.types.GeometryNodeTree,
    geometry: bpy.types.NodeSocket,
    temporary_material: bpy.types.Material,
) -> tuple[bpy.types.NodeSocket, list[bpy.types.Node]]:
    """Remove only faces still carrying the temporary shell material."""
    selection = ng.nodes.new("GeometryNodeMaterialSelection")
    selection.label = "Temporary Solidify Faces"
    selection.inputs["Material"].default_value = temporary_material
    delete = ng.nodes.new("GeometryNodeDeleteGeometry")
    delete.label = "Remove Temporary Terrain Bottom and Sides"
    delete.domain = "FACE"
    ng.links.new(geometry, delete.inputs["Geometry"])
    ng.links.new(selection.outputs["Selection"], delete.inputs["Selection"])
    return delete.outputs["Geometry"], [selection, delete]


def _path_batches(paths: list[_ResolvedPath]) -> list[list[_ResolvedPath]]:
    batches: list[list[_ResolvedPath]] = []
    for path in paths:
        if batches and batches[-1][0].batch_key == path.batch_key:
            batches[-1].append(path)
        else:
            batches.append([path])
    return batches


def create_tunnel_system_modifier(config: "TerrainConfig"):
    if config.tunnel_system is None:
        return None
    paths, caves = _resolve_tunnel_system(config)
    if not paths and not caves:
        return None
    obj = get_terrain_object(config.object_name)
    for cave in caves:
        cave.object.hide_render = True
        cave.object.hide_set(True)

    mod_name = config.tunnel_system_modifier_name
    # The old generated modifier must not remain active alongside the renamed
    # system modifier when a scene is rebuilt after upgrading this package.
    if mod_name != _PREVIOUS_SYSTEM_MODIFIER_NAME:
        previous_system_modifier = obj.modifiers.get(_PREVIOUS_SYSTEM_MODIFIER_NAME)
        if previous_system_modifier is not None:
            obj.modifiers.remove(previous_system_modifier)
        remove_node_group(_PREVIOUS_SYSTEM_MODIFIER_NAME)
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

    # Import lazily to avoid a configuration <-> tunnel module import cycle.
    from terrain_layers.shader.create_shader import create_ground_material_shader
    material_cache: dict[tuple[GroundMaterial, float], bpy.types.Material] = {}
    def material_for(material: GroundMaterial, texture_scale: float) -> bpy.types.Material:
        key = (material, texture_scale)
        if key not in material_cache:
            material_cache[key] = create_ground_material_shader(
                material, f"{config.shader_name}_Tunnel_{len(material_cache) + 1}", texture_scale
            )
            material_cache[key][TUNNEL_INTERIOR_MATERIAL_MARKER] = True
        return material_cache[key]

    child_frames: list[bpy.types.Node] = []
    temporary_solidify_material = _get_temporary_solidify_material()
    cut_geometry, solidify_nodes = _solidify_terrain(
        ng,
        gin.outputs["Geometry"],
        config.tunnel_system.solidify_depth,
        temporary_solidify_material,
    )
    solidify_frame = frame_nodes(ng, "Solidify Terrain", solidify_nodes)
    if solidify_frame:
        child_frames.append(solidify_frame)
    cutters: list[bpy.types.NodeSocket] = []
    for batch in _path_batches(paths):
        first = batch[0]
        path_geometry, source_nodes = add_object_info_nodes(
            ng, objects=[path.object for path in batch], transform_space="RELATIVE", as_instance=False
        )
        cutter_group = create_tunnel_path_cutter_group(
            group_name=f"TerrainTunnelPathCutter_{len(child_frames) + 1}",
            shape=first.shape, keep_floor_level=first.keep_floor_level,
        )
        portal_cutter = nodes.new("GeometryNodeGroup")
        portal_cutter.node_tree = cutter_group
        portal_cutter.label = "Tunnel Path Cutter"
        links.new(path_geometry, portal_cutter.inputs["Path Geometry"])
        dimensions = {"Radius": first.radius} if first.shape == TunnelShape.CIRCLE else {"Width": first.width, "Height": first.height}
        batch_nodes = [*source_nodes]
        for name, size in dimensions.items():
            value, clearance = nodes.new("ShaderNodeValue"), nodes.new("ShaderNodeMath")
            value.label, value.outputs[0].default_value = f"Tunnel {name}", size
            clearance.operation, clearance.inputs[1].default_value = "MULTIPLY", 1.02
            links.new(value.outputs[0], clearance.inputs[0])
            links.new(clearance.outputs["Value"], portal_cutter.inputs[name])
            batch_nodes.extend((value, clearance))
        material_cutter = nodes.new("GeometryNodeSetMaterial")
        material_cutter.label = f"Tunnel Material: {first.ground_material.material_name}"
        material_cutter.inputs["Material"].default_value = material_for(first.ground_material, first.texture_scale)
        links.new(portal_cutter.outputs["Cutter Mesh"], material_cutter.inputs["Geometry"])
        smooth = nodes.new("GeometryNodeSetShadeSmooth")
        smooth.label, smooth.inputs["Shade Smooth"].default_value = "Smooth Tunnel Cut", True
        links.new(material_cutter.outputs["Geometry"], smooth.inputs["Mesh"])
        cutters.append(smooth.outputs["Mesh"])
        names = " + ".join(path.object.name for path in batch)
        frame = frame_nodes(ng, ("Path: " if len(batch) == 1 else "Paths: ") + names, [*batch_nodes, portal_cutter, material_cutter, smooth])
        if frame:
            child_frames.append(frame)

    # A named group is cut at its first declaration, preserving the declared
    # order relative to independent caves without duplicating group work.
    cave_units: list[tuple[str | None, list[_ResolvedCave]]] = []
    grouped: set[str] = set()
    for cave in caves:
        if cave.fuse_group is None:
            cave_units.append((None, [cave]))
        elif cave.fuse_group not in grouped:
            grouped.add(cave.fuse_group)
            cave_units.append((cave.fuse_group, [item for item in caves if item.fuse_group == cave.fuse_group]))
    for group_name, unit in cave_units:
        geometry, source_nodes = add_object_info_nodes(
            ng, objects=[cave.object for cave in unit], transform_space="RELATIVE", as_instance=False,
            join_multiple=not (group_name is not None and len(unit) > 1),
        )
        unit_nodes = [*source_nodes]
        if group_name is not None and len(unit) > 1:
            union = nodes.new("GeometryNodeMeshBoolean")
            union.label = "Fuse Overlapping Caves"
            _configure_boolean(union, "UNION", self_intersection=False)
            for source in source_nodes:
                if source.bl_idname == "GeometryNodeObjectInfo":
                    links.new(source.outputs["Geometry"], union.inputs[1])
            geometry = union.outputs["Mesh"]
            unit_nodes.append(union)
        material = nodes.new("GeometryNodeSetMaterial")
        material.label = f"Cave Material: {unit[0].ground_material.material_name}"
        material.inputs["Material"].default_value = material_for(unit[0].ground_material, unit[0].texture_scale)
        links.new(geometry, material.inputs["Geometry"])
        flat = nodes.new("GeometryNodeSetShadeSmooth")
        flat.label, flat.inputs["Shade Smooth"].default_value = "Keep Cave Faces Flat", False
        links.new(material.outputs["Geometry"], flat.inputs["Mesh"])
        cutters.append(flat.outputs["Mesh"])
        label = f"Caves: {group_name}" if group_name is not None else f"Cave: {unit[0].object.name}"
        frame = frame_nodes(ng, label, [*unit_nodes, material, flat])
        if frame:
            child_frames.append(frame)

    # Keep Mesh 1 closed until every cutter is applied. A tunnel that exits
    # the terrain otherwise makes every later boolean much more expensive.
    final_boolean = nodes.new("GeometryNodeMeshBoolean")
    final_boolean.label = "Cut Tunnel System"
    _configure_boolean(
        final_boolean,
        "DIFFERENCE",
        self_intersection=False,
        solver="FLOAT",
    )
    links.new(cut_geometry, final_boolean.inputs["Mesh 1"])
    for cutter in cutters:
        links.new(cutter, final_boolean.inputs["Mesh 2"])
    cut_geometry = final_boolean.outputs["Mesh"]
    final_frame = frame_nodes(ng, "Cut Tunnel System", [final_boolean])
    if final_frame:
        child_frames.append(final_frame)

    if any(isinstance(path.entry_decoration, MineShaftEntry) for path in paths):
        entry_collection = _clear_mineshaft_entries()
        for path in paths:
            if isinstance(path.entry_decoration, MineShaftEntry):
                _create_mineshaft_entry_objects(obj, path.object, path.width, path.height, path.entry_decoration, entry_collection)
    cut_geometry, cleanup_nodes = _remove_temporary_solidify_geometry(
        ng,
        cut_geometry,
        temporary_solidify_material,
    )
    cleanup_frame = frame_nodes(ng, "Remove Temporary Solidify", cleanup_nodes)
    if cleanup_frame:
        child_frames.append(cleanup_frame)
    links.new(cut_geometry, gout.inputs["Geometry"])
    frame_nodes(ng, "Tunnel System", child_frames)

    mod = ensure_geo_nodes_modifier(obj, mod_name)
    mod.node_group = ng
    mod.name = mod_name
    mod.show_viewport = True
    mod.show_render = True
    _move_modifier_before(obj, mod_name, config.geometry_modifier_name)
    _move_modifier_before(obj, mod_name, config.scatter_modifier_name)

    arrange_nodes(ng)
    return ng
