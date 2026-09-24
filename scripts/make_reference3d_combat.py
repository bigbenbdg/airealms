"""Test the reference-driven 3D player against the modeled Giant Rat.

Run after make_player_reference_3d.py has been built successfully. This is a
combat-layout prototype; it uses the real meshes and transform rig, not image
cards.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import make_combat_prototype as combat  # noqa: E402
import make_player_reference_3d as reference  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "3d" / "reference3d" / "combat"
BLEND_PATH = OUT_DIR / "player_vs_giant_rat_3d.blend"
HERO_PATH = OUT_DIR / "player_vs_giant_rat_3d_hero.png"
VIDEO_PATH = OUT_DIR / "player_vs_giant_rat_3d_30fps.mp4"
SCENE_NAME = "AI_REALMS_REFERENCE3D_COMBAT"
FPS = 30
FRAME_END = 95
HERO_FRAME = 28


def add_collection(scene, key):
    collection = bpy.data.collections.get(reference.base.PREFIX + "REFERENCE3D_" + key)
    if collection is None:
        collection = bpy.data.collections.new(reference.base.PREFIX + "REFERENCE3D_" + key)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def key_object(obj, frame, base_location, base_rotation, base_scale, location=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1)):
    obj.location = tuple(base_location[i] + location[i] for i in range(3))
    obj.rotation_euler = tuple(base_rotation[i] + rotation[i] for i in range(3))
    obj.scale = tuple(base_scale[i] * scale[i] for i in range(3))
    obj.keyframe_insert(data_path="location", frame=frame, group="Reference3DCombat")
    obj.keyframe_insert(data_path="rotation_euler", frame=frame, group="Reference3DCombat")
    obj.keyframe_insert(data_path="scale", frame=frame, group="Reference3DCombat")


def animate(scene, player, rat, camera, collections, materials):
    player_root = player["root"]
    rat_root = rat["root"]
    player_root.location = (-1.22, 0.0, 0.0)
    rat_root.location = (1.12, 0.0, 0.0)
    player_base = tuple(player_root.location)
    rat_base = tuple(rat_root.location)
    player_rot = tuple(player_root.rotation_euler)
    rat_rot = tuple(rat_root.rotation_euler)
    player_scale = tuple(player_root.scale)
    rat_scale = tuple(rat_root.scale)
    sword = bpy.data.objects.get(reference.base.PREFIX + "Reference_Sword")
    sword_base_rot = tuple(sword.rotation_euler) if sword else (0.0, 0.0, 0.0)
    sword_base_loc = tuple(sword.location) if sword else (0.0, 0.0, 0.0)
    sword_base_scale = tuple(sword.scale) if sword else (1.0, 1.0, 1.0)

    poses = [
        (1, (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        (10, (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        (16, (0.12, 0, 0), (0, -0.08, -0.02), (1, 1, 1), (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0.65, 0)),
        (24, (0.38, 0, 0), (0, -0.16, -0.04), (1, 1, 1), (0.08, 0, 0), (0, 0.05, 0.02), (1.02, 1, 1), (0, 0.25, 0)),
        (28, (0.62, 0, 0.02), (0, 0.08, -0.05), (1.04, 1, 0.98), (0.22, 0, 0.02), (0, -0.14, 0.04), (1.05, 1, 0.98), (0, -1.25, 0)),
        (33, (0.44, 0, 0), (0, 0.03, -0.02), (1, 1, 1), (0.34, 0, 0), (0, -0.20, 0.03), (1.04, 1, 1), (0, -0.45, 0)),
        (39, (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        (44, (0, 0, 0), (0, 0, 0), (1, 1, 1), (-0.18, 0, 0.03), (0, 0.10, 0.02), (1.04, 1, 0.98), (0, 0, 0)),
        (49, (-0.24, 0, 0.02), (0, 0.14, 0.04), (0.98, 1, 1.02), (-1.08, 0, 0.06), (0, -0.05, -0.03), (1.10, 1, 1), (0, 0, 0)),
        (54, (-0.40, 0, 0.03), (0, 0.20, 0.06), (0.96, 1, 1.04), (-1.18, 0, 0.05), (0, -0.12, -0.04), (1.12, 1, 1), (0, 0, 0)),
        (61, (-0.16, 0, 0), (0, 0.08, 0.02), (1, 1, 1), (-0.60, 0, 0.02), (0, -0.04, -0.01), (1.04, 1, 1), (0, 0, 0)),
        (68, (0.08, 0, 0), (0, -0.12, -0.02), (1, 1, 1), (-0.18, 0, 0), (0, 0.05, 0.01), (1, 1, 1), (0, 0.65, 0)),
        (73, (0.50, 0, 0.02), (0, 0.08, -0.04), (1.04, 1, 0.98), (0.26, 0, 0), (0, -0.16, 0.03), (1.06, 1, 0.98), (0, -1.25, 0)),
        (80, (0.30, 0, 0), (0, 0.03, -0.02), (1, 1, 1), (0.48, 0, 0), (0, -0.22, 0.04), (1.04, 1, 1), (0, -0.45, 0)),
        (88, (-0.06, 0, 0), (0, 0, 0), (1, 1, 1), (0.10, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        (95, (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0), (0, 0, 0), (1, 1, 1), (0, 0, 0)),
    ]
    for frame, pl, pr, ps, rl, rr, rs, sr in poses:
        key_object(player_root, frame, player_base, player_rot, player_scale, pl, pr, ps)
        key_object(rat_root, frame, rat_base, rat_rot, rat_scale, rl, rr, rs)
        if sword:
            key_object(sword, frame, sword_base_loc, sword_base_rot, sword_base_scale, (0, 0, 0), sr, (1, 1, 1))

        # Light camera shake on impacts.
        if frame in (1, 10, 39, 61, 88, 95):
            camera.location = (0.55, -10.0, 3.05)
        elif frame == 28:
            camera.location = (0.65, -10.0, 3.08)
        elif frame == 49:
            camera.location = (0.47, -10.0, 3.07)
        elif frame == 54:
            camera.location = (0.65, -10.0, 3.02)
        elif frame == 73:
            camera.location = (0.63, -10.0, 3.08)
        else:
            camera.location = (0.55, -10.0, 3.05)
        camera.keyframe_insert(data_path="location", frame=frame, group="Reference3DCamera")

    # Rat jaw/neck accents make the lunge read even at thumbnail size.
    neck = rat.get("neck")
    jaw = rat.get("jaw")
    if neck:
        for frame, value in ((1, 0), (44, 0.10), (49, 0.28), (54, 0.36), (61, 0.08), (95, 0)):
            neck.rotation_euler.y = value
            neck.keyframe_insert(data_path="rotation_euler", frame=frame, group="Reference3DRat")
    if jaw:
        for frame, value in ((1, 0), (44, 0.12), (49, 0.48), (54, 0.62), (61, 0.10), (95, 0)):
            jaw.rotation_euler.y = value
            jaw.keyframe_insert(data_path="rotation_euler", frame=frame, group="Reference3DRat")

    # Small 3D impact accents.
    gold = reference.base.make_material("Reference3D_GoldFX", "#FFD166", emission=3.0, roughness=0.3)
    slime = reference.base.make_material("Reference3D_SlimeFX", "#A8FF28", emission=2.5, roughness=0.3)
    slash = reference.base.make_impact_burst("Reference3D_SlashFX", (0.20, -0.25, 1.20), collections["FX"], gold)
    bite = reference.base.make_impact_burst("Reference3D_BiteFX", (-0.55, -0.25, 1.00), collections["FX"], slime)
    for burst, keys in (
        (slash, ((1, .001), (26, .001), (28, .65), (31, .001), (70, .001), (73, .78), (76, .001), (95, .001))),
        (bite, ((1, .001), (47, .001), (50, .70), (53, .001), (95, .001))),
    ):
        for frame, value in keys:
            burst.scale = (value, value, value)
            burst.keyframe_insert(data_path="scale", frame=frame, group="Reference3DFX")

    scene.timeline_markers.new("READY", frame=1)
    scene.timeline_markers.new("PLAYER_STRIKE", frame=28)
    scene.timeline_markers.new("RAT_BITE", frame=50)
    scene.timeline_markers.new("PLAYER_COUNTER", frame=73)
    scene.timeline_markers.new("LOOP", frame=95)
    scene.frame_set(HERO_FRAME)


def render_hero(scene, camera):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scene.frame_set(HERO_FRAME)
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(HERO_PATH)
    bpy.ops.render.render(write_still=True)


def render_animation(scene, camera):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scene.frame_start = 1
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
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(HERO_PATH)
    scene.frame_set(HERO_FRAME)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))


def build(render=True):
    reference.remove_scene(SCENE_NAME)
    scene, collections = reference.new_scene()
    scene.name = SCENE_NAME
    reference.configure_scene(scene)
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    collections["RAT"] = add_collection(scene, "RAT")
    collections["FX"] = add_collection(scene, "FX")
    player_materials = reference.helpers.materials()
    player_materials["ground"] = reference.base.make_material("Reference3D_Ground", "#25282F", roughness=0.95)
    player_materials["backdrop"] = reference.base.make_material("Reference3D_Backdrop", "#25282F", roughness=1.0)
    reference.build_reference_planes(collections["REFERENCE"])
    reference.helpers.build_stage(scene, collections, player_materials)
    player = reference.build_player(collections["PLAYER"], player_materials)
    rat_materials = combat.make_materials()
    rat = combat.build_rat(collections["RAT"], rat_materials)
    camera = scene.camera
    if camera is None:
        camera = next(obj for obj in collections["STAGE"].objects if obj.type == "CAMERA")
        scene.camera = camera
    camera.location = (0.55, -10.0, 3.05)
    camera.rotation_euler = (Vector((0.0, 0.0, 1.30)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 55
    animate(scene, player, rat, camera, collections, player_materials)
    scene["Reference3DCombat_description"] = "True 3D reference-driven player + modeled Giant Rat combat layout"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    if render:
        render_hero(scene, camera)
    return {
        "scene": scene.name,
        "objects": len(scene.objects),
        "blend": str(BLEND_PATH),
        "hero": str(HERO_PATH) if render else None,
        "video": str(VIDEO_PATH),
    }


if __name__ == "__main__":
    built = build(render=True)
    if os.environ.get("REF3D_RENDER_VIDEO", "0") == "1":
        render_animation(bpy.context.scene, bpy.context.scene.camera)
