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
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in value) or "Path"


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
