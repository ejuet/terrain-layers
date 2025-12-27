def frame_nodes(nt, title: str, nodes_to_frame: list):
    """
    Put given nodes into a NodeFrame with a label/title.
    Returns the created frame.
    """
    if not nodes_to_frame:
        return None

    frame = nt.nodes.new("NodeFrame")
    frame.label = title
    frame.name = title

    # Place the frame roughly around the first node; Blender will grow/shrink visually.
    first = nodes_to_frame[0]
    frame.location = (first.location.x - 120, first.location.y + 120)

    for n in nodes_to_frame:
        if n:
            n.parent = frame

    return frame
