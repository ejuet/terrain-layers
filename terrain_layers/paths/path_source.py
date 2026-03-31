from __future__ import annotations

import bpy

from terrain_layers.utility.type_helpers import Node
from terrain_layers.utility.geo_nodes import collect_collection_objects
from terrain_layers.utility.object_info_group import create_object_info_group


def ensure_curve_object(path_object_name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(path_object_name)
    if obj is None:
        raise RuntimeError(
            f"Road network references missing object '{path_object_name}'."
        )
    if obj.type != "CURVE":
        raise RuntimeError(
            f"Road network object '{path_object_name}' must be CURVE, got: {obj.type}"
        )
    return obj


def resolve_path_objects(
    *,
    path_object_name: str | None,
    path_collection_name: str | None,
) -> list[bpy.types.Object]:
    has_object = bool(path_object_name)
    has_collection = bool(path_collection_name)

    if has_object == has_collection:
        raise RuntimeError(
            "Road network path must specify exactly one of 'path_object_name' or "
            "'path_collection_name'."
        )

    if path_object_name:
        return [ensure_curve_object(path_object_name)]

    collection = bpy.data.collections.get(path_collection_name)
    if collection is None:
        raise RuntimeError(
            f"Road network references missing collection '{path_collection_name}'."
        )

    curve_objects = [
        obj for obj in collect_collection_objects(collection) if obj.type == "CURVE"
    ]
    if not curve_objects:
        raise RuntimeError(
            f"Road network collection '{path_collection_name}' does not contain any "
            "CURVE objects."
        )
    return curve_objects


def resolve_collection_geometry_objects(
    collection_name: str,
    *,
    object_types: tuple[str, ...] = ("MESH",),
) -> list[bpy.types.Object]:
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        raise RuntimeError(f"Missing collection '{collection_name}'.")

    geometry_objects = [
        obj
        for obj in collect_collection_objects(collection)
        if obj.type in object_types
    ]
    if not geometry_objects:
        type_list = ", ".join(object_types)
        raise RuntimeError(
            f"Collection '{collection_name}' does not contain any {type_list} objects."
        )
    return geometry_objects


def path_source_label(
    *,
    path_object_name: str | None,
    path_collection_name: str | None,
) -> str:
    if path_object_name:
        return path_object_name
    if path_collection_name:
        return path_collection_name
    return "Path"


def _safe_key(value: str | None) -> str:
    value = (value or "").strip()
    return (
        "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in value) or "Path"
    )


def _path_source_group_name(
    *,
    group_namespace: str,
    path_object_name: str | None,
    path_collection_name: str | None,
) -> str:
    if path_object_name:
        source_key = f"Object_{_safe_key(path_object_name)}"
    elif path_collection_name:
        source_key = f"Collection_{_safe_key(path_collection_name)}"
    else:
        source_key = "Path"
    return f"GN_{group_namespace}_{source_key}"


def create_path_source_group(
    *,
    group_namespace: str = "RoadPathSource",
    path_object_name: str | None,
    path_collection_name: str | None,
) -> bpy.types.NodeTree:
    label = path_source_label(
        path_object_name=path_object_name,
        path_collection_name=path_collection_name,
    )
    path_objects = resolve_path_objects(
        path_object_name=path_object_name,
        path_collection_name=path_collection_name,
    )
    return create_object_info_group(
        group_name=_path_source_group_name(
            group_namespace=group_namespace,
            path_object_name=path_object_name,
            path_collection_name=path_collection_name,
        ),
        objects=path_objects,
        transform_space="RELATIVE",
        as_instance=False,
        output_name="Geometry",
        frame_label=f"Objects: {label}",
    )


def add_path_source_nodes(
    nt: bpy.types.NodeTree,
    *,
    group_namespace: str = "RoadPathSource",
    path_object_name: str | None,
    path_collection_name: str | None,
) -> tuple[bpy.types.NodeSocket, list[Node]]:
    label = path_source_label(
        path_object_name=path_object_name,
        path_collection_name=path_collection_name,
    )
    group_node = nt.nodes.new("GeometryNodeGroup")
    group_node.node_tree = create_path_source_group(
        group_namespace=group_namespace,
        path_object_name=path_object_name,
        path_collection_name=path_collection_name,
    )
    group_node.label = f"Path Source: {label}"
    return group_node.outputs["Geometry"], [group_node]


def add_collection_geometry_source_nodes(
    nt: bpy.types.NodeTree,
    *,
    collection_name: str,
    group_namespace: str = "CollectionSource",
    object_types: tuple[str, ...] = ("MESH",),
    label_prefix: str = "Collection Source",
) -> tuple[bpy.types.NodeSocket, list[Node]]:
    objects = resolve_collection_geometry_objects(
        collection_name,
        object_types=object_types,
    )
    group_node = nt.nodes.new("GeometryNodeGroup")
    group_name = _path_source_group_name(
        group_namespace=group_namespace,
        path_object_name=None,
        path_collection_name=collection_name,
    )
    modifier_name = nt.name
    group_name += modifier_name
    """
    It is always wise to include the modifier name in the group name
    because if we do not, we can end up reusing the same group for multiple modifiers,
    which can lead to the created group not being correctly connected to the next nodes
    of the actual modifier (i think)
    so #TODO we might want a helper method for creating a node group that handles this
    It is maybe more likely that the create_object_info_group function overwrites the node group.
    Always recreating the ng in the function also fixes the issue
    """
    group_node.node_tree = create_object_info_group(
        group_name=group_name,
        objects=objects,
        transform_space="RELATIVE",
        as_instance=False,
        output_name="Geometry",
        frame_label=f"Objects: {collection_name}",
    )
    group_node.label = f"{label_prefix}: {collection_name}"
    return group_node.outputs["Geometry"], [group_node]
