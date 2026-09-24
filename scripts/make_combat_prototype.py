"""Build and render the AI Realms 3D combat vertical slice in Blender.

Prototype scope:
  * low-poly player based on assets/player/player.png
  * low-poly Giant Rat based on assets/monsters/giant_rat.png
  * Rusty Sword test weapon
  * 3.2 second, 30 fps side-view combat loop

The scene is generated procedurally so the source portraits remain untouched and
future roster assets can reuse the same rig/material conventions.

Run inside Blender:
    blender --background --python scripts/make_combat_prototype.py

Or from a running Blender MCP session:
    runpy.run_path(r"scripts/make_combat_prototype.py", run_name="__main__")
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "3d"
BLEND_DIR = OUT_DIR / "source"
PREVIEW_DIR = OUT_DIR / "previews"
BLEND_PATH = BLEND_DIR / "player_vs_giant_rat.blend"
HERO_PATH = PREVIEW_DIR / "player_vs_giant_rat_hero.png"
VIDEO_PATH = PREVIEW_DIR / "player_vs_giant_rat_30fps.mp4"

SCENE_NAME = "AI_REALMS_COMBAT_PROTO"
PREFIX = "ARP_"
FPS = 30
FRAME_START = 1
FRAME_END = 95  # frame 96 matches frame 1 for a clean loop
HERO_FRAME = 30
RESOLUTION = (1280, 720)


# ---------------------------------------------------------------------------
# Blender data helpers
# ---------------------------------------------------------------------------


def srgb_to_linear(value: float) -> float:
    value = max(0.0, min(1.0, value))
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(
        srgb_to_linear(int(value[index:index + 2], 16) / 255.0)
        for index in (0, 2, 4)
    )


def set_socket(node, names: tuple[str, ...], value) -> None:
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return


def make_material(
    name: str,
    color: str,
    *,
    metallic: float = 0.0,
    roughness: float = 0.65,
    emission: float = 0.0,
) -> bpy.types.Material:
    full_name = PREFIX + name
    material = bpy.data.materials.get(full_name)
    if material is None:
        material = bpy.data.materials.new(full_name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()

    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (280, 0)
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    rgba = (*hex_rgb(color), 1.0)
    set_socket(bsdf, ("Base Color",), rgba)
    set_socket(bsdf, ("Metallic",), metallic)
    set_socket(bsdf, ("Roughness",), roughness)
    set_socket(bsdf, ("IOR",), 1.45)
    if emission > 0.0:
        set_socket(bsdf, ("Emission Color", "Emission"), rgba)
        set_socket(bsdf, ("Emission Strength",), emission)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = rgba
    return material


def move_to_collection(obj, collection: bpy.types.Collection) -> None:
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def assign_material(obj, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


def finish_object(
    obj,
    name: str,
    collection: bpy.types.Collection,
    material: bpy.types.Material | None,
    *,
    parent=None,
    location=(0.0, 0.0, 0.0),
    rotation=(0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
) -> bpy.types.Object:
    obj.name = PREFIX + name
    move_to_collection(obj, collection)
    if material is not None:
        assign_material(obj, material)
    if parent is not None:
        obj.parent = parent
    obj.location = location
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = rotation
    obj.scale = scale
    if obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = False
    return obj


def make_empty(
    name: str,
    collection: bpy.types.Collection,
    *,
    parent=None,
    location=(0.0, 0.0, 0.0),
    rotation=(0.0, 0.0, 0.0),
    size: float = 0.12,
) -> bpy.types.Object:
    obj = bpy.data.objects.new(PREFIX + name, None)
    collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    obj.location = location
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = rotation
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = size
    return obj


def add_bevel(obj, width: float = 0.025) -> None:
    modifier = obj.modifiers.new("ARP_Bevel", "BEVEL")
    modifier.width = width
    modifier.segments = 1
    modifier.limit_method = "ANGLE"


def make_cube(
    name: str,
    location,
    scale,
    material,
    collection,
    *,
    parent=None,
    rotation=(0.0, 0.0, 0.0),
    bevel: float = 0.025,
):
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = bpy.context.active_object
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    finish_object(
        obj, name, collection, material,
        parent=parent, location=location, rotation=rotation,
    )
    if bevel > 0.0:
        add_bevel(obj, bevel)
    return obj


def make_ico(
    name: str,
    location,
    scale,
    material,
    collection,
    *,
    parent=None,
    rotation=(0.0, 0.0, 0.0),
    subdivisions: int = 1,
):
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=subdivisions, radius=1.0,
    )
    obj = bpy.context.active_object
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish_object(
        obj, name, collection, material,
        parent=parent, location=location, rotation=rotation,
    )


def make_cone(
    name: str,
    location,
    radius: float,
    depth: float,
    material,
    collection,
    *,
    parent=None,
    rotation=(0.0, 0.0, 0.0),
    vertices: int = 6,
    radius_top: float = 0.0,
):
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices,
        radius1=radius,
        radius2=radius_top,
        depth=depth,
    )
    obj = bpy.context.active_object
    return finish_object(
        obj, name, collection, material,
        parent=parent, location=location, rotation=rotation,
    )


def make_cylinder(
    name: str,
    location,
    radius: float,
    depth: float,
    material,
    collection,
    *,
    parent=None,
    rotation=(0.0, 0.0, 0.0),
    vertices: int = 8,
):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth,
    )
    obj = bpy.context.active_object
    return finish_object(
        obj, name, collection, material,
        parent=parent, location=location, rotation=rotation,
    )


def segment(
    name: str,
    start,
    end,
    radius: float,
    material,
    collection,
    *,
    parent=None,
    vertices: int = 6,
):
    start_v = Vector(start)
    end_v = Vector(end)
    direction = end_v - start_v
    midpoint = (start_v + end_v) * 0.5
    rotation = direction.to_track_quat("Z", "Y").to_euler()
    return make_cylinder(
        name, midpoint, radius, max(direction.length, 0.001),
        material, collection, parent=parent, rotation=rotation,
        vertices=vertices,
    )


def make_mesh(
    name: str,
    vertices,
    faces,
    material,
    collection,
    *,
    parent=None,
    location=(0.0, 0.0, 0.0),
    rotation=(0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
):
    mesh = bpy.data.meshes.new(PREFIX + name + "_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(PREFIX + name, mesh)
    collection.objects.link(obj)
    return finish_object(
        obj, name, collection, material,
        parent=parent, location=location, rotation=rotation, scale=scale,
    )


def tapered_box(
    name: str,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
    material,
    collection,
    *,
    parent=None,
):
    """Eight-vertex box tapered along X; coordinates are local to its parent."""
    vertices = [
        (x0, -y0, z0), (x0, y0, z0), (x1, y1, z0), (x1, -y1, z0),
        (x0, -y0, z1), (x0, y0, z1), (x1, y1, z1), (x1, -y1, z1),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    return make_mesh(name, vertices, faces, material, collection, parent=parent)


def make_diamond(name, location, scale, material, collection, *, parent=None):
    obj = make_cube(
        name, location, scale, material, collection,
        parent=parent, rotation=(0.0, math.pi / 4.0, 0.0), bevel=0.01,
    )
    return obj


# ---------------------------------------------------------------------------
# Scene lifecycle
# ---------------------------------------------------------------------------


def remove_previous_prototype() -> None:
    old_scene = bpy.data.scenes.get(SCENE_NAME)
    if old_scene is None:
        return
    if bpy.context.window is not None and bpy.context.window.scene == old_scene:
        fallback = next(
            (scene for scene in bpy.data.scenes if scene != old_scene), None
        )
        if fallback is not None:
            bpy.context.window.scene = fallback
    for obj in list(old_scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.scenes.remove(old_scene)


def purge_generated_data() -> None:
    for datablocks in (
        bpy.data.collections, bpy.data.meshes, bpy.data.curves,
        bpy.data.armatures, bpy.data.cameras, bpy.data.lights,
        bpy.data.materials, bpy.data.actions,
    ):
        for block in list(datablocks):
            if block.name.startswith(PREFIX) and block.users == 0:
                datablocks.remove(block)


def new_scene():
    remove_previous_prototype()
    purge_generated_data()
    scene = bpy.data.scenes.new(SCENE_NAME)
    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    collections = {}
    for key in ("STAGE", "PLAYER", "RAT", "FX", "LIGHTS"):
        collection = bpy.data.collections.new(PREFIX + key)
        scene.collection.children.link(collection)
        collections[key] = collection
    return scene, collections


def configure_scene(scene) -> None:
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_file_extension = True
    if hasattr(scene.render.image_settings, "media_type"):
        scene.render.image_settings.media_type = "IMAGE"
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
    except Exception:
        pass
    if hasattr(scene, "eevee"):
        eevee = scene.eevee
        for attr, value in (
            ("taa_render_samples", 64),
            ("taa_samples", 32),
            ("use_gtao", True),
            ("gtao_distance", 3.0),
            ("gtao_factor", 1.25),
        ):
            if hasattr(eevee, attr):
                try:
                    setattr(eevee, attr, value)
                except Exception:
                    pass

    world = bpy.data.worlds.get(PREFIX + "World")
    if world is None:
        world = bpy.data.worlds.new(PREFIX + "World")
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")
    background = tree.nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = (*hex_rgb("#172126"), 1.0)
    background.inputs["Strength"].default_value = 0.28
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    scene.world = world


def make_materials() -> dict[str, bpy.types.Material]:
    return {
        "ground": make_material("Ground", "#1A2522", roughness=0.95),
        "ground_edge": make_material("GroundEdge", "#0B1110", roughness=1.0),
        "backdrop": make_material("Backdrop", "#20332E", roughness=1.0),
        "backdrop2": make_material("Backdrop2", "#2D463B", roughness=1.0),
        "rock": make_material("Rock", "#3A4540", roughness=0.95),
        "moon": make_material("Moon", "#B7D9C7", roughness=0.8, emission=0.8),
        "armor": make_material("PlayerArmor", "#123B35", metallic=0.2, roughness=0.38),
        "armor_dark": make_material("PlayerArmorDark", "#0A1D1B", metallic=0.15, roughness=0.5),
        "silver": make_material("Silver", "#B9C4C6", metallic=0.78, roughness=0.3),
        "silver_dark": make_material("SilverDark", "#667679", metallic=0.72, roughness=0.42),
        "cyan": make_material("CyanTrim", "#5CE9D4", metallic=0.25, roughness=0.25, emission=1.4),
        "skin": make_material("Skin", "#C98E67", roughness=0.7),
        "hair": make_material("Hair", "#2A160E", roughness=0.85),
        "leather": make_material("Leather", "#352117", roughness=0.85),
        "boot": make_material("Boot", "#21130D", roughness=0.8),
        "rust": make_material("Rust", "#8A4D31", metallic=0.3, roughness=0.72),
        "rust_dark": make_material("RustDark", "#4A2D20", metallic=0.25, roughness=0.82),
        "blade": make_material("RustedBlade", "#756B5D", metallic=0.72, roughness=0.5),
        "rat_fur": make_material("RatFur", "#4B3021", roughness=0.92),
        "rat_fur_light": make_material("RatFurLight", "#795039", roughness=0.9),
        "rat_fur_dark": make_material("RatFurDark", "#26180F", roughness=0.95),
        "rat_skin": make_material("RatSkin", "#A75E42", roughness=0.78),
        "rat_tail": make_material("RatTail", "#9A5B44", roughness=0.75),
        "eye": make_material("AcidEye", "#B8FF3C", roughness=0.25, emission=3.0),
        "tooth": make_material("Tooth", "#F1D66B", roughness=0.6),
        "mouth": make_material("Mouth", "#160E0B", roughness=1.0),
        "impact": make_material("Impact", "#FFD166", roughness=0.3, emission=4.0),
        "slime": make_material("Slime", "#A8FF28", roughness=0.25, emission=2.2),
    }


# ---------------------------------------------------------------------------
# Stage, camera, lighting
# ---------------------------------------------------------------------------


def build_stage(scene, collections, materials):
    stage = collections["STAGE"]
    make_cube(
        "Ground", (0.0, 0.0, -0.09), (7.2, 3.5, 0.16),
        materials["ground"], stage, bevel=0.0,
    )
    make_cube(
        "GroundLip", (0.0, -1.74, -0.15), (7.2, 0.18, 0.25),
        materials["ground_edge"], stage, bevel=0.0,
    )
    make_cube(
        "Backdrop", (0.0, 3.0, 3.0), (9.0, 0.25, 6.0),
        materials["backdrop"], stage, bevel=0.0,
    )

    # Low-poly distant forest silhouettes keep the scene grounded without
    # competing with the two fighters.
    for index, x in enumerate((-5.5, -4.0, -2.7, 2.8, 4.1, 5.3)):
        height = 2.5 + (index % 3) * 0.55
        make_cone(
            f"BackTree_{index}", (x, 2.45, height * 0.5),
            0.72, height,
            materials["backdrop2"] if index % 2 else materials["backdrop"],
            stage, vertices=5,
        )
        make_cylinder(
            f"BackTrunk_{index}", (x, 2.45, 0.45), 0.15, 0.9,
            materials["backdrop2"], stage, vertices=6,
        )

    make_ico(
        "Moon", (2.8, 2.6, 4.0), (0.46, 0.08, 0.46),
        materials["moon"], stage, subdivisions=2,
    )
    for index, (x, z, scale) in enumerate((
        (-3.6, 0.16, 0.22), (-2.8, 0.10, 0.14), (2.2, 0.12, 0.16),
        (3.0, 0.18, 0.24), (4.0, 0.08, 0.12),
    )):
        make_ico(
            f"Rock_{index}", (x, 1.4, z), (scale, scale * 0.8, scale * 0.65),
            materials["rock"], stage, subdivisions=1,
        )

    # Sparse grass shards, kept behind the combat plane.
    for index in range(14):
        x = -4.8 + index * 0.72
        h = 0.18 + (index % 4) * 0.06
        make_cone(
            f"Grass_{index}", (x, 1.15, h * 0.5), 0.055, h,
            materials["backdrop2"], stage, vertices=4,
            rotation=(0.0, math.radians(12 if index % 2 else -12), 0.0),
        )

    camera_data = bpy.data.cameras.new(PREFIX + "CombatCamera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 6.25
    camera_data.lens = 52
    camera = bpy.data.objects.new(PREFIX + "CombatCamera", camera_data)
    stage.objects.link(camera)
    camera.location = (0.45, -12.5, 3.25)
    target = Vector((0.0, 0.0, 1.18))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera

    lights = collections["LIGHTS"]
    key_data = bpy.data.lights.new(PREFIX + "Key", "AREA")
    key_data.energy = 1050
    key_data.shape = "DISK"
    key_data.size = 5.0
    key_data.color = (1.0, 0.84, 0.68)
    key = bpy.data.objects.new(PREFIX + "Key", key_data)
    lights.objects.link(key)
    key.location = (-3.8, -4.8, 7.0)
    key.rotation_euler = (Vector((0, 0, 1.1)) - key.location).to_track_quat("-Z", "Y").to_euler()

    fill_data = bpy.data.lights.new(PREFIX + "Fill", "AREA")
    fill_data.energy = 620
    fill_data.shape = "RECTANGLE"
    fill_data.size = 4.0
    fill_data.size_y = 3.0
    fill_data.color = (0.34, 0.90, 0.83)
    fill = bpy.data.objects.new(PREFIX + "Fill", fill_data)
    lights.objects.link(fill)
    fill.location = (4.5, -3.2, 4.5)
    fill.rotation_euler = (Vector((0, 0, 1.0)) - fill.location).to_track_quat("-Z", "Y").to_euler()

    rim_data = bpy.data.lights.new(PREFIX + "Rim", "AREA")
    rim_data.energy = 1250
    rim_data.shape = "DISK"
    rim_data.size = 3.0
    rim_data.color = (0.78, 1.0, 0.91)
    rim = bpy.data.objects.new(PREFIX + "Rim", rim_data)
    lights.objects.link(rim)
    rim.location = (1.2, 3.8, 6.2)
    rim.rotation_euler = (Vector((0, 0, 1.2)) - rim.location).to_track_quat("-Z", "Y").to_euler()
    return camera


# ---------------------------------------------------------------------------
# Player and weapon
# ---------------------------------------------------------------------------


def build_player(collection, materials):
    root = make_empty("PLAYER_ROOT", collection, location=(-1.42, 0.0, 0.0), size=0.28)
    pelvis = make_empty("PLAYER_Pelvis", collection, parent=root, location=(0.0, 0.0, 1.04))
    make_cube(
        "PLAYER_PelvisArmor", (0.0, 0.0, 0.0), (0.28, 0.34, 0.20),
        materials["armor"], collection, parent=pelvis, bevel=0.05,
    )
    make_cube(
        "PLAYER_Belt", (0.0, -0.345, 0.0), (0.29, 0.035, 0.075),
        materials["leather"], collection, parent=pelvis, bevel=0.015,
    )
    make_cube(
        "PLAYER_Buckle", (0.0, -0.37, 0.0), (0.095, 0.028, 0.08),
        materials["cyan"], collection, parent=pelvis, bevel=0.012,
    )

    torso = make_empty("PLAYER_Torso", collection, parent=pelvis, location=(0.0, 0.0, 0.18))
    tapered_box(
        "PLAYER_TorsoLower", -0.19, 0.19, 0.27, 0.34, -0.12, 0.48,
        materials["armor_dark"], collection, parent=torso,
    )
    tapered_box(
        "PLAYER_Chest", -0.23, 0.22, 0.30, 0.36, 0.36, 0.75,
        materials["armor"], collection, parent=torso,
    )
    make_cube(
        "PLAYER_ChestInset", (0.225, 0.0, 0.55), (0.055, 0.24, 0.27),
        materials["armor_dark"], collection, parent=torso, bevel=0.025,
    )
    make_diamond(
        "PLAYER_Emblem", (0.265, -0.245, 0.56), (0.055, 0.035, 0.15),
        materials["cyan"], collection, parent=torso,
    )
    make_cube(
        "PLAYER_Collar", (0.0, 0.0, 0.78), (0.24, 0.30, 0.10),
        materials["leather"], collection, parent=torso, bevel=0.035,
    )

    head = make_empty("PLAYER_Head", collection, parent=torso, location=(0.0, 0.0, 0.78))
    make_cube(
        "PLAYER_Neck", (0.0, 0.0, 0.0), (0.13, 0.15, 0.15),
        materials["skin"], collection, parent=head, bevel=0.03,
    )
    make_ico(
        "PLAYER_HeadMesh", (0.025, 0.0, 0.19), (0.235, 0.205, 0.27),
        materials["skin"], collection, parent=head, subdivisions=2,
    )
    make_ico(
        "PLAYER_Hair", (0.0, 0.025, 0.38), (0.255, 0.22, 0.145),
        materials["hair"], collection, parent=head, subdivisions=1,
        rotation=(0.0, math.radians(-5), math.radians(-6)),
    )
    make_cube(
        "PLAYER_HairSpike", (-0.12, 0.0, 0.43), (0.18, 0.16, 0.12),
        materials["hair"], collection, parent=head,
        rotation=(0.0, math.radians(18), 0.0), bevel=0.03,
    )
    make_ico(
        "PLAYER_Nose", (0.25, 0.0, 0.19), (0.09, 0.07, 0.08),
        materials["skin"], collection, parent=head, subdivisions=1,
    )
    make_cube(
        "PLAYER_Eye", (0.19, -0.198, 0.245), (0.055, 0.025, 0.035),
        materials["cyan"], collection, parent=head, rotation=(0.0, math.radians(-8), 0.0), bevel=0.0,
    )
    make_cube(
        "PLAYER_Brow", (0.18, -0.205, 0.285), (0.09, 0.022, 0.025),
        materials["hair"], collection, parent=head, rotation=(0.0, math.radians(8), 0.0), bevel=0.0,
    )

    # Near/camera-side sword arm.
    arm_r = make_empty("PLAYER_ArmR_Upper", collection, parent=torso, location=(0.0, -0.34, 0.64))
    make_ico(
        "PLAYER_ShoulderR", (0.0, 0.0, 0.02), (0.27, 0.20, 0.23),
        materials["silver"], collection, parent=arm_r, subdivisions=1,
    )
    make_cube(
        "PLAYER_ArmR_UpperMesh", (0.0, 0.0, -0.24), (0.145, 0.145, 0.29),
        materials["armor_dark"], collection, parent=arm_r, bevel=0.04,
    )
    arm_r_fore = make_empty("PLAYER_ArmR_Fore", collection, parent=arm_r, location=(0.0, 0.0, -0.45))
    make_cube(
        "PLAYER_ArmR_ForeMesh", (0.0, 0.0, -0.20), (0.14, 0.14, 0.25),
        materials["silver_dark"], collection, parent=arm_r_fore, bevel=0.035,
    )
    make_cube(
        "PLAYER_ArmR_Trim", (0.07, -0.145, -0.20), (0.025, 0.025, 0.18),
        materials["cyan"], collection, parent=arm_r_fore, bevel=0.0,
    )
    hand_r = make_empty("PLAYER_HandR", collection, parent=arm_r_fore, location=(0.0, 0.0, -0.42))
    make_ico(
        "PLAYER_HandR_Mesh", (0.0, 0.0, 0.0), (0.14, 0.12, 0.15),
        materials["leather"], collection, parent=hand_r, subdivisions=1,
    )

    # Far arm.
    arm_l = make_empty("PLAYER_ArmL_Upper", collection, parent=torso, location=(0.0, 0.34, 0.64))
    make_ico(
        "PLAYER_ShoulderL", (0.0, 0.0, 0.02), (0.25, 0.18, 0.21),
        materials["silver_dark"], collection, parent=arm_l, subdivisions=1,
    )
    make_cube(
        "PLAYER_ArmL_UpperMesh", (0.0, 0.0, -0.24), (0.135, 0.135, 0.29),
        materials["armor_dark"], collection, parent=arm_l, bevel=0.035,
    )
    arm_l_fore = make_empty("PLAYER_ArmL_Fore", collection, parent=arm_l, location=(0.0, 0.0, -0.45))
    make_cube(
        "PLAYER_ArmL_ForeMesh", (0.0, 0.0, -0.20), (0.125, 0.125, 0.25),
        materials["silver_dark"], collection, parent=arm_l_fore, bevel=0.03,
    )
    hand_l = make_empty("PLAYER_HandL", collection, parent=arm_l_fore, location=(0.0, 0.0, -0.42))
    make_ico(
        "PLAYER_HandL_Mesh", (0.0, 0.0, 0.0), (0.13, 0.11, 0.14),
        materials["leather"], collection, parent=hand_l, subdivisions=1,
    )

    # Rusty Sword. Local +X is the blade direction.
    sword = make_empty("PLAYER_RustySword", collection, parent=hand_r, size=0.18)
    segment(
        "PLAYER_SwordGrip", (-0.24, 0.0, 0.0), (0.13, 0.0, 0.0),
        0.055, materials["leather"], collection, parent=sword, vertices=8,
    )
    make_ico(
        "PLAYER_SwordPommel", (-0.28, 0.0, 0.0), (0.09, 0.075, 0.09),
        materials["rust_dark"], collection, parent=sword, subdivisions=1,
    )
    make_cylinder(
        "PLAYER_SwordGuard", (0.15, 0.0, 0.0), 0.065, 0.38,
        materials["rust"], collection, parent=sword,
        rotation=(math.pi / 2.0, 0.0, 0.0), vertices=6,
    )
    blade_vertices = [
        (0.20, -0.045, -0.075), (0.20, 0.045, -0.075),
        (1.18, 0.045, -0.055), (1.42, 0.0, 0.0),
        (1.18, 0.045, 0.055), (1.18, -0.045, 0.055),
        (0.20, -0.045, 0.075), (0.20, 0.045, 0.075),
    ]
    blade_faces = [
        (0, 1, 2, 3, 4, 5), (5, 4, 7, 6),
        (1, 0, 6, 7), (0, 3, 5, 6), (3, 2, 4, 5), (2, 1, 7, 4),
    ]
    make_mesh(
        "PLAYER_RustyBlade", blade_vertices, blade_faces,
        materials["blade"], collection, parent=sword,
    )
    for index, (x, z) in enumerate(((0.43, 0.018), (0.72, -0.025), (0.98, 0.012))):
        make_ico(
            f"PLAYER_SwordRust_{index}", (x, -0.052, z), (0.11, 0.018, 0.035),
            materials["rust"], collection, parent=sword, subdivisions=1,
        )

    # Legs and armored boots.
    legs = {}
    for side, y in (("R", -0.17), ("L", 0.17)):
        upper = make_empty(f"PLAYER_Leg{side}_Upper", collection, parent=pelvis, location=(0.0, y, -0.10))
        make_cube(
            f"PLAYER_Leg{side}_UpperMesh", (0.0, 0.0, -0.20), (0.15, 0.15, 0.24),
            materials["leather"], collection, parent=upper, bevel=0.035,
        )
        lower = make_empty(f"PLAYER_Leg{side}_Lower", collection, parent=upper, location=(0.0, 0.0, -0.40))
        make_cube(
            f"PLAYER_Leg{side}_LowerMesh", (0.0, 0.0, -0.18), (0.125, 0.125, 0.22),
            materials["silver_dark"], collection, parent=lower, bevel=0.03,
        )
        make_ico(
            f"PLAYER_Knee{side}", (0.08, 0.0, 0.02), (0.12, 0.12, 0.12),
            materials["silver"], collection, parent=lower, subdivisions=1,
        )
        make_cube(
            f"PLAYER_Boot{side}", (0.09, 0.0, -0.40), (0.25, 0.16, 0.11),
            materials["boot"], collection, parent=lower, bevel=0.045,
        )
        make_cube(
            f"PLAYER_Toe{side}", (0.24, 0.0, -0.42), (0.10, 0.17, 0.09),
            materials["boot"], collection, parent=lower, bevel=0.035,
        )
        legs[side] = (upper, lower)

    # A readable combat-ready rest pose. The near arm reaches toward screen
    # right (+X); the sword joint supplies the opposing angle so the blade
    # sits above the ready line instead of behind the fighter.
    torso.rotation_euler.y = 0.08
    arm_r.rotation_euler.y = -0.55
    arm_r_fore.rotation_euler.y = -0.10
    hand_r.rotation_euler.y = 0.0
    sword.rotation_euler.y = -0.20
    arm_l.rotation_euler.y = 0.20
    arm_l_fore.rotation_euler.y = -0.18
    legs["R"][0].rotation_euler.y = -0.24
    legs["R"][1].rotation_euler.y = 0.12
    legs["L"][0].rotation_euler.y = 0.24
    legs["L"][1].rotation_euler.y = -0.10

    return {
        "root": root,
        "pelvis": pelvis,
        "torso": torso,
        "head": head,
        "arm_r": arm_r,
        "fore_r": arm_r_fore,
        "hand_r": hand_r,
        "arm_l": arm_l,
        "fore_l": arm_l_fore,
        "leg_r": legs["R"][0],
        "shin_r": legs["R"][1],
        "leg_l": legs["L"][0],
        "shin_l": legs["L"][1],
        "sword": sword,
    }


# ---------------------------------------------------------------------------
# Giant Rat
# ---------------------------------------------------------------------------


def build_rat(collection, materials):
    root = make_empty("RAT_ROOT", collection, location=(1.18, 0.0, 0.0), size=0.24)
    body = make_empty("RAT_Body", collection, parent=root, location=(0.0, 0.0, 0.68))
    make_ico(
        "RAT_Torso", (0.0, 0.0, 0.0), (0.74, 0.42, 0.46),
        materials["rat_fur"], collection, parent=body, subdivisions=2,
        rotation=(0.0, math.radians(-3), 0.0),
    )
    make_ico(
        "RAT_Haunch", (0.36, 0.0, 0.02), (0.43, 0.40, 0.40),
        materials["rat_fur_light"], collection, parent=body, subdivisions=1,
    )
    make_ico(
        "RAT_Belly", (-0.08, 0.0, -0.30), (0.57, 0.31, 0.22),
        materials["rat_fur_dark"], collection, parent=body, subdivisions=1,
    )

    for index, (x, z, scale) in enumerate((
        (-0.28, 0.37, 0.18), (0.0, 0.43, 0.23), (0.30, 0.40, 0.20),
        (0.53, 0.30, 0.14),
    )):
        make_cone(
            f"RAT_FurSpike_{index}", (x, 0.0, z), scale, 0.25,
            materials["rat_fur_dark"], collection, parent=body,
            rotation=(0.0, math.radians(-12 if x > 0 else 4), 0.0),
            vertices=5,
        )

    neck = make_empty("RAT_Neck", collection, parent=body, location=(-0.58, 0.0, 0.10))
    make_ico(
        "RAT_Head", (0.0, 0.0, 0.0), (0.45, 0.34, 0.35),
        materials["rat_fur"], collection, parent=neck, subdivisions=2,
    )
    make_ico(
        "RAT_Muzzle", (-0.37, 0.0, -0.12), (0.34, 0.20, 0.19),
        materials["rat_skin"], collection, parent=neck, subdivisions=1,
        rotation=(0.0, math.radians(6), 0.0),
    )
    make_ico(
        "RAT_Nose", (-0.66, 0.0, -0.10), (0.10, 0.12, 0.085),
        materials["rat_skin"], collection, parent=neck, subdivisions=1,
    )
    for side, y in (("R", -0.30), ("L", 0.30)):
        make_ico(
            f"RAT_Eye_{side}", (-0.17, y, 0.12), (0.085, 0.055, 0.085),
            materials["eye"], collection, parent=neck, subdivisions=1,
        )
        make_ico(
            f"RAT_EyeBrow_{side}", (-0.18, y * 1.04, 0.22), (0.16, 0.055, 0.065),
            materials["rat_fur_dark"], collection, parent=neck, subdivisions=1,
            rotation=(0.0, math.radians(8), 0.0),
        )

    for side, y in (("R", -0.20), ("L", 0.20)):
        make_ico(
            f"RAT_Ear_{side}", (0.08, y, 0.43), (0.22, 0.14, 0.30),
            materials["rat_fur_light"], collection, parent=neck, subdivisions=1,
            rotation=(0.0, math.radians(-8), math.radians(-8 if side == "R" else 8)),
        )
        make_ico(
            f"RAT_EarInner_{side}", (0.06, y * 1.12, 0.45), (0.15, 0.08, 0.21),
            materials["rat_skin"], collection, parent=neck, subdivisions=1,
        )

    # Open mouth cavity and oversized teeth.
    make_ico(
        "RAT_Mouth", (-0.30, 0.0, -0.24), (0.35, 0.25, 0.095),
        materials["mouth"], collection, parent=neck, subdivisions=1,
    )
    for index, (x, y, length) in enumerate((
        (-0.18, -0.13, 0.18), (-0.34, -0.16, 0.22), (-0.51, -0.13, 0.17),
        (-0.22, 0.15, 0.19), (-0.42, 0.14, 0.20),
    )):
        make_cone(
            f"RAT_UpperTooth_{index}", (x, y, -0.27 - length * 0.08), 0.052, length,
            materials["tooth"], collection, parent=neck,
            rotation=(0.0, math.pi, 0.0), vertices=4,
        )

    jaw = make_empty("RAT_Jaw", collection, parent=neck, location=(-0.18, 0.0, -0.24))
    make_ico(
        "RAT_LowerJaw", (-0.17, 0.0, 0.02), (0.34, 0.20, 0.10),
        materials["rat_skin"], collection, parent=jaw, subdivisions=1,
    )
    for index, (x, y) in enumerate(((-0.16, -0.12), (-0.34, -0.13), (-0.48, -0.10))):
        make_cone(
            f"RAT_LowerTooth_{index}", (x, y, 0.12), 0.045, 0.16,
            materials["tooth"], collection, parent=jaw, vertices=4,
        )

    legs = {}
    for side, y in (("R", -0.27), ("L", 0.27)):
        for part, x in (("Front", -0.43), ("Back", 0.42)):
            upper = make_empty(
                f"RAT_{part}Leg{side}_Upper", collection,
                parent=body, location=(x, y, -0.32),
            )
            make_ico(
                f"RAT_{part}Leg{side}_UpperMesh", (0.0, 0.0, -0.16),
                (0.11, 0.11, 0.20), materials["rat_fur"], collection,
                parent=upper, subdivisions=1,
            )
            lower = make_empty(
                f"RAT_{part}Leg{side}_Lower", collection,
                parent=upper, location=(0.0, 0.0, -0.29),
            )
            make_ico(
                f"RAT_{part}Leg{side}_LowerMesh", (-0.035, 0.0, -0.12),
                (0.10, 0.09, 0.17), materials["rat_fur_light"], collection,
                parent=lower, subdivisions=1,
            )
            make_ico(
                f"RAT_{part}Paw{side}", (-0.10, 0.0, -0.27),
                (0.17, 0.12, 0.09), materials["rat_skin"], collection,
                parent=lower, subdivisions=1,
            )
            for claw_index in range(3):
                make_cone(
                    f"RAT_{part}Claw{side}_{claw_index}",
                    (-0.22, -0.07 + claw_index * 0.07, -0.28),
                    0.032, 0.20, materials["tooth"], collection,
                    parent=lower, rotation=(0.0, math.radians(96), 0.0),
                    vertices=4,
                )
            legs[f"{part}{side}"] = (upper, lower)

    # Segmented tail curling behind the body.
    tail_roots = []
    parent = body
    local_start = (0.68, 0.0, -0.10)
    for index in range(5):
        pivot = make_empty(
            f"RAT_Tail_{index}", collection, parent=parent,
            location=local_start if index == 0 else (0.34, 0.0, -0.02),
        )
        segment(
            f"RAT_TailMesh_{index}", (0.0, 0.0, 0.0), (0.36, 0.0, -0.02),
            0.105 - index * 0.012,
            materials["rat_tail"] if index % 2 == 0 else materials["rat_skin"],
            collection, parent=pivot, vertices=7,
        )
        make_ico(
            f"RAT_TailJoint_{index}", (0.0, 0.0, 0.0),
            (0.115 - index * 0.012, 0.105 - index * 0.012, 0.105 - index * 0.012),
            materials["rat_skin"], collection, parent=pivot, subdivisions=1,
        )
        pivot.rotation_euler.y = 0.10 if index < 3 else -0.10
        tail_roots.append(pivot)
        parent = pivot

    return {
        "root": root,
        "body": body,
        "neck": neck,
        "jaw": jaw,
        "front_r": legs["FrontR"],
        "front_l": legs["FrontL"],
        "back_r": legs["BackR"],
        "back_l": legs["BackL"],
        "tail": tail_roots,
    }


# ---------------------------------------------------------------------------
# Effects and animation
# ---------------------------------------------------------------------------


def make_impact_burst(name, location, collection, material):
    root = make_empty(name, collection, location=location, size=0.08)
    make_ico(
        name + "_Core", (0.0, 0.0, 0.0), (0.11, 0.055, 0.11),
        material, collection, parent=root, subdivisions=1,
    )
    for index in range(8):
        angle = index * math.pi / 4.0
        start = (0.08 * math.cos(angle), 0.0, 0.08 * math.sin(angle))
        end = (
            (0.28 + 0.05 * (index % 2)) * math.cos(angle),
            0.0,
            (0.28 + 0.05 * (index % 2)) * math.sin(angle),
        )
        segment(
            f"{name}_Ray_{index}", start, end, 0.022, material,
            collection, parent=root, vertices=4,
        )
    return root


def capture_rest(animated):
    return {
        name: {
            "location": tuple(obj.location),
            "rotation": tuple(obj.rotation_euler),
            "scale": tuple(obj.scale),
        }
        for name, obj in animated.items()
    }


def key_pose(rest, frame: int, *, location=None, rotation=None, scale=None) -> None:
    """Key a complete pose so the final frame can return cleanly to rest."""
    location = location or {}
    rotation = rotation or {}
    scale = scale or {}
    for name, obj in rest["_objects"].items():
        base = rest[name]
        location_delta = location.get(name, (0.0, 0.0, 0.0))
        rotation_delta = rotation.get(name, (0.0, 0.0, 0.0))
        obj.location = tuple(
            base["location"][index] + location_delta[index]
            for index in range(3)
        )
        obj.rotation_euler = tuple(
            base["rotation"][index] + rotation_delta[index]
            for index in range(3)
        )
        obj.scale = scale.get(name, base["scale"])
        obj.keyframe_insert(data_path="location", frame=frame, group=name)
        obj.keyframe_insert(data_path="rotation_euler", frame=frame, group=name)
        obj.keyframe_insert(data_path="scale", frame=frame, group=name)


def add_camera_keys(camera, frame: int, offset=(0.0, 0.0, 0.0)) -> None:
    base_location = (0.45, -12.5, 3.25)
    camera.location = tuple(base_location[i] + offset[i] for i in range(3))
    camera.keyframe_insert(data_path="location", frame=frame, group="CameraShake")


def animate_scene(scene, player, rat, camera, collections, materials):
    animated = {
        "p_root": player["root"],
        "p_pelvis": player["pelvis"],
        "p_torso": player["torso"],
        "p_head": player["head"],
        "p_arm_r": player["arm_r"],
        "p_fore_r": player["fore_r"],
        "p_hand_r": player["hand_r"],
        "p_sword": player["sword"],
        "p_arm_l": player["arm_l"],
        "p_leg_r": player["leg_r"],
        "p_shin_r": player["shin_r"],
        "p_leg_l": player["leg_l"],
        "p_shin_l": player["shin_l"],
        "r_root": rat["root"],
        "r_body": rat["body"],
        "r_neck": rat["neck"],
        "r_jaw": rat["jaw"],
        "r_front_r": rat["front_r"][0],
        "r_front_rr": rat["front_r"][1],
        "r_front_l": rat["front_l"][0],
        "r_front_lr": rat["front_l"][1],
        "r_back_r": rat["back_r"][0],
        "r_back_rr": rat["back_r"][1],
        "r_back_l": rat["back_l"][0],
        "r_back_lr": rat["back_l"][1],
    }
    for index, tail in enumerate(rat["tail"]):
        animated[f"r_tail_{index}"] = tail

    rest = capture_rest(animated)
    rest["_objects"] = animated

    # Each entry is a clean full-body pose; unused channels fall back to rest.
    poses = [
        # Frame: location offsets, rotation offsets, scale overrides.
        (1, {}, {}, {}),
        (10, {}, {}, {}),
        (16, {
            "p_root": (0.12, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, -0.08, 0.0),
            "p_arm_r": (0.0, 0.10, -0.08, 0.0),
            "p_fore_r": (0.0, -0.20, 0.12, 0.0),
            "p_hand_r": (0.0, 0.15, 0.0, 0.0),
            "p_sword": (0.0, -0.70, 0.0, 0.0),
            "p_leg_r": (0.0, 0.0, 0.18, 0.0),
            "p_leg_l": (0.0, 0.0, -0.14, 0.0),
            "r_body": (0.0, 0.0, 0.04, 0.0),
        }, {}),
        (24, {
            "p_root": (0.34, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, -0.18, 0.0),
            "p_arm_r": (0.0, -0.05, 0.08, 0.0),
            "p_fore_r": (0.0, 0.05, -0.08, 0.0),
            "p_hand_r": (0.0, 0.05, 0.0, 0.0),
            "p_sword": (0.0, -0.30, 0.0, 0.0),
            "p_leg_r": (0.0, 0.0, -0.12, 0.0),
            "p_leg_l": (0.0, 0.0, 0.18, 0.0),
            "r_neck": (0.0, 0.0, 0.14, 0.0),
            "r_jaw": (0.0, 0.0, 0.12, 0.0),
        }, {}),
        (28, {
            "p_root": (0.47, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, 0.10, 0.0),
            "p_arm_r": (0.0, -0.15, 0.08, 0.0),
            "p_fore_r": (0.0, 0.0, 0.0, 0.0),
            "p_hand_r": (0.0, -0.05, 0.0, 0.0),
            "p_sword": (0.0, 1.20, 0.0, 0.0),
            "p_leg_r": (0.0, 0.0, 0.20, 0.0),
            "p_leg_l": (0.0, 0.0, -0.16, 0.0),
            "r_root": (0.30, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, -0.18, 0.0),
            "r_neck": (0.0, 0.0, 0.26, 0.0),
            "r_jaw": (0.0, 0.0, 0.32, 0.0),
            "r_front_r": (0.0, 0.0, 0.22, 0.0),
            "r_front_l": (0.0, 0.0, -0.12, 0.0),
            "r_tail_0": (0.0, 0.0, 0.18, 0.0),
        }, {}),
        (33, {
            "p_root": (0.42, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, 0.04, 0.0),
            "p_arm_r": (0.0, -0.05, 0.05, 0.0),
            "p_fore_r": (0.0, 0.0, 0.0, 0.0),
            "p_hand_r": (0.0, 0.0, 0.0, 0.0),
            "p_sword": (0.0, 0.40, 0.0, 0.0),
            "r_root": (0.42, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, -0.28, 0.0),
            "r_neck": (0.0, 0.0, 0.34, 0.0),
            "r_jaw": (0.0, 0.0, 0.40, 0.0),
            "r_front_r": (0.0, 0.0, 0.36, 0.0),
            "r_front_l": (0.0, 0.0, -0.20, 0.0),
            "r_back_r": (0.0, 0.0, 0.24, 0.0),
            "r_tail_0": (0.0, 0.0, 0.30, 0.0),
            "r_tail_1": (0.0, 0.0, 0.20, 0.0),
        }, {}),
        (39, {}, {}, {}),
        (44, {
            "r_root": (-0.35, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, 0.04, 0.0),
            "r_neck": (0.0, 0.0, -0.12, 0.0),
            "r_jaw": (0.0, 0.0, -0.10, 0.0),
            "r_front_r": (0.0, 0.0, -0.35, 0.0),
            "r_back_r": (0.0, 0.0, 0.30, 0.0),
            "r_tail_0": (0.0, 0.0, -0.22, 0.0),
        }, {}),
        (49, {
            "p_root": (-0.28, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, 0.12, 0.0),
            "p_head": (0.0, 0.0, -0.18, 0.0),
            "p_arm_r": (0.0, 0.30, -0.45, 0.0),
            "p_fore_r": (0.0, -0.18, 0.18, 0.0),
            "r_root": (-1.38, 0.0, 0.04, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, -0.10, 0.0),
            "r_neck": (0.0, 0.0, 0.26, 0.0),
            "r_jaw": (0.0, 0.0, 0.55, 0.0),
            "r_front_r": (0.0, 0.0, 0.48, 0.0),
            "r_front_l": (0.0, 0.0, -0.34, 0.0),
            "r_back_r": (0.0, 0.0, 0.42, 0.0),
            "r_back_l": (0.0, 0.0, -0.28, 0.0),
            "r_tail_0": (0.0, 0.0, -0.42, 0.0),
            "r_tail_1": (0.0, 0.0, -0.30, 0.0),
        }, {}),
        (54, {
            "p_root": (-0.42, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_pelvis": (0.0, 0.0, 0.10, 0.0),
            "p_torso": (0.0, 0.0, 0.24, 0.0),
            "p_head": (0.0, 0.0, -0.26, 0.0),
            "p_arm_r": (0.0, 0.42, -0.62, 0.0),
            "p_fore_r": (0.0, -0.28, 0.28, 0.0),
            "p_leg_r": (0.0, 0.0, 0.22, 0.0),
            "r_root": (-1.48, 0.0, 0.04, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, -0.16, 0.0),
            "r_neck": (0.0, 0.0, 0.34, 0.0),
            "r_jaw": (0.0, 0.0, 0.68, 0.0),
            "r_front_r": (0.0, 0.0, 0.58, 0.0),
            "r_front_l": (0.0, 0.0, -0.42, 0.0),
            "r_back_r": (0.0, 0.0, 0.48, 0.0),
            "r_back_l": (0.0, 0.0, -0.36, 0.0),
            "r_tail_0": (0.0, 0.0, -0.55, 0.0),
            "r_tail_1": (0.0, 0.0, -0.38, 0.0),
            "r_tail_2": (0.0, 0.0, -0.24, 0.0),
        }, {}),
        (61, {
            "p_root": (-0.18, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, 0.06, 0.0),
            "p_arm_r": (0.0, 0.18, -0.18, 0.0),
            "r_root": (-0.90, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_jaw": (0.0, 0.0, 0.20, 0.0),
        }, {}),
        (68, {
            "p_root": (0.02, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, -0.16, 0.0),
            "p_arm_r": (0.0, 0.10, -0.08, 0.0),
            "p_fore_r": (0.0, -0.20, 0.12, 0.0),
            "p_hand_r": (0.0, 0.15, 0.0, 0.0),
            "p_sword": (0.0, -0.70, 0.0, 0.0),
            "r_root": (-0.10, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_neck": (0.0, 0.0, -0.12, 0.0),
        }, {}),
        (73, {
            "p_root": (0.34, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, 0.18, 0.0),
            "p_arm_r": (0.0, -0.15, 0.08, 0.0),
            "p_fore_r": (0.0, 0.0, 0.0, 0.0),
            "p_hand_r": (0.0, -0.05, 0.0, 0.0),
            "p_sword": (0.0, 1.20, 0.0, 0.0),
            "r_root": (0.22, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, -0.22, 0.0),
            "r_neck": (0.0, 0.0, 0.30, 0.0),
            "r_jaw": (0.0, 0.0, 0.42, 0.0),
            "r_front_r": (0.0, 0.0, 0.34, 0.0),
            "r_front_l": (0.0, 0.0, -0.20, 0.0),
            "r_tail_0": (0.0, 0.0, 0.25, 0.0),
        }, {}),
        (80, {
            "p_root": (0.18, 0.0, 0.0, 0.0, 0.0, 0.0),
            "p_torso": (0.0, 0.0, 0.04, 0.0),
            "p_arm_r": (0.0, -0.05, 0.05, 0.0),
            "p_hand_r": (0.0, 0.0, 0.0, 0.0),
            "p_sword": (0.0, 0.40, 0.0, 0.0),
            "r_root": (0.62, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, -0.30, 0.0),
            "r_neck": (0.0, 0.0, 0.38, 0.0),
            "r_jaw": (0.0, 0.0, 0.46, 0.0),
            "r_front_r": (0.0, 0.0, 0.42, 0.0),
            "r_front_l": (0.0, 0.0, -0.30, 0.0),
            "r_back_r": (0.0, 0.0, 0.28, 0.0),
            "r_tail_0": (0.0, 0.0, 0.34, 0.0),
            "r_tail_1": (0.0, 0.0, 0.24, 0.0),
        }, {}),
        (88, {
            "p_root": (-0.10, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_root": (0.18, 0.0, 0.0, 0.0, 0.0, 0.0),
            "r_body": (0.0, 0.0, -0.08, 0.0),
            "r_jaw": (0.0, 0.0, 0.08, 0.0),
        }, {}),
        (95, {}, {}, {}),
    ]
    for pose in poses:
        frame = pose[0]
        channels = pose[1]
        scales = pose[-1] if len(pose) == 4 else pose[2]
        locations = {}
        rotations = {}
        for name, values in channels.items():
            # Compact pose notation: four values are rotation XYZ; six values
            # are location XYZ followed by rotation XYZ.
            if len(values) >= 6:
                locations[name] = tuple(values[:3])
                rotations[name] = tuple(values[3:6])
            else:
                rotations[name] = tuple(values[:3])
        key_pose(rest, frame, location=locations, rotation=rotations, scale=scales)
        if frame in (1, 10, 39, 61, 88, 95):
            add_camera_keys(camera, frame)
        elif frame == 28:
            add_camera_keys(camera, frame, (0.09, 0.0, 0.02))
        elif frame == 30:
            add_camera_keys(camera, frame, (-0.07, 0.0, -0.03))
        elif frame == 33:
            add_camera_keys(camera, frame)
        elif frame == 49:
            add_camera_keys(camera, frame, (-0.08, 0.0, 0.02))
        elif frame == 54:
            add_camera_keys(camera, frame, (0.10, 0.0, -0.03))
        elif frame == 73:
            add_camera_keys(camera, frame, (0.08, 0.0, 0.02))
        elif frame == 76:
            add_camera_keys(camera, frame)
        else:
            add_camera_keys(camera, frame)

    impact_1 = make_impact_burst(
        "FX_SlashImpact", (0.56, -0.26, 1.12),
        collections["FX"], materials["impact"],
    )
    impact_2 = make_impact_burst(
        "FX_BiteImpact", (-1.45, -0.25, 1.16),
        collections["FX"], materials["slime"],
    )
    for burst, keys in (
        (impact_1, (
            (1, 0.001), (26, 0.001), (28, 0.75), (31, 0.001),
            (70, 0.001), (73, 0.90), (76, 0.001), (95, 0.001),
        )),
        (impact_2, ((1, 0.001), (47, 0.001), (50, 0.85), (53, 0.001), (95, 0.001))),
    ):
        for frame, value in keys:
            burst.scale = (value, value, value)
            burst.keyframe_insert(data_path="scale", frame=frame, group="Impact")

    # Acid droplets appear only during the rat's bite.
    drool_root = make_empty(
        "FX_Drool", collections["FX"], parent=rat["neck"],
        location=(-0.55, -0.10, -0.25), size=0.05,
    )
    droplets = []
    for index in range(4):
        obj = make_ico(
            f"FX_Droplet_{index}", (0.0, 0.0, 0.0),
            (0.055 - index * 0.006, 0.04, 0.09),
            materials["slime"], collections["FX"], parent=drool_root,
            subdivisions=1,
        )
        droplets.append(obj)
    for index, obj in enumerate(droplets):
        for frame, location, scale in (
            (1, (0.0, 0.0, 0.0), 0.001),
            (49, (0.0, 0.0, 0.0), 0.001),
            (51 + index, (-0.10 - index * 0.05, -0.02 * index, -0.22 - index * 0.12), 1.0),
            (56 + index, (-0.18 - index * 0.06, -0.03 * index, -0.65 - index * 0.12), 0.65),
            (61, (-0.22 - index * 0.06, -0.03 * index, -0.80 - index * 0.12), 0.001),
            (95, (0.0, 0.0, 0.0), 0.001),
        ):
            obj.location = location
            obj.scale = (scale, scale, scale)
            obj.keyframe_insert(data_path="location", frame=frame, group="Drool")
            obj.keyframe_insert(data_path="scale", frame=frame, group="Drool")

    scene.timeline_markers.new("READY", frame=1)
    scene.timeline_markers.new("PLAYER_WINDUP", frame=16)
    scene.timeline_markers.new("PLAYER_SLASH", frame=28)
    scene.timeline_markers.new("RAT_LUNGE", frame=44)
    scene.timeline_markers.new("RAT_BITE", frame=50)
    scene.timeline_markers.new("PLAYER_COUNTER", frame=73)
    scene.timeline_markers.new("LOOP", frame=95)
    scene.frame_set(HERO_FRAME)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def save_blend(scene) -> None:
    BLEND_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))


def render_hero(scene) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    scene.frame_set(HERO_FRAME)
    if hasattr(scene.render.image_settings, "media_type"):
        scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(HERO_PATH)
    bpy.ops.render.render(write_still=True)


def render_animation(scene) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END
    scene.render.fps = FPS
    if hasattr(scene.render.image_settings, "media_type"):
        scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.ffmpeg.audio_codec = "NONE"
    scene.render.filepath = str(VIDEO_PATH)
    bpy.ops.render.render(animation=True)
    # Leave the saved file configured for PNG stills and the hero pose.
    if hasattr(scene.render.image_settings, "media_type"):
        scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(HERO_PATH)
    scene.frame_set(HERO_FRAME)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))


def build(render_still: bool = True) -> dict[str, object]:
    scene, collections = new_scene()
    configure_scene(scene)
    materials = make_materials()
    camera = build_stage(scene, collections, materials)
    player = build_player(collections["PLAYER"], materials)
    rat = build_rat(collections["RAT"], materials)
    animate_scene(scene, player, rat, camera, collections, materials)
    scene["ARP_description"] = (
        "AI Realms low-poly combat vertical slice: player, Rusty Sword, "
        "Giant Rat, 30 fps side-view loop"
    )
    save_blend(scene)
    if render_still:
        render_hero(scene)
    return {
        "scene": scene.name,
        "objects": len(scene.objects),
        "blend": str(BLEND_PATH),
        "hero": str(HERO_PATH) if render_still else None,
        "frame_range": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
    }


def main() -> None:
    result = build(render_still=os.environ.get("ARP_RENDER_STILL", "1") != "0")


if __name__ == "__main__":
    main()
