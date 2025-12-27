
# ============================================================
# Naming convention:
#   gn_value_*      -> create constant value
#   gn_math_*       -> math operation nodes (mul/sub/add/div)
#   gn_clamp_*      -> clamp helpers
# ============================================================

def gn_value_float(nt, value: float, *, label: str | None = None):
    n = nt.nodes.new("ShaderNodeValue")
    n.outputs[0].default_value = float(value)
    if label:
        n.label = label
    return n.outputs[0]

def gn_math_multiply(nt, a, b, *, label: str | None = None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = "MULTIPLY"
    if label:
        n.label = label
    nt.links.new(a, n.inputs[0])
    nt.links.new(b, n.inputs[1])
    return n.outputs["Value"]

def gn_math_subtract(nt, a, b, *, clamp: bool = False, label: str | None = None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = "SUBTRACT"
    n.use_clamp = bool(clamp)
    if label:
        n.label = label
    nt.links.new(a, n.inputs[0])
    nt.links.new(b, n.inputs[1])
    return n.outputs["Value"]

def gn_clamp_0_1(nt, value_socket, *, label: str | None = None):
    c = nt.nodes.new("ShaderNodeClamp")
    c.inputs["Min"].default_value = 0.0
    c.inputs["Max"].default_value = 1.0
    if label:
        c.label = label
    nt.links.new(value_socket, c.inputs["Value"])
    return c.outputs["Result"]
