from __future__ import annotations

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from terrain_layers.shader.material_types import PBRMaterialSource
from terrain_layers.tunnels.tunnel_types import MineShaftEntry


MINE_SHAFT_LOG_MATERIAL_NAME = "TerrainTunnelMineShaftLog"
MINE_SHAFT_ENTRIES_COLLECTION_NAME = "TerrainTunnelMineShaftEntries"
LEGACY_MINESHAFT_ENTRIES_COLLECTION_NAME = "TerrainTunnelMineshaftEntries"


def get_mineshaft_log_material(
    ground_material: PBRMaterialSource | None = None,
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


def clear_mineshaft_entries() -> bpy.types.Collection:
    legacy_collection = bpy.data.collections.get(
        LEGACY_MINESHAFT_ENTRIES_COLLECTION_NAME
    )
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
    faces = [
        (0, 1, 3, 2),
        (4, 6, 7, 5),
        (0, 4, 5, 1),
        (2, 3, 7, 6),
        (0, 2, 6, 4),
        (1, 5, 7, 3),
    ]
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    log = bpy.data.objects.new(name, mesh)
    collection.objects.link(log)
    orientation = Matrix((right, forward, up)).transposed().to_4x4()
    # Bake dimensions into the mesh instead of object scale. The PBR material
    # samples Object coordinates, so applied dimensions preserve a consistent
    # real-world texture scale across the thin and long sides of each beam.
    log.matrix_world = Matrix.Translation(center) @ orientation


def create_mineshaft_entry_objects(
    terrain: bpy.types.Object,
    curve: bpy.types.Object,
    tunnel_width: float,
    tunnel_height: float,
    entry: MineShaftEntry,
    collection: bpy.types.Collection,
) -> None:
    """Create three-log frames at exact curve-segment/terrain intersections."""
    material = get_mineshaft_log_material(entry.ground_material)
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
                    start + direction * travelled, direction, length - travelled
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
                if not any(
                    (location - previous[0]).length < 1e-3 for previous in intersections
                ):
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
