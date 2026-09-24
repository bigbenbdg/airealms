# AI Realms 3D combat prototype

This directory contains the first Blender combat vertical slice for AI Realms.
It is a visual and animation prototype, not yet a production game-asset export.

## Prototype scope

- Low-poly player inspired by `assets/player/player.png`
- Low-poly Giant Rat inspired by `assets/monsters/giant_rat.png`
- Corroded Rusty Sword test weapon
- Fixed side-view, slightly three-quarter camera
- 3.2-second looping fight at 30 fps

The fight contains a player slash, impact reaction, Giant Rat lunge and bite,
acid droplets, a player recoil, and a counter slash.

## Files

- `source/player_vs_giant_rat.blend` — editable Blender source
- `previews/player_vs_giant_rat_hero.png` — 1280×720 impact-frame still
- `previews/player_vs_giant_rat_30fps.mp4` — 1280×720, 30 fps, H.264 preview

## Regenerate

From the repository root:

```powershell
blender --background --python scripts/make_combat_prototype.py
```

The procedural scene uses a piece-based joint hierarchy so silhouette and timing
can be approved quickly. The final roster should convert those conventions to
armatures/GLB only after the style is accepted. Original player and monster PNGs
are used as references and are never modified by the generator.
