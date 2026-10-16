# AutoSWF Vector Animation

**Turn your finished drawings into AdventureQuest Worlds items — without Adobe Animate.**

AutoSWF is a Windows desktop app for AQW item artists. You draw a cel-shaded item in Clip Studio
Paint, as usual. AutoSWF opens the file with its layers and does the rest: it converts the art into clean
vector shapes that look hand-made in Animate, finds the parts with AI (eyes, hair locks, ears,
accessories), animates them Flash-style (blinking eyes, swaying hair, light cloth physics), wires AQW's
color customization, shows the item on the AQW body, and exports a SWF ready for the game.

> **Status: early development.** Phase 1 (helms and morph helms) is being built. Done so far: the SWF engine
> (AQW-valid helm export) and the preview of a helm on the AQW male and female bodies.

## Why

Making an AQW item today means drawing it, then redrawing every line as vector art in Adobe Animate and
animating it by hand. That second step is slow, and Adobe discontinued Animate on March 1, 2026.
AutoSWF replaces it.

## Planned features — Phase 1: helms

- **Open your files directly:** Clip Studio Paint `.clip` and `.psd`, keeping your layers by painting
  pass (line art, flat colors, shadow, occlusion shadow, details, light).
- **Vectorization like hand-made Animate art:** brush-like line art with varying width, flat color
  regions without gaps, cel shading as separate shapes, few nodes.
- **AI part detection:** eyes, hair locks, ears, horns, accessories, back hair. You confirm or fix
  everything with a click.
- **Flash-style animation presets:** Blink (same pattern as AQW's own eyes), Sway with spring physics,
  Twitch and Pulse, all editable on a 24 fps timeline.
- **AQW color custom built in:** hair follows the player's Hair color, skin follows Skin, irises follow
  Eye, and other areas can follow Base, Trim or Accessory. Shadow and light layers become the game's
  Dark, Darker and Light tones.
- **Preview on the AQW body:** male and female, playing the game's own animations, with any player
  colors.
- **Export:** normal helms and morph helms (a whole new head with its own face), optional back hair,
  optional male/female variants. Every file is checked against the AQW format before it is saved.

## Roadmap

| Phase | Items |
|---|---|
| 1 | Helms and morph helms *(in progress)* |
| 2 | Armors (all 11 body parts, male and female) |
| 3 | Capes and weapons, plus **AI FX from a text prompt** (e.g. "electric energy running from the guard to the blade tip") |
| 4 | Pets |
| Later | Native Procreate, Krita, Illustrator, Animate and SWF importers |

Phase 1 is built in six steps: SWF engine → preview window → import and vectorization → parts and
color custom → animation presets → the full app (`.exe`).

## For developers

Requirements: Windows 10/11, Python 3.12 or newer.

```bash
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

Documentation:

  — includes the AQW item format, verified against live game files.
  merged)

### Try it

```bash
.venv/Scripts/python -m autoswf download-aqw
.venv/Scripts/python -m autoswf demo-helm cache/demo.swf
.venv/Scripts/python -m autoswf preview cache/demo.swf
```

`download-aqw` fetches the current AQW game client and one armor (for the preview body) from AQW's public server.
AQW files are only downloaded when you ask, stay on your computer (in `cache/`), and are never committed or shared.
Other commands: `inspect FILE` describes a SWF, `render FILE --class NAME --out OUT.png` renders one class, and
`fidelity` compares the renderer with JPEXS FFDec on official items.

## Disclaimer

AutoSWF is an independent fan-made tool. It is not affiliated with or endorsed by Artix Entertainment.
AdventureQuest Worlds and all of its art belong to Artix Entertainment. This repository contains no AQW
game files: the app only downloads reference files from AQW's public servers on the user's own computer,
for preview, and never redistributes them.
