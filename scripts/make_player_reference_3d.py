"""Build a true-3D player reference model from the supplied multi-view images.

The source screenshots are used as hidden viewport references and visual
validation targets. The model itself is a low-poly, rigged-by-transform mesh;
it does not project the screenshots onto the character.

Outputs:
  assets/3d/reference3d/source/player_reference_3d.blend
  assets/3d/reference3d/previews/player_{front,three_quarter,side,back,face}.png
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import make_combat_prototype as base  # noqa: E402
import player_mesh_helpers as helpers  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "assets" / "3d" / "reference3d" / "references"
OUT_DIR = ROOT / "assets" / "3d" / "reference3d"
BLEND_PATH = OUT_DIR / "source" / "player_reference_3d.blend"
PREVIEW_DIR = OUT_DIR / "previews"
SCENE_NAME = "AI_REALMS_PLAYER_REFERENCE_3D"
RESOLUTION = 1000


def remove_scene(name: str) -> None:
    scene = bpy.data.scenes.get(name)
    if scene is None:
        return
    if bpy.context.window is not None and bpy.context.window.scene == scene:
        fallback = next((item for item in bpy.data.scenes if item != scene), None)
        if fallback is not None:
            bpy.context.window.scene = fallback
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.scenes.remove(scene)


def new_scene():
    # Reuse the proven primitive/material helpers, but give this pass its own
    # scene name and output directory.
    remove_scene(SCENE_NAME)
    scene, collections = helpers.new_scene()
    scene.name = SCENE_NAME
    return scene, collections


def configure_scene(scene) -> None:
    helpers.configure(scene)
    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = 1
    scene.render.film_transparent = False
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    world = bpy.data.worlds.get(base.PREFIX + "REFERENCE3D_World")
    if world is None:
        world = bpy.data.worlds.new(base.PREFIX + "REFERENCE3D_World")
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")
    background = tree.nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = (*base.hex_rgb("#25282F"), 1.0)
    background.inputs["Strength"].default_value = 0.45
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    scene.world = world


def add_bevel(obj, width=0.02):
    modifier = obj.modifiers.new(base.PREFIX + "ReferenceBevel", "BEVEL")
    modifier.width = width
    modifier.segments = 1
    modifier.limit_method = "ANGLE"


def ring(x_front, x_back, half_y, z):
    # Eight-point faceted cross-section; front is +X, character width is Y.
    return [
        (x_front, 0.0, z),
        (x_front * 0.72, half_y * 0.72, z),
        (0.0, half_y, z),
        (x_back * 0.72, half_y * 0.72, z),
        (x_back, 0.0, z),
        (x_back * 0.72, -half_y * 0.72, z),
        (0.0, -half_y, z),
        (x_front * 0.72, -half_y * 0.72, z),
    ]


def make_ring_body(name, sections, material, collection, parent=None, bevel=0.02):
    vertices = []
    for x_front, x_back, half_y, z in sections:
        vertices.extend(ring(x_front, x_back, half_y, z))
    faces = []
    for level in range(len(sections) - 1):
        a = level * 8
        b = (level + 1) * 8
        for index in range(8):
            nxt = (index + 1) % 8
            faces.append((a + index, a + nxt, b + nxt, b + index))
    faces.append(tuple(range(0, 8)))
    faces.append(tuple(reversed(range((len(sections) - 1) * 8, len(sections) * 8))))
    obj = base.make_mesh(name, vertices, faces, material, collection, parent=parent)
    if bevel:
        add_bevel(obj, bevel)
    return obj


def extrude_yz(name, outline, x_front, x_back, material, collection, parent=None, bevel=0.015):
    count = len(outline)
    vertices = [(x_back, y, z) for y, z in outline]
    vertices += [(x_front, y, z) for y, z in outline]
    faces = [
        tuple(reversed(range(count))),
        tuple(range(count, count * 2)),
    ]
    for index in range(count):
        nxt = (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))
    obj = base.make_mesh(name, vertices, faces, material, collection, parent=parent)
    if bevel:
        add_bevel(obj, bevel)
    return obj


def extruded_crystal(name, outline, depth, material, collection, parent=None, location=(0, 0, 0), rotation=(0, 0, 0)):
    # Extrude a Y/Z outline along X, useful for the cyan chest crest.
    adjusted = [(y + location[1], z + location[2]) for y, z in outline]
    return extrude_yz(
        name, adjusted, location[0] + depth, location[0],
        material, collection, parent=parent, bevel=0.008,
    )


def make_reference_material(name, path):
    material = bpy.data.materials.get(base.PREFIX + name)
    if material is None:
        material = bpy.data.materials.new(base.PREFIX + name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(path), check_existing=True)
    texture.image.colorspace_settings.name = "sRGB"
    tree.links.new(texture.outputs["Color"], emission.inputs["Color"])
    emission.inputs["Strength"].default_value = 0.8
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def make_reference_plane(name, path, collection, location, rotation=(math.pi / 2, 0, 0), scale=(1.8, 3.0, 1.0)):
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    obj = bpy.context.active_object
    obj.name = base.PREFIX + name
    base.move_to_collection(obj, collection)
    material = make_reference_material(name + "Material", path)
    base.assign_material(obj, material)
    obj.location = location
    obj.rotation_euler = rotation
    obj.scale = scale
    obj.hide_render = True
    obj.hide_viewport = True
    obj["reference_path"] = str(path)
    return obj


def build_reference_planes(collection):
    paths = {
        "RefThreeQuarter": REFERENCE_DIR / "player_three_quarter.png",
        "RefFront": REFERENCE_DIR / "player_front.png",
        "RefBack": REFERENCE_DIR / "player_back.png",
        "RefFace": REFERENCE_DIR / "player_face_closeup.png",
    }
    locations = {
        "RefThreeQuarter": (4.0, -4.5, 1.45),
        "RefFront": (4.0, 0.0, 1.45),
        "RefBack": (-4.0, 0.0, 1.45),
        "RefFace": (2.8, -2.8, 2.35),
    }
    for name, path in paths.items():
        if path.exists():
            make_reference_plane(name, path, collection, locations[name])


def make_crest(collection, material, torso):
    crest = base.make_empty("Reference_Crest", collection, parent=torso, location=(0.36, 0.0, 0.44), size=0.08)
    crest.scale = (0.55, 0.55, 0.55)
    # Symmetrical rune silhouette from the front reference.
    outline = [
        (0.0, 0.25), (0.09, 0.12), (0.07, 0.02), (0.20, -0.02),
        (0.16, -0.12), (0.08, -0.08), (0.0, -0.25), (-0.08, -0.08),
        (-0.16, -0.12), (-0.20, -0.02), (-0.07, 0.02), (-0.09, 0.12),
    ]
    extruded_crystal("Reference_CrestMesh", outline, 0.025, material, collection, parent=crest)
    base.make_cube(
        "Reference_CrestCenter", (0.02, 0.0, 0.02), (0.028, 0.035, 0.24),
        material, collection, parent=crest, bevel=0.006,
    )
    return crest


def build_head(collection, mat, torso):
    head = base.make_empty("Reference_Head", collection, parent=torso, location=(0.0, 0.0, 0.88), size=0.16)
    base.make_ico(
        "Reference_Neck", (0.0, 0.0, -0.04), (0.13, 0.14, 0.16),
        mat["skin_shadow"], collection, parent=head, subdivisions=1,
    )
    base.make_ico(
        "Reference_Face", (0.03, 0.0, 0.22), (0.235, 0.205, 0.28),
        mat["skin"], collection, parent=head, subdivisions=2,
    )
    base.make_ico(
        "Reference_Jaw", (0.14, 0.0, 0.10), (0.13, 0.15, 0.11),
        mat["skin"], collection, parent=head, subdivisions=1,
    )
    base.make_cone(
        "Reference_Nose", (0.26, 0.0, 0.22), 0.065, 0.13,
        mat["skin"], collection, parent=head,
        rotation=(0, math.pi / 2, 0), vertices=4,
    )
    for side, y in (("R", -0.19), ("L", 0.19)):
        base.make_ico(
            f"Reference_Ear_{side}", (-0.01, y, 0.20), (0.07, 0.05, 0.10),
            mat["skin_shadow"], collection, parent=head, subdivisions=1,
        )
        base.make_cube(
            f"Reference_EyeWhite_{side}", (0.225, y * 0.53, 0.27), (0.035, 0.075, 0.045),
            base.make_material("Reference_EyeWhite", "#E8E2D5", roughness=0.5),
            collection, parent=head, bevel=0.008,
        )
        base.make_cube(
            f"Reference_EyeDark_{side}", (0.255, y * 0.53, 0.27), (0.015, 0.035, 0.040),
            mat["armor_dark"], collection, parent=head, bevel=0.004,
        )
        base.make_cube(
            f"Reference_Brow_{side}", (0.22, y * 0.53, 0.335), (0.035, 0.09, 0.025),
            mat["hair"], collection, parent=head,
            rotation=(0, math.radians(-5), 0), bevel=0.004,
        )
    base.make_cube(
        "Reference_Mouth", (0.225, 0.0, 0.12), (0.015, 0.07, 0.012),
        mat["skin_shadow"], collection, parent=head, bevel=0.0,
    )

    # Faceted swept hair from the close-up reference.
    base.make_ico(
        "Reference_HairCap", (-0.02, 0.015, 0.46), (0.245, 0.215, 0.14),
        mat["hair"], collection, parent=head, subdivisions=1,
        rotation=(0, math.radians(-7), math.radians(-3)),
    )
    for index, (y, z, sx, sy, sz, angle) in enumerate((
        (-0.14, 0.39, 0.20, 0.075, 0.11, -18),
        (-0.045, 0.40, 0.20, 0.09, 0.10, -10),
        (0.06, 0.40, 0.18, 0.08, 0.095, -3),
        (0.15, 0.43, 0.13, 0.06, 0.08, 8),
    )):
        base.make_ico(
            f"Reference_HairLock_{index}", (0.13, y, z), (sx, sy, sz),
            mat["hair_light"] if index in (0, 2) else mat["hair"],
            collection, parent=head, subdivisions=1,
            rotation=(0, math.radians(angle), 0),
        )
    base.make_ico(
        "Reference_HairBack", (-0.20, 0.02, 0.28), (0.14, 0.20, 0.23),
        mat["hair"], collection, parent=head, subdivisions=1,
        rotation=(0, math.radians(12), math.radians(-5)),
    )
    return head


def build_arm(side, y, collection, mat, torso):
    upper = base.make_empty(f"Reference_Arm{side}_Upper", collection, parent=torso, location=(0.0, y, 0.70))
    base.make_ico(
        f"Reference_MailUpper_{side}", (0.0, 0.0, -0.25), (0.115, 0.115, 0.27),
        mat["mail"], collection, parent=upper, subdivisions=3,
    )
    # Layered angular shoulder plates.
    for index, (x, z, scale, material) in enumerate((
        (0.0, 0.04, (0.24, 0.17, 0.115), mat["silver"]),
        (-0.03, -0.10, (0.22, 0.15, 0.10), mat["silver_mid"]),
        (-0.05, -0.20, (0.18, 0.125, 0.08), mat["silver_dark"]),
    )):
        base.make_ico(
            f"Reference_Pauldron_{side}_{index}", (x, 0.0, z), scale,
            material, collection, parent=upper, subdivisions=1,
            rotation=(0, math.radians(3 + index * 3), math.radians(-3 if y < 0 else 3)),
        )
    # A round front clasp and a cyan edge strip.
    base.make_cylinder(
        f"Reference_ShoulderClasp_{side}", (0.25, 0.0, 0.02), 0.085, 0.045,
        mat["silver_dark"], collection, parent=upper,
        rotation=(0, math.pi / 2, 0), vertices=10,
    )
    base.make_cube(
        f"Reference_ShoulderTrim_{side}", (0.20, -0.18 if y < 0 else 0.18, -0.05),
        (0.028, 0.022, 0.28), mat["cyan"], collection, parent=upper, bevel=0.006,
    )
    fore = base.make_empty(f"Reference_Arm{side}_Fore", collection, parent=upper, location=(0.0, 0.0, -0.48))
    base.make_ico(
        f"Reference_MailFore_{side}", (0.0, 0.0, -0.20), (0.105, 0.105, 0.23),
        mat["mail"], collection, parent=fore, subdivisions=3,
    )
    base.make_ico(
        f"Reference_Elbow_{side}", (0.06, 0.0, 0.01), (0.13, 0.13, 0.12),
        mat["silver_dark"], collection, parent=fore, subdivisions=1,
    )
    for index, z in enumerate((-0.12, -0.25, -0.37)):
        base.make_cube(
            f"Reference_Bracer_{side}_{index}", (0.07, -0.10 if y < 0 else 0.10, z),
            (0.105, 0.055, 0.10), mat["silver"] if index != 1 else mat["silver_mid"],
            collection, parent=fore, bevel=0.018,
        )
    hand = base.make_empty(f"Reference_Hand{side}", collection, parent=fore, location=(0.0, 0.0, -0.49))
    base.make_ico(
        f"Reference_Glove_{side}", (0.0, 0.0, 0.0), (0.13, 0.105, 0.15),
        mat["leather"], collection, parent=hand, subdivisions=1,
    )
    for finger in range(3):
        base.make_cube(
            f"Reference_Finger_{side}_{finger}", (0.02, -0.06 + finger * 0.06, -0.10),
            (0.09, 0.025, 0.035), mat["leather_light"], collection, parent=hand, bevel=0.01,
        )
    return upper, fore, hand


def build_leg(side, y, forward, collection, mat, pelvis):
    upper = base.make_empty(f"Reference_Leg{side}_Upper", collection, parent=pelvis, location=(0.0, y, -0.05))
    base.make_ico(
        f"Reference_Thigh_{side}", (0.0, 0.0, -0.25), (0.135, 0.14, 0.28),
        mat["cloth"], collection, parent=upper, subdivisions=1,
    )
    lower = base.make_empty(f"Reference_Leg{side}_Lower", collection, parent=upper, location=(0.0, 0.0, -0.48))
    base.make_ico(
        f"Reference_Shin_{side}", (0.0, 0.0, -0.21), (0.12, 0.12, 0.25),
        mat["leather"], collection, parent=lower, subdivisions=1,
    )
    base.make_ico(
        f"Reference_Knee_{side}", (0.10, 0.0, 0.01), (0.15, 0.16, 0.14),
        mat["silver"], collection, parent=lower, subdivisions=1,
        rotation=(0, math.radians(-8), 0),
    )
    for index, z in enumerate((-0.14, -0.28, -0.42)):
        base.make_cube(
            f"Reference_Greave_{side}_{index}", (0.08, -0.11 if y < 0 else 0.11, z),
            (0.10, 0.055, 0.12), mat["silver"] if index != 1 else mat["silver_mid"],
            collection, parent=lower, bevel=0.018,
        )
    base.make_cube(
        f"Reference_Boot_{side}", (0.11, 0.0, -0.53), (0.28, 0.18, 0.12),
        mat["leather"], collection, parent=lower, bevel=0.04,
    )
    base.make_cube(
        f"Reference_Toe_{side}", (0.30, 0.0, -0.55), (0.14, 0.20, 0.10),
        mat["leather"], collection, parent=lower, bevel=0.035,
    )
    base.make_cube(
        f"Reference_Sole_{side}", (0.18, 0.0, -0.61), (0.36, 0.21, 0.035),
        mat["cloth"], collection, parent=lower, bevel=0.012,
    )
    direction = 1.0 if forward else -1.0
    upper.rotation_euler.y = direction * 0.14
    lower.rotation_euler.y = -direction * 0.10
    return upper, lower


def build_sword(collection, mat, hand):
    sword = base.make_empty("Reference_Sword", collection, parent=hand, size=0.18)
    # Reference pose holds the sword down and slightly forward.
    segment(
        "Reference_SwordGrip", (0, 0, 0), (0, 0, -0.28), 0.055,
        mat["leather"], collection, parent=sword, vertices=8,
    )
    make_cylinder_local(
        "Reference_SwordGuard", (0, 0, -0.30), 0.065, 0.34,
        mat["silver_dark"], collection, sword,
        rotation=(math.pi / 2, 0, 0), vertices=8,
    )
    blade_verts = [
        (-0.075, -0.035, -0.34), (-0.075, 0.035, -0.34),
        (-0.09, 0.035, -1.22), (0.0, 0.0, -1.38),
        (0.09, 0.035, -1.22), (0.075, -0.035, -0.34),
        (0.075, 0.035, -0.34), (0.075, -0.035, -0.34),
    ]
    # Build a clean six-sided blade strip with a pointed tip.
    blade_verts = [
        (-0.075, -0.035, -0.34), (-0.075, 0.035, -0.34),
        (-0.085, 0.035, -1.18), (0.0, 0.0, -1.38),
        (0.085, 0.035, -1.18), (0.075, -0.035, -0.34),
        (0.075, 0.035, -0.34), (0.075, -0.035, -0.34),
    ]
    blade_faces = [
        (0, 1, 2, 3, 4, 5), (5, 4, 7, 6), (1, 0, 6, 7),
        (0, 3, 5, 6), (3, 2, 4, 5), (2, 1, 7, 4),
    ]
    base.make_mesh("Reference_SwordBlade", blade_verts, blade_faces, mat["cyan"], collection, parent=sword)
    return sword


def segment(name, start, end, radius, material, collection, parent=None, vertices=6):
    return base.segment(name, start, end, radius, material, collection, parent=parent, vertices=vertices)


def make_cylinder_local(name, location, radius, depth, material, collection, parent, rotation=(0, 0, 0), vertices=8):
    return base.make_cylinder(name, location, radius, depth, material, collection, parent=parent, rotation=rotation, vertices=vertices)


def build_player(collection, mat):
    root = base.make_empty("Reference_ROOT", collection, size=0.30)
    pelvis = base.make_empty("Reference_Pelvis", collection, parent=root, location=(0.0, 0.0, 1.18))
    make_ring_body(
        "Reference_PelvisBody",
        [(0.16, -0.16, 0.25, -0.08), (0.19, -0.18, 0.30, 0.15), (0.19, -0.18, 0.30, 0.25)],
        mat["armor_dark"], collection, parent=pelvis, bevel=0.025,
    )
    base.make_cube(
        "Reference_Belt", (0.0, 0.0, 0.25), (0.39, 0.48, 0.10),
        mat["leather"], collection, parent=pelvis, bevel=0.025,
    )
    base.make_cube(
        "Reference_Buckle", (0.34, 0.0, 0.25), (0.06, 0.15, 0.13),
        mat["silver"], collection, parent=pelvis, bevel=0.015,
    )
    base.make_cube(
        "Reference_BuckleInset", (0.38, 0.0, 0.25), (0.018, 0.075, 0.065),
        mat["cyan"], collection, parent=pelvis, bevel=0.006,
    )

    # Split coat panels: front panels, side panels, and a back center panel.
    panels = [
        ("FrontL", 0.20, 0.0, 0.13, 0.09, -0.48),
        ("FrontC", 0.22, 0.0, 0.15, 0.10, -0.56),
        ("FrontR", 0.20, 0.0, 0.13, 0.09, -0.48),
        ("SideL", 0.17, -0.27, 0.10, 0.085, -0.40),
        ("SideR", 0.17, 0.27, 0.10, 0.085, -0.40),
    ]
    for name, x, y, half_x, half_y, bottom in panels:
        # Custom hanging trapezoid, slightly rotated around Z for a layered coat.
        panel = base.make_empty(f"Reference_Coat{name}", collection, parent=pelvis, location=(x, y, 0.22))
        panel.rotation_euler.z = math.radians(-8 if "L" in name else 8 if "R" in name else 0)
        outline = [
            (-half_x, 0.02), (half_x, 0.02), (half_x * 0.88, bottom), (-half_x * 0.88, bottom),
        ]
        extrude_yz(f"Reference_CoatPanel{name}", outline, 0.0, -0.045,
                   mat["armor"] if "C" in name else mat["armor_dark"], collection, parent=panel, bevel=0.012)
        base.make_cube(
            f"Reference_CoatTrim{name}", (0.0, 0.0, bottom + 0.025), (0.025, half_x * 1.65, 0.025),
            mat["silver_dark"], collection, parent=panel, bevel=0.006,
        )
    # Center mail panel visible between the split coat tails.
    extrude_yz(
        "Reference_CenterMail",
        [(-0.075, 0.02), (0.075, 0.02), (0.06, -0.36), (-0.06, -0.36)],
        0.235, 0.19, mat["mail"], collection, parent=pelvis, bevel=0.008,
    )
    # Back split panel and hood are visible in the back reference.
    back_panel = base.make_empty("Reference_CoatBack", collection, parent=pelvis, location=(-0.24, 0.0, 0.22))
    extrude_yz(
        "Reference_CoatBackPanel",
        [(-0.14, 0.02), (0.14, 0.02), (0.13, -0.50), (-0.13, -0.50)],
        0.0, -0.045, mat["armor_dark"], collection, parent=back_panel, bevel=0.012,
    )
    base.make_ico(
        "Reference_Hood", (-0.19, 0.0, 0.78), (0.23, 0.30, 0.16),
        mat["armor_dark"], collection, parent=torso if False else pelvis, subdivisions=1,
    )

    torso = base.make_empty("Reference_Torso", collection, parent=pelvis, location=(0.0, 0.0, 0.10))
    make_ring_body(
        "Reference_TorsoBody",
        [(0.17, -0.17, 0.25, 0.00), (0.21, -0.19, 0.31, 0.22), (0.23, -0.20, 0.35, 0.50), (0.14, -0.15, 0.21, 0.70)],
        mat["armor_dark"], collection, parent=torso, bevel=0.025,
    )
    # Front breastplate with a faceted outline, based on the front screenshot.
    extrude_yz(
        "Reference_ChestPlate",
        [(-0.28, 0.05), (0.28, 0.05), (0.35, 0.25), (0.28, 0.55), (0.17, 0.70), (-0.17, 0.70), (-0.28, 0.55), (-0.35, 0.25)],
        0.33, 0.24, mat["armor"], collection, parent=torso, bevel=0.018,
    )
    # Brown harness straps visible across the front breastplate.
    for side in (-1, 1):
        base.make_cube(
            f"Reference_ChestStrap_{side}", (0.355, side * 0.17, 0.38),
            (0.025, 0.045, 0.48), mat["leather"], collection, parent=torso,
            rotation=(math.radians(side * 20), 0.0, 0.0), bevel=0.005,
        )
        base.make_ico(
            f"Reference_StrapStud_{side}", (0.38, side * 0.17, 0.56),
            (0.035, 0.035, 0.035), mat["silver_dark"], collection,
            parent=torso, subdivisions=1,
        )
    # Shoulder/neck dark collar and chainmail scarf.
    base.make_ico(
        "Reference_Collar", (-0.03, 0.0, 0.78), (0.27, 0.34, 0.16),
        mat["armor_dark"], collection, parent=torso, subdivisions=1,
    )
    for index, (z, radius, minor) in enumerate(((0.82, 0.24, 0.052), (0.88, 0.22, 0.043))):
        bpy.ops.mesh.primitive_torus_add(major_segments=12, minor_segments=6, major_radius=radius, minor_radius=minor, location=(0, 0, z))
        ring_obj = bpy.context.active_object
        ring_obj.name = base.PREFIX + f"Reference_ScarfRing_{index}"
        base.move_to_collection(ring_obj, collection)
        base.assign_material(ring_obj, mat["mail"])
        if parent := torso:
            ring_obj.parent = parent
        ring_obj.location = (0.0, 0.0, z)
    for side in (-1, 1):
        base.make_cube(
            f"Reference_CollarSide_{side}", (0.0, side * 0.19, 0.78), (0.22, 0.10, 0.18),
            mat["armor"], collection, parent=torso,
            rotation=(math.radians(side * 15), math.radians(-7), 0), bevel=0.025,
        )
        base.make_cube(
            f"Reference_CollarFlap_{side}", (-0.12, side * 0.20, 0.73), (0.16, 0.10, 0.25),
            mat["armor_dark"], collection, parent=torso,
            rotation=(math.radians(side * 12), math.radians(-12), 0), bevel=0.035,
        )
    make_crest(collection, mat["cyan"], torso)
    build_head(collection, mat, torso)
    arm_r = build_arm("R", -0.35, collection, mat, torso)
    arm_l = build_arm("L", 0.35, collection, mat, torso)
    leg_r = build_leg("R", -0.15, False, collection, mat, pelvis)
    leg_l = build_leg("L", 0.15, True, collection, mat, pelvis)
    # The source neutral pose has the sword down in the near hand.
    sword = build_sword(collection, mat, arm_r[2])
    arm_r[0].rotation_euler = (0, math.radians(-7), math.radians(9))
    arm_r[1].rotation_euler = (0, math.radians(-11), math.radians(-5))
    arm_l[0].rotation_euler = (0, math.radians(7), math.radians(-9))
    arm_l[1].rotation_euler = (0, math.radians(11), math.radians(5))
    torso.rotation_euler = (0, math.radians(3), math.radians(-2))
    return {"root": root, "torso": torso, "head": None, "sword": sword}


def configure_camera(camera, location, target, ortho=None, lens=60):
    camera.location = location
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO" if ortho is not None else "PERSP"
    camera.data.lens = lens
    if ortho is not None:
        camera.data.ortho_scale = ortho


def render_views(scene, camera):
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    views = {
        "front": ((7.5, 0.0, 1.58), (0.0, 0.0, 1.40), None, 78),
        "three_quarter": ((5.0, -4.2, 2.55), (0.0, 0.0, 1.40), None, 70),
        "side": ((0.25, -10.0, 1.70), (0.0, 0.0, 1.28), 3.65, 60),
        "back": ((-7.5, 0.0, 1.58), (0.0, 0.0, 1.40), None, 78),
        "face": ((3.2, -2.8, 2.55), (0.0, 0.0, 2.23), None, 75),
    }
    for name, (location, target, ortho, lens) in views.items():
        configure_camera(camera, location, target, ortho, lens)
        scene.render.filepath = str(PREVIEW_DIR / f"player_{name}.png")
        bpy.ops.render.render(write_still=True)


def build(render=True):
    scene, collections = new_scene()
    configure_scene(scene)
    mat = helpers.materials()
    mat["ground"] = base.make_material("ReferenceGround", "#25282F", roughness=0.95)
    mat["backdrop"] = base.make_material("ReferenceBackdrop", "#25282F", roughness=1.0)
    # Add a few reference-only materials/objects without changing the render.
    build_reference_planes(collections["REFERENCE"])
    helpers.build_stage(scene, collections, mat)
    player = build_player(collections["PLAYER"], mat)
    scene["Reference3D_description"] = (
        "True-3D player reconstruction from supplied front, back, three-quarter, "
        "and face reference screenshots; reference planes are hidden from render."
    )
    OUT_DIR.joinpath("source").mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    camera = bpy.data.objects.get(base.PREFIX + "PF_Camera")
    if camera is None:
        camera = next(obj for obj in collections["STAGE"].objects if obj.type == "CAMERA")
    if render:
        render_views(scene, camera)
    return {
        "scene": scene.name,
        "objects": len(scene.objects),
        "blend": str(BLEND_PATH),
        "previews": [str(PREVIEW_DIR / f"player_{name}.png") for name in ("front", "three_quarter", "side", "back", "face")] if render else [],
    }


if __name__ == "__main__":
    build(render=True)
