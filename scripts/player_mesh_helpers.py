"""Shared low-level mesh/material helpers for the Blender prototypes.

The reference-driven player script imports these helpers for faceted geometry,
procedural chainmail materials, and simple primitive construction. The helper
also remains runnable as an isolated diagnostic scene.
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

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "3d" / "fidelity"
BLEND_PATH = OUT_DIR / "player_fidelity_v2.blend"
THREE_QUARTER_PATH = OUT_DIR / "player_fidelity_v2_three_quarter.png"
SIDE_PATH = OUT_DIR / "player_fidelity_v2_side.png"
SCENE_NAME = "AI_REALMS_PLAYER_FIDELITY_V2"
RESOLUTION = 1200


def remove_previous() -> None:
    old = bpy.data.scenes.get(SCENE_NAME)
    if old is None:
        return
    if bpy.context.window is not None and bpy.context.window.scene == old:
        fallback = next((scene for scene in bpy.data.scenes if scene != old), None)
        if fallback is not None:
            bpy.context.window.scene = fallback
    for obj in list(old.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.scenes.remove(old)


def new_scene():
    remove_previous()
    scene = bpy.data.scenes.new(SCENE_NAME)
    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    collections = {}
    for key in ("PLAYER", "STAGE", "LIGHTS", "REFERENCE"):
        collection = bpy.data.collections.new(base.PREFIX + "FIDELITY_" + key)
        scene.collection.children.link(collection)
        collections[key] = collection
    return scene, collections


def make_mail_material() -> bpy.types.Material:
    """Fine procedural mail cells; avoids oversized wireframe triangles."""
    material = base.make_material(
        "PF_ChainmailProcedural", "#151B1C", metallic=0.72, roughness=0.48,
    )
    tree = material.node_tree
    bsdf = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
    coordinate = tree.nodes.new("ShaderNodeTexCoord")
    voronoi = tree.nodes.new("ShaderNodeTexVoronoi")
    voronoi.voronoi_dimensions = "3D"
    voronoi.feature = "DISTANCE_TO_EDGE"
    voronoi.inputs["Scale"].default_value = 42.0
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.018
    ramp.color_ramp.elements[0].color = (*base.hex_rgb("#778386"), 1.0)
    ramp.color_ramp.elements[1].position = 0.075
    ramp.color_ramp.elements[1].color = (*base.hex_rgb("#111617"), 1.0)
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.24
    bump.inputs["Distance"].default_value = 0.018
    tree.links.new(coordinate.outputs["Generated"], voronoi.inputs["Vector"])
    tree.links.new(voronoi.outputs["Distance"], ramp.inputs["Fac"])
    tree.links.new(voronoi.outputs["Distance"], bump.inputs["Height"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return material


def materials() -> dict[str, bpy.types.Material]:
    return {
        "armor": base.make_material("PF_Armor", "#123B35", metallic=0.25, roughness=0.36),
        "armor_light": base.make_material("PF_ArmorLight", "#1B5148", metallic=0.28, roughness=0.34),
        "armor_dark": base.make_material("PF_ArmorDark", "#071B19", metallic=0.18, roughness=0.48),
        "silver": base.make_material("PF_Silver", "#D1DADB", metallic=0.82, roughness=0.25),
        "silver_mid": base.make_material("PF_SilverMid", "#939FA1", metallic=0.78, roughness=0.34),
        "silver_dark": base.make_material("PF_SilverDark", "#566164", metallic=0.72, roughness=0.42),
        "mail": make_mail_material(),
        "mail_edge": base.make_material("PF_ChainmailEdge", "#687477", metallic=0.76, roughness=0.38),
        "cyan": base.make_material("PF_Cyan", "#62F0DC", metallic=0.25, roughness=0.22, emission=1.25),
        "skin": base.make_material("PF_Skin", "#D49A72", roughness=0.68),
        "skin_shadow": base.make_material("PF_SkinShadow", "#9B644B", roughness=0.72),
        "hair": base.make_material("PF_Hair", "#32180F", roughness=0.82),
        "hair_light": base.make_material("PF_HairLight", "#4A2919", roughness=0.78),
        "leather": base.make_material("PF_Leather", "#2B1811", roughness=0.84),
        "leather_light": base.make_material("PF_LeatherLight", "#4B2C1B", roughness=0.78),
        "cloth": base.make_material("PF_Cloth", "#0A1112", roughness=0.95),
        "ground": base.make_material("PF_Ground", "#AAB2B2", roughness=0.9),
        "backdrop": base.make_material("PF_Backdrop", "#C7CBCB", roughness=1.0),
    }


def configure(scene) -> None:
    base.configure_scene(scene)
    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    world = bpy.data.worlds.get(base.PREFIX + "PF_World")
    if world is None:
        world = bpy.data.worlds.new(base.PREFIX + "PF_World")
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")
    background = tree.nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = (*base.hex_rgb("#C5CAC9"), 1.0)
    background.inputs["Strength"].default_value = 0.48
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    scene.world = world


def add_chain_overlay(source, name: str, collection, material, parent, thickness=0.013):
    overlay = source.copy()
    overlay.data = source.data.copy()
    overlay.name = base.PREFIX + name
    collection.objects.link(overlay)
    overlay.parent = parent
    overlay.location = source.location.copy()
    overlay.rotation_euler = source.rotation_euler.copy()
    overlay.scale = source.scale.copy()
    base.assign_material(overlay, material)
    modifier = overlay.modifiers.new(base.PREFIX + "MailGrid", "WIREFRAME")
    modifier.thickness = thickness
    modifier.use_replace = True
    modifier.use_even_offset = True
    modifier.use_boundary = True
    return overlay


def add_armor_stud(location, collection, material, parent=None, rotation=(math.pi / 2, 0, 0), radius=0.035):
    return base.make_cylinder(
        "PF_Stud", location, radius, 0.035, material, collection,
        parent=parent, rotation=rotation, vertices=8,
    )


def build_head(collection, mat, torso):
    head = base.make_empty("PF_Head", collection, parent=torso, location=(0.0, 0.0, 0.79), size=0.16)
    base.make_cube(
        "PF_Neck", (0.0, 0.0, 0.015), (0.13, 0.15, 0.16),
        mat["skin_shadow"], collection, parent=head, bevel=0.035,
    )
    base.make_ico(
        "PF_Face", (0.015, 0.0, 0.19), (0.235, 0.205, 0.285),
        mat["skin"], collection, parent=head, subdivisions=1,
    )
    base.make_ico(
        "PF_Chin", (0.145, 0.0, 0.085), (0.13, 0.145, 0.10),
        mat["skin"], collection, parent=head, subdivisions=1,
        rotation=(0.0, math.radians(-10), 0.0),
    )
    base.make_cone(
        "PF_Nose", (0.255, 0.0, 0.19), 0.070, 0.13,
        mat["skin"], collection, parent=head,
        rotation=(0.0, math.pi / 2.0, 0.0), vertices=4,
    )
    base.make_ico(
        "PF_Ear", (-0.015, 0.19, 0.18), (0.075, 0.055, 0.10),
        mat["skin_shadow"], collection, parent=head, subdivisions=1,
    )

    # Layered, swept hair masses create the angular source silhouette.
    base.make_ico(
        "PF_HairCap", (-0.035, 0.015, 0.39), (0.235, 0.205, 0.13),
        mat["hair"], collection, parent=head, subdivisions=1,
        rotation=(0.0, math.radians(-7), math.radians(-4)),
    )
    for index, (y, z, sx, sy, sz, ry) in enumerate((
        (-0.12, 0.315, 0.18, 0.075, 0.105, -18),
        (-0.03, 0.305, 0.195, 0.085, 0.10, -12),
        (0.07, 0.315, 0.17, 0.075, 0.095, -5),
        (0.145, 0.335, 0.125, 0.055, 0.08, 4),
    )):
        base.make_ico(
            f"PF_HairLock_{index}", (0.115, y, z), (sx, sy, sz),
            mat["hair_light"] if index in (0, 2) else mat["hair"],
            collection, parent=head, subdivisions=1,
            rotation=(0.0, math.radians(ry), 0.0),
        )
    base.make_ico(
        "PF_HairBack", (-0.205, 0.02, 0.24), (0.14, 0.20, 0.23),
        mat["hair"], collection, parent=head, subdivisions=1,
        rotation=(0.0, math.radians(13), math.radians(-6)),
    )
    base.make_ico(
        "PF_Sideburn", (0.015, -0.195, 0.205), (0.075, 0.045, 0.14),
        mat["hair"], collection, parent=head, subdivisions=1,
    )

    for side, y in (("Near", -0.202), ("Far", 0.202)):
        base.make_cube(
            f"PF_Eye_{side}", (0.145, y, 0.225), (0.070, 0.022, 0.030),
            mat["cyan"], collection, parent=head,
            rotation=(0.0, math.radians(-7), 0.0), bevel=0.0,
        )
        base.make_cube(
            f"PF_Brow_{side}", (0.13, y * 1.02, 0.267), (0.105, 0.020, 0.022),
            mat["hair"], collection, parent=head,
            rotation=(0.0, math.radians(8), 0.0), bevel=0.0,
        )
    base.make_cube(
        "PF_Mouth", (0.222, -0.03, 0.105), (0.018, 0.075, 0.010),
        mat["skin_shadow"], collection, parent=head, bevel=0.0,
    )
    head.rotation_euler = (0.0, math.radians(-2), math.radians(-7))
    return head


def build_arm(side: str, y: float, collection, mat, torso):
    upper = base.make_empty(
        f"PF_Arm{side}_Upper", collection, parent=torso,
        location=(0.0, y, 0.67),
    )
    base.make_ico(
        f"PF_ShoulderUnder_{side}", (0.0, 0.0, 0.025), (0.245, 0.165, 0.18),
        mat["armor_dark"], collection, parent=upper, subdivisions=1,
    )
    for index, (x, z, scale, material) in enumerate((
        (-0.02, 0.075, (0.285, 0.18, 0.155), mat["silver"]),
        (-0.055, -0.045, (0.255, 0.155, 0.115), mat["silver_mid"]),
        (-0.09, -0.145, (0.21, 0.13, 0.09), mat["silver_dark"]),
    )):
        base.make_ico(
            f"PF_Pauldron_{side}_{index}", (x, -0.015 if y < 0 else 0.015, z), scale,
            material, collection, parent=upper, subdivisions=1,
            rotation=(0.0, math.radians(5 + index * 4), math.radians(-4 if y < 0 else 4)),
        )
    if y < 0:
        for index, z in enumerate((0.08, -0.045, -0.15)):
            add_armor_stud((0.18, -0.225, z), collection, mat["cyan"] if index == 1 else mat["silver_dark"], upper)
        base.make_cube(
            "PF_ShoulderTrim", (0.17, -0.19, -0.015), (0.03, 0.022, 0.27),
            mat["cyan"], collection, parent=upper,
            rotation=(0.0, math.radians(-4), 0.0), bevel=0.0,
        )

    base.make_ico(
        f"PF_MailSleeve_{side}", (0.0, 0.0, -0.25), (0.145, 0.14, 0.29),
        mat["mail"], collection, parent=upper, subdivisions=3,
    )
    fore = base.make_empty(
        f"PF_Arm{side}_Fore", collection, parent=upper,
        location=(0.0, 0.0, -0.46),
    )
    base.make_ico(
        f"PF_MailFore_{side}", (0.0, 0.0, -0.20), (0.13, 0.125, 0.25),
        mat["mail"], collection, parent=fore, subdivisions=3,
    )
    base.make_ico(
        f"PF_Elbow_{side}", (0.055, 0.0, 0.015), (0.13, 0.13, 0.12),
        mat["silver_dark"], collection, parent=fore, subdivisions=1,
    )
    for index, z in enumerate((-0.13, -0.25, -0.36)):
        base.make_cube(
            f"PF_Bracer_{side}_{index}", (0.075, -0.105 if y < 0 else 0.105, z),
            (0.11, 0.055, 0.10), mat["silver"] if index != 1 else mat["silver_mid"],
            collection, parent=fore, bevel=0.025,
            rotation=(0.0, math.radians(-8 + index * 3), 0.0),
        )
    hand = base.make_empty(
        f"PF_Hand{side}", collection, parent=fore,
        location=(0.0, 0.0, -0.48),
    )
    base.make_ico(
        f"PF_Glove_{side}", (0.0, 0.0, 0.0), (0.125, 0.105, 0.145),
        mat["leather"], collection, parent=hand, subdivisions=1,
    )
    for finger in range(3):
        base.make_cube(
            f"PF_Finger_{side}_{finger}", (0.025, -0.06 + finger * 0.06, -0.10),
            (0.09, 0.025, 0.035), mat["leather_light"], collection,
            parent=hand, bevel=0.012,
        )
    return upper, fore, hand


def build_leg(side: str, y: float, forward: bool, collection, mat, pelvis):
    upper = base.make_empty(
        f"PF_Leg{side}_Upper", collection, parent=pelvis,
        location=(0.0, y, -0.11),
    )
    base.make_ico(
        f"PF_Thigh_{side}", (0.0, 0.0, -0.23), (0.17, 0.16, 0.28),
        mat["cloth"], collection, parent=upper, subdivisions=1,
    )
    base.make_cube(
        f"PF_ThighStrap_{side}", (0.04, -0.145 if y < 0 else 0.145, -0.22),
        (0.15, 0.035, 0.055), mat["leather"], collection,
        parent=upper, bevel=0.012,
    )
    lower = base.make_empty(
        f"PF_Leg{side}_Lower", collection, parent=upper,
        location=(0.0, 0.0, -0.46),
    )
    base.make_ico(
        f"PF_Shin_{side}", (0.0, 0.0, -0.20), (0.145, 0.14, 0.26),
        mat["leather"], collection, parent=lower, subdivisions=1,
    )
    base.make_ico(
        f"PF_Knee_{side}", (0.105, 0.0, 0.015), (0.15, 0.16, 0.14),
        mat["silver"], collection, parent=lower, subdivisions=1,
        rotation=(0.0, math.radians(-8), 0.0),
    )
    for index, z in enumerate((-0.15, -0.28, -0.40)):
        base.make_cube(
            f"PF_Greave_{side}_{index}", (0.085, -0.115 if y < 0 else 0.115, z),
            (0.10, 0.055, 0.115), mat["silver"] if index != 1 else mat["silver_mid"],
            collection, parent=lower, bevel=0.022,
        )
    base.make_cube(
        f"PF_Ankle_{side}", (0.02, 0.0, -0.43), (0.17, 0.17, 0.09),
        mat["silver_dark"], collection, parent=lower, bevel=0.025,
    )
    base.make_cube(
        f"PF_Boot_{side}", (0.11, 0.0, -0.51), (0.27, 0.18, 0.12),
        mat["leather"], collection, parent=lower, bevel=0.045,
    )
    base.make_cube(
        f"PF_Toe_{side}", (0.29, 0.0, -0.535), (0.14, 0.20, 0.10),
        mat["leather"], collection, parent=lower, bevel=0.04,
    )
    base.make_cube(
        f"PF_Sole_{side}", (0.19, 0.0, -0.60), (0.36, 0.21, 0.035),
        mat["cloth"], collection, parent=lower, bevel=0.015,
    )

    direction = 1.0 if forward else -1.0
    upper.rotation_euler.y = direction * 0.52
    lower.rotation_euler.y = -direction * 0.42
    return upper, lower


def build_player(collection, mat):
    root = base.make_empty("PF_ROOT", collection, size=0.28)
    pelvis = base.make_empty("PF_Pelvis", collection, parent=root, location=(0.0, 0.0, 1.18))
    base.make_ico(
        "PF_PelvisArmor", (0.0, 0.0, -0.01), (0.31, 0.37, 0.22),
        mat["armor_dark"], collection, parent=pelvis, subdivisions=1,
    )
    base.make_cube(
        "PF_Belt", (0.0, 0.0, 0.10), (0.34, 0.43, 0.10),
        mat["leather"], collection, parent=pelvis, bevel=0.035,
    )
    base.make_cube(
        "PF_Buckle", (0.335, 0.0, 0.10), (0.055, 0.16, 0.13),
        mat["silver"], collection, parent=pelvis, bevel=0.018,
    )
    base.make_cube(
        "PF_BuckleInset", (0.372, 0.0, 0.10), (0.018, 0.085, 0.065),
        mat["cyan"], collection, parent=pelvis, bevel=0.008,
    )

    # Five radial fauld panels create the layered armored skirt silhouette.
    for index, angle in enumerate((-80, -40, 0, 40, 80)):
        panel = base.make_empty(
            f"PF_Fauld_{index}", collection, parent=pelvis,
            location=(0.0, 0.0, 0.02),
        )
        panel.rotation_euler.z = math.radians(angle)
        base.tapered_box(
            f"PF_FauldPanel_{index}", 0.16, 0.37, 0.125, 0.09,
            -0.47 - (0.08 if angle == 0 else 0.0), 0.02,
            mat["armor"] if index % 2 == 0 else mat["armor_dark"],
            collection, parent=panel,
        )
        base.make_cube(
            f"PF_FauldTrim_{index}", (0.365, 0.0, -0.46 - (0.08 if angle == 0 else 0.0)),
            (0.022, 0.18, 0.03), mat["silver_dark"], collection,
            parent=panel, bevel=0.006,
        )

    torso = base.make_empty("PF_Torso", collection, parent=pelvis, location=(0.0, 0.0, 0.16))
    base.make_ico(
        "PF_Abdomen", (0.0, 0.0, 0.27), (0.25, 0.32, 0.31),
        mat["armor_dark"], collection, parent=torso, subdivisions=1,
    )
    base.tapered_box(
        "PF_ChestArmor", -0.22, 0.25, 0.32, 0.43, 0.34, 0.74,
        mat["armor"], collection, parent=torso,
    )
    base.make_cube(
        "PF_ChestInset", (0.265, 0.0, 0.53), (0.045, 0.29, 0.28),
        mat["armor_light"], collection, parent=torso, bevel=0.035,
    )
    for y in (-0.25, 0.25):
        base.make_cube(
            "PF_ChestEdge", (0.13, y, 0.54), (0.34, 0.035, 0.055),
            mat["silver_dark"], collection, parent=torso,
            rotation=(0.0, math.radians(-3), 0.0), bevel=0.008,
        )
    base.make_cube(
        "PF_CollarBack", (-0.04, 0.0, 0.79), (0.27, 0.37, 0.14),
        mat["armor_dark"], collection, parent=torso, bevel=0.05,
    )
    for side in (-1, 1):
        base.make_cube(
            f"PF_Collar_{side}", (0.02, side * 0.19, 0.80), (0.22, 0.12, 0.18),
            mat["armor"], collection, parent=torso,
            rotation=(math.radians(side * 16), math.radians(-8), 0.0), bevel=0.04,
        )
        base.make_cube(
            f"PF_CollarTrim_{side}", (0.12, side * 0.22, 0.80), (0.025, 0.035, 0.18),
            mat["cyan"], collection, parent=torso,
            rotation=(math.radians(side * 16), 0.0, 0.0), bevel=0.0,
        )

    # Source-style luminous geometric crest, placed where the side camera reads it.
    crest = base.make_empty("PF_Crest", collection, parent=torso, location=(0.295, -0.23, 0.55))
    base.make_diamond("PF_CrestDiamond", (0.0, 0.0, 0.0), (0.035, 0.025, 0.13), mat["cyan"], collection, parent=crest)
    base.make_cube("PF_CrestBar", (-0.02, -0.03, 0.08), (0.025, 0.025, 0.16), mat["cyan"], collection, parent=crest, bevel=0.0)
    base.make_cube("PF_CrestWingL", (-0.05, -0.03, -0.015), (0.025, 0.025, 0.10), mat["cyan"], collection, parent=crest, rotation=(0.0, math.radians(-28), 0.0), bevel=0.0)
    base.make_cube("PF_CrestWingR", (0.01, -0.03, -0.015), (0.025, 0.025, 0.10), mat["cyan"], collection, parent=crest, rotation=(0.0, math.radians(28), 0.0), bevel=0.0)

    head = build_head(collection, mat, torso)
    arm_near = build_arm("Near", -0.40, collection, mat, torso)
    arm_far = build_arm("Far", 0.40, collection, mat, torso)
    leg_near = build_leg("Near", -0.19, False, collection, mat, pelvis)
    leg_far = build_leg("Far", 0.19, True, collection, mat, pelvis)

    # Reference-like wide combat stance, with the torso subtly turned to camera.
    torso.rotation_euler = (0.0, math.radians(7), math.radians(-5))
    pelvis.rotation_euler.z = math.radians(-3)
    arm_near[0].rotation_euler = (0.0, math.radians(-7), math.radians(12))
    arm_near[1].rotation_euler = (0.0, math.radians(-22), math.radians(-8))
    arm_far[0].rotation_euler = (0.0, math.radians(20), math.radians(-8))
    arm_far[1].rotation_euler = (0.0, math.radians(-16), math.radians(5))

    return {
        "root": root,
        "pelvis": pelvis,
        "torso": torso,
        "head": head,
        "arm_near": arm_near,
        "arm_far": arm_far,
        "leg_near": leg_near,
        "leg_far": leg_far,
    }


def build_stage(scene, collections, mat):
    stage = collections["STAGE"]
    base.make_cube(
        "PF_Ground", (0.0, 0.0, -0.06), (40.0, 40.0, 0.12),
        mat["ground"], stage, bevel=0.0,
    )
    base.make_cube(
        "PF_Backdrop", (0.0, 10.0, 6.0), (40.0, 0.2, 12.0),
        mat["backdrop"], stage, bevel=0.0,
    )

    camera_data = bpy.data.cameras.new(base.PREFIX + "PF_Camera")
    camera_data.type = "PERSP"
    camera_data.lens = 62
    camera = bpy.data.objects.new(base.PREFIX + "PF_Camera", camera_data)
    stage.objects.link(camera)
    scene.camera = camera

    lights = collections["LIGHTS"]
    for name, location, energy, color, size in (
        ("Key", (-3.8, -4.5, 7.0), 850, (1.0, 0.88, 0.78), 4.5),
        ("Fill", (4.0, -2.5, 4.2), 520, (0.70, 0.92, 1.0), 3.5),
        ("Rim", (1.0, 3.5, 6.0), 950, (0.78, 1.0, 0.94), 3.0),
    ):
        data = bpy.data.lights.new(base.PREFIX + "PF_" + name, "AREA")
        data.energy = energy
        data.color = color
        data.shape = "DISK"
        data.size = size
        light = bpy.data.objects.new(base.PREFIX + "PF_" + name, data)
        lights.objects.link(light)
        light.location = location
        light.rotation_euler = (Vector((0, 0, 1.2)) - light.location).to_track_quat("-Z", "Y").to_euler()
    return camera


def point_camera(camera, location, target=(0.0, 0.0, 1.25), ortho=None):
    camera.location = location
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO" if ortho is not None else "PERSP"
    if ortho is not None:
        camera.data.ortho_scale = ortho


def render_views(scene, camera) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    point_camera(camera, (5.8, -5.5, 2.8), target=(0.0, 0.0, 1.16))
    scene.render.filepath = str(THREE_QUARTER_PATH)
    bpy.ops.render.render(write_still=True)

    point_camera(camera, (0.35, -10.0, 2.65), target=(0.0, 0.0, 1.20), ortho=3.55)
    scene.render.filepath = str(SIDE_PATH)
    bpy.ops.render.render(write_still=True)


def build(render: bool = True):
    scene, collections = new_scene()
    configure(scene)
    mat = materials()
    player = build_player(collections["PLAYER"], mat)
    camera = build_stage(scene, collections, mat)
    scene["PF_description"] = (
        "Player-only fidelity reconstruction based on assets/player/player.png; "
        "approval scene before combat-rig replacement"
    )
    player["root"]["PF_status"] = "reference-fidelity prototype"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    if render:
        render_views(scene, camera)
    return {
        "scene": scene.name,
        "objects": len(scene.objects),
        "blend": str(BLEND_PATH),
        "three_quarter": str(THREE_QUARTER_PATH) if render else None,
        "side": str(SIDE_PATH) if render else None,
    }


if __name__ == "__main__":
    build(render=True)
