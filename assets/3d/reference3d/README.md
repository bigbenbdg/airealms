# Reference-driven 3D player

This folder contains the true-3D player reconstruction retry based on the
additional reference screenshots supplied by the user:

- `Screenshot 2026-09-24 173208.png` — full-body three-quarter view
- `Screenshot 2026-09-24 173230.png` — full-body front view
- `Screenshot 2026-09-24 173246.png` — full-body back view
- `Screenshot 2026-09-24 173316.png` — face and chest close-up

The reference images are loaded into the Blender scene as hidden viewport
planes. They are construction references only; the player is built from
low-poly geometry, materials, and a transform hierarchy.

## Outputs

- `source/player_reference_3d.blend` — player model and validation scene
- `previews/player_front.png`
- `previews/player_three_quarter.png`
- `previews/player_side.png`
- `previews/player_back.png`
- `previews/player_face.png`
- `previews/reference_comparison.png` — source/reference versus model sheet
- `combat/player_vs_giant_rat_3d.blend` — true-3D combat layout with the existing Giant Rat
- `combat/player_vs_giant_rat_3d_hero.png`
- `combat/player_vs_giant_rat_3d_30fps.mp4` — 95-frame combat test loop

## Regeneration

```powershell
python scripts/make_player_reference_3d.py
blender --background --python scripts/make_reference3d_combat.py
```

This is still a stylized low-poly prototype. The next production step would be
adding more layered armor plates, cleaner coat topology, refined facial/hair
geometry, and a real armature/GLB export after the silhouette is approved.
