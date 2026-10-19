import bpy


TEMPORARY_SOLIDIFY_MATERIAL_NAME = "TerrainTemporarySolidify"


def get_temporary_solidify_material() -> bpy.types.Material:
    material = bpy.data.materials.get(TEMPORARY_SOLIDIFY_MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(TEMPORARY_SOLIDIFY_MATERIAL_NAME)
    return material


def solidify_terrain(
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
        bounds, minimum, maximum, height, extrusion_depth, downward_depth,
        extrusion_offset, extrude, position, position_xyz, bottom_vertices,
        bottom_z, bottom_position, flatten_bottom, normal, normal_xyz,
        upward_faces, flip_bottom, mark_temporary, join, merge,
    ]


def remove_temporary_solidify_geometry(
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
