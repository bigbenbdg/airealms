"""Generate the six map backgrounds in Blender (stylized flat-shaded art).

Renders one 1440x570 PNG per location into assets/backgrounds/ for the
agent viewer's scene stage (engines/viewer.py).

Run headless:
    blender --background --python scripts/make_backgrounds.py

Or paste the body into Blender's scripting console / the Blender MCP
`execute_blender_code` tool. Pure emission materials + Standard view
transform = exact palette colors, and an orthographic side-view camera
matches the viewer's 960x380 stage.

After generating, shrink the files with:
    python scripts/optimize_backgrounds.py
"""
import math
import os

import bpy

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "backgrounds")
W, H = 1440, 570
ORTHO = 30.0
CAM_Z = 5.5

SKY_BOTTOM = {"town": "#141A2A", "dungeon": "#0F0B10"}
PALETTE = {"ink": "#12141C", "gold": "#C9A24B", "verdigris": "#4E9585",
           "blood": "#9E3B34", "parchment": "#EDE7D9"}


def srgb_to_linear(c):
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))


def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
                  bpy.data.lights, bpy.data.curves):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def setup_render():
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_EEVEE"
    scn.render.resolution_x, scn.render.resolution_y = W, H
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = "PNG"
    scn.render.film_transparent = False
    try:
        scn.view_settings.view_transform = "Standard"
        scn.view_settings.look = "None"
    except Exception:
        pass
    world = scn.world or bpy.data.worlds.new("BG_World")
    scn.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (*hex_rgb("#0A0C12"), 1.0)
    return scn


def mat(name, hexcolor):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*hex_rgb(hexcolor), 1.0)
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], o.inputs["Surface"])
    return m


def mat_gradient(name, bottom_hex, top_hex):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    em = nt.nodes.new("ShaderNodeEmission")
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (*hex_rgb(bottom_hex), 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (*hex_rgb(top_hex), 1.0)
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs[0], o.inputs["Surface"])
    return m


def use(obj, material):
    obj.data.materials.clear()
    obj.data.materials.append(material)
    return obj


def cube(loc, scale, material, name="cube", rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    return use(o, material)


def cone(loc, r, depth, material, rot=(0, 0, 0), verts=8, r2=0.0, name="cone"):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r2,
                                    depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return use(o, material)


def cyl(loc, r, depth, material, rot=(0, 0, 0), verts=8, name="cyl"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth,
                                        location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return use(o, material)


def ico(loc, r, material, scale=(1, 1, 1), name="ico"):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=r, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    return use(o, material)


def streak(p0, p1, y, width, material, name="streak"):
    """Thin cube spanning (x,z)=p0 -> p1 at depth y (lava flows on a slope)."""
    (x0, z0), (x1, z1) = p0, p1
    dx, dz = x1 - x0, z1 - z0
    length = math.hypot(dx, dz) or 0.001
    return cube(((x0 + x1) / 2, y, (z0 + z1) / 2), (width, 0.6, length),
                material, name, rot=(0, math.atan2(dx, dz), 0))


def camera():
    cam_data = bpy.data.cameras.new("BG_Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ORTHO
    cam = bpy.data.objects.new("BG_Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (0, -20, CAM_Z)
    cam.rotation_euler = (math.pi / 2, 0, 0)
    bpy.context.scene.camera = cam
    return cam


def sky(bottom_hex, top_hex):
    return cube((0, 6.0, CAM_Z), (ORTHO * 1.3, 2, 13),
                mat_gradient("sky", bottom_hex, top_hex), "sky")


def ground(hexcolor, top=0.0, depth=7.0):
    return cube((0, -1.0, top - depth / 2), (ORTHO * 1.3, 3, depth),
                mat("ground", hexcolor), "ground")


STARS = [(-13.0, 10.4), (-10.2, 8.1), (-7.4, 10.9), (-5.6, 7.2), (-3.1, 10.1),
         (-0.8, 8.8), (1.5, 11.1), (3.3, 7.6), (5.1, 9.9), (7.2, 6.9),
         (9.4, 10.6), (11.8, 8.4), (13.4, 11.0), (-11.6, 6.4)]


def stars(material, up_to=0):
    for i, (x, z) in enumerate(STARS):
        if up_to and i >= up_to:
            break
        ico((x, 4.5, z), 0.12, material)


# ---------------- locations ----------------

def build_forest():
    """Oakhollow Forest: layered pine ridges, moon, night green."""
    sky("#0D1A15", "#16241F")
    stars(mat("star", "#2E4A40"), up_to=8)
    ico((8.6, 5.0, 9.2), 0.95, mat("moon", "#CFE9DA"))
    ground("#0B1310")
    far = mat("far", "#1E3329")
    mid = mat("mid", "#2C5341")
    near = mat("near", "#437F6D")
    for i in range(20):
        x = i * 1.6 - 15.2
        h = 5.0 + (i % 3) * 0.9
        cone((x, 3.2, h / 2), 1.4, h, far)
    for i in range(12):
        x = i * 2.7 - 14.8
        h = 6.8 + (i % 2) * 1.3
        cone((x, 1.2, h / 2), 2.0, h, mid)
        cyl((x, 1.2, 1.0), 0.32, 2.0, mid)
    for x, h in ((-13.4, 11.5), (13.6, 10.0)):
        cone((x, -2.4, h / 2), 3.1, h, near)
        cyl((x, -2.4, 1.5), 0.52, 3.0, near)
    return "oakhollow_forest"


def build_cave():
    """Deep Cave: stalactites, boulders, blood glow."""
    sky("#0F0B10", "#1A1218")
    ico((7.5, 5.0, 8.6), 2.4, mat("glow", "#3B1E22"), scale=(1.6, 1, 1))
    ground("#0C080C")
    rock = mat("rock", "#241A22")
    rock2 = mat("rock2", "#3A2A32")
    edge = mat("edge", "#5A3A40")
    for i, (x, w, h) in enumerate([(-12, 2.0, 4.2), (-6.5, 2.6, 5.6), (-1.0, 1.8, 3.6),
                                   (4.5, 2.8, 6.0), (10.5, 2.2, 4.6)]):
        cone((x, -1.5, h / 2 - 0.6), w, h, rock2 if i % 2 else edge)
    for x, r in [(-14, 1.5), (-8, 1.9), (0.5, 1.6), (7.5, 2.0), (14, 1.4)]:
        ico((x, -3.0, r * 0.5), r, rock, scale=(1.4, 1, 0.8))
    for i in range(11):
        x = i * 3.0 - 15.0
        h = 3.0 + (i % 3) * 1.6
        cone((x, 2.5, 11.4 - h / 2), 1.1 + (i % 2) * 0.5, h, rock,
             rot=(math.pi, 0, 0))
    return "deep_cave"


def build_village():
    """Riverside Village: cottages on the bank, river in the foreground."""
    gz = 1.8
    sky("#141A2A", "#1E2436")
    stars(mat("star", "#5A6A8C"), up_to=11)
    ico((9.4, 5.0, 10.2), 0.85, mat("moon", "#EDE7D9"))
    ground("#0F1420", top=gz)
    house = mat("house", "#2A3350")
    house2 = mat("house2", "#333D60")
    roof = mat("roof", "#C9A24B")
    win = mat("window", "#E8B45C")
    for i, (x, h, w) in enumerate([(-12.2, 3.3, 3.4), (-8.0, 4.2, 3.8), (-3.6, 3.1, 3.2),
                                   (1.8, 4.4, 4.0), (6.6, 3.4, 3.4), (10.9, 4.0, 3.6)]):
        cube((x, 1.4, gz + h / 2), (w, 2.8, h), house if i % 2 == 0 else house2, "house")
        cone((x, 1.4, gz + h + 0.72), w * 0.62, 1.5, roof, verts=4, name="roof")
        for sx in (-1, 1):
            cube((x + sx * w * 0.22, -0.05, gz + h * 0.45),
                 (0.55, 0.12, 0.75), win, "win")
    cube((0, -3.4, gz - 1.7), (ORTHO * 1.4, 6, 3.4), mat("water", "#22385C"), "river")
    ripple = mat("ripple", "#31507E")
    for i in range(9):
        x = i * 3.3 - 13.2
        cube((x, -3.4, gz - 0.7 - (i % 2) * 0.55), (1.6, 0.5, 0.16), ripple, "ripple")
    cube((0, -1.4, gz - 0.18), (ORTHO * 1.3, 2.4, 0.36), mat("quay", "#1B2233"), "quay")
    return "riverside_village"


def build_city():
    """Capital City: keep, towers, curtain wall, gold roofs, banners."""
    sky("#171D33", "#202741")
    stars(mat("star", "#5A6A8C"), up_to=12)
    ico((-13.0, 5.0, 8.6), 1.0, mat("moon", "#EDE7D9"))
    stone = mat("stone", "#333C5C")
    stone2 = mat("stone2", "#424D73")
    gold = mat("gold", "#C9A24B")
    ground("#0F1420")
    cube((0, 1.6, 1.6), (22, 2.2, 3.2), stone)
    for i in range(15):
        cube((i * 1.55 - 11, 1.6, 3.4), (0.8, 2.4, 0.9), stone2, "merlon")
    cube((0, 0.8, 4.6), (4.0, 3.0, 9.2), stone2, "keep")
    cone((0, 0.8, 10.2), 3.1, 3.0, gold, verts=4, name="keep_roof")
    for x in (-8.5, 8.5):
        cube((x, 1.0, 4.2), (2.6, 2.6, 8.4), stone, "tower")
        cone((x, 1.0, 9.3), 2.0, 2.6, gold, verts=4, name="tower_roof")
    cube((0, 0.4, 1.2), (2.2, 2.6, 2.4), mat("gate", "#151A2B"), "gate")
    for x in (-4.6, 4.6):
        cone((x, 0.6, 7.6), 0.5, 2.6, mat("banner", "#8C3038"), name="banner")
    return "capital_city"


def build_marsh():
    """Sunken Marsh: black water table, reeds, bare trees, wisps."""
    gz = 1.4
    sky("#0B1A19", "#132725")
    stars(mat("star", "#3E5C63"), up_to=10)
    ico((9.2, 5.0, 9.8), 0.75, mat("moon", "#B9D8CB"))
    ground("#080F0E", top=gz)
    trunk = mat("trunk", "#2F4039")
    reed = mat("reed", "#437F6D")
    for x, h in [(-12.6, 6.5), (-5.2, 7.8), (3.0, 5.9), (11.6, 6.9)]:
        cyl((x, 0.8, gz + h / 2), 0.34, h, trunk)
        for ang, ln in ((0.75, 2.4), (-0.65, 2.0), (1.25, 1.7)):
            cyl((x + math.sin(ang) * ln / 2, 0.8, gz + h - 1.0 + ln / 2),
                0.17, ln, trunk, rot=(0, ang, 0), verts=6)
    for i in range(30):
        x = i * 1.0 - 14.6
        h = 2.2 + (i % 4) * 0.8
        cone((x, -1.6, gz + h / 2 - 0.8), 0.24, h, reed, verts=5)
    cube((0, -3.4, gz - 1.6), (ORTHO * 1.4, 6, 3.2), mat("water", "#15302E"), "water")
    refl = mat("refl", "#1E4441")
    for i, x in enumerate((-9.4, -2.2, 4.8, 11.2)):
        cube((x, -3.4, gz - 0.6 - (i % 2) * 0.3), (2.4, 1.6, 0.14), refl, "refl")
    for x, z in ((-6.5, 4.4), (2.0, 4.8), (9.0, 4.1)):
        ico((x, 2.2, z), 0.40, mat("wisp", "#8FD3B6"))
    return "sunken_marsh"


def build_ridge():
    """Ember Ridge: volcano, crater glow, lava streaks, jagged rock."""
    sky("#160E12", "#2A1519")
    rock = mat("rock", "#2A1A1A")
    rock2 = mat("rock2", "#3A2320")
    lava = mat("lava", "#E8622F")
    lava2 = mat("lava2", "#FFA23C")
    ground("#160D0D")
    ico((0, 3.5, 8.2), 2.6, mat("haze", "#331812"), scale=(2.0, 1, 1.0))
    cone((0, 1.0, 4.6), 11.5, 9.2, rock, verts=12, r2=2.6, name="volcano")
    cone((0, 0.2, 4.5), 10.6, 9.0, rock2, verts=12, r2=2.3, name="volcano_inner")
    ico((0, 0.2, 8.78), 2.25, lava, scale=(1.15, 1, 0.26), name="crater_rim")
    ico((0, 0.2, 8.92), 1.80, lava2, scale=(1.05, 1, 0.28), name="crater")
    streak((1.2, 7.6), (5.6, 2.6), -4.6, 0.7, lava, "flow")
    streak((-1.0, 7.4), (-4.8, 2.8), -4.4, 0.6, lava, "flow")
    streak((0.5, 7.0), (2.0, 2.4), -4.2, 0.5, lava2, "flow")
    for i, (x, w, h) in enumerate([(-13.6, 1.6, 3.2), (-8.2, 2.0, 4.4), (-3.6, 1.4, 2.5),
                                   (4.2, 1.8, 3.7), (9.6, 1.6, 2.9), (14.2, 1.5, 3.3)]):
        cone((x, -3.2, h / 2 - 1.2), w, h, rock2 if i % 2 else rock, verts=5)
    for i in range(10):
        x = i * 3.1 - 13.8
        ico((x, -2.8, 0.3), 0.30, lava, scale=(1.7, 1, 0.5), name="ember")
    return "ember_ridge"


BUILDERS = {
    "riverside_village": build_village,
    "oakhollow_forest": build_forest,
    "capital_city": build_city,
    "deep_cave": build_cave,
    "sunken_marsh": build_marsh,
    "ember_ridge": build_ridge,
}


def generate(only=None):
    os.makedirs(OUT_DIR, exist_ok=True)
    done = []
    for loc_id, fn in BUILDERS.items():
        if only and loc_id not in only:
            continue
        clear()
        setup_render()
        camera()
        fn()
        path = os.path.join(OUT_DIR, loc_id + ".png")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        done.append(path)
    return done


if __name__ == "__main__":
    for p in generate():
        print("wrote", p)
