# AutoSWF Vector Animation

**Turn your finished drawings into AdventureQuest Worlds items — without Adobe Animate.**

AutoSWF is a Windows desktop app for AQW item artists. You draw a cel-shaded item in Clip Studio
Paint, as usual. AutoSWF opens the file with its layers and does the rest: it converts the art into clean
vector shapes that look hand-made in Animate, finds the parts with AI (eyes, hair locks, ears,
accessories), animates them Flash-style (blinking eyes, swaying hair, light cloth physics), wires AQW's
color customization, shows the item on the AQW body, and exports a SWF ready for the game.

> **Status: early development.** Phase 1 (helms and morph helms) is being built. Done so far: the SWF engine
> (AQW-valid helm export), the preview of a helm on the AQW male and female bodies, and the conversion of a layered
> drawing (`.clip`, `.psd`, `.png`) into an animated vector helm split into parts (blinking eyes, swaying hair),
> with AQW color custom.

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

### Try it

```bash
.venv/Scripts/python -m autoswf download-aqw
.venv/Scripts/python -m autoswf demo-helm cache/demo.swf
.venv/Scripts/python -m autoswf preview cache/demo.swf
```

### Convert a drawing

```bash
.venv/Scripts/python -m autoswf template cache/template.psd --clip cache/template.clip
.venv/Scripts/python -m autoswf convert my-helm.clip -o cache/my-helm.swf --report
.venv/Scripts/python -m autoswf preview cache/my-helm.swf
```

`template` writes a 2000 x 2000 canvas with the AQW male and female heads on locked `AQW Guide` layers and empty
layers for each painting pass; art drawn on it lands on the head exactly (the `.clip` version is experimental — use the
`.psd` if Clip Studio Paint does not open it). `convert` finds each layer's role from its name:

| Role | Layer names it recognizes (English, Portuguese, Japanese) |
|---|---|
| Line | Line, Lineart, Ink, Outline, Linha, Contorno, 線画 |
| Flat colors | Flats, Base, Colors, Fill, Cores chapadas, Cores, 下塗り, ベタ |
| Shadow | Shadow, Shade, Sombra, 影 |
| Occlusion shadow | Occlusion, AO, Oclusão, Sombra 2, Sombra escura |
| Light | Light, Highlight, Glow, Luz, Brilho, ハイライト |
| Details | Details, Detalhes, Extras |
| Not used | Paper, Background, Sketch, Rascunho, Reference, `AQW Guide …`, hidden layers |

Folders named like a pass give their role to the layers inside; other folders are treated as parts (Hair, Face…).
Useful options: `--role "Layer 1=line"` (set a role by hand), `--align SCALE,X,Y[,DEG]` (where the head is, for
drawings not made on the template; DEG turns the drawing clockwise onto the head, so a drawing that is turned
clockwise needs a negative DEG), `--detail 0-100` (simpler or more faithful shapes, default 50), `--gradient Light`
(an SWF gradient instead of flat steps for a soft layer), `--separate-tones` (shadows and lights as their own shapes),
`--list` (only show the layers and roles) and `--report` (measure the vector art against the drawing).

### Parts and color custom

`convert` finds the helm's parts — face, ears, eyes (white, iris, pupil, highlight, lid), brows, mouth, nose, the hair
and each lock, horns, the helm itself and accessories — and lists them with the point (in drawing pixels) where each
one is. Each part becomes its own symbol, ready to be animated, and what is behind the parts that move (eyes, locks,
ears, accessories) is filled in, so nothing opens up when they move. Folders named after parts (Hair, Cabelo, Olhos,
Eyes, Chapéu, Accessories, Back hair…) are used as they are; a face folder says what the skin color is. A part painted
in several folders (hair behind and in front of the face) keeps each folder's place: the extra pieces are named after
their folder, like `Hair (Bangs)`.

Hair follows the player's Hair color, skin follows Skin and irises follow Eye; shadow, occlusion and light layers become
the game's Dark, Darker and Light tones there (the game draws those with its own fixed tones). Everything else keeps
the colors you painted, unless you give a part a color slot.

To fix a part, write `my-helm.parts.json` next to the drawing (or pass `--parts FILE`), using the points `convert`
printed or `--parts-image` shows:

```json
{
  "assign": [{"at": [512, 300], "part": "Lock 2"}, {"at": [400, 310], "part": "Eye L", "piece": "iris"}],
  "cuts": [[[100, 200], [140, 260]]],
  "colors": {"Helm": "Base", "Accessory 1": "Trim", "Brow L": "none"}
}
```

`assign` puts the region under a point into a part (Face, Ear L/R, Nose, Mouth, Brow L/R, Eye L/R, Hair, Lock N,
Back hair, Horn L/R, Helm, Accessory N); `cuts` split regions along a line; `colors` give a part a slot (Skin, Hair, Eye,
Base, Trim, Accessory or `none`; a slot for Hair applies to the locks too, and eye whites, pupils, highlights, lids and
outlines always keep their colors). More options: `--color "Helm=Base"` (same as `colors`), `--parts-image parts.png` (an
image of the parts found), `--morph` (warn when the male or female base head shows around a morph helm) and
`--no-parts` (one static shape set, no color custom). To see the result with other player colors:
`preview my-helm.swf --player-color Hair=C02030 --player-color Skin=80C0FF`.

### Animation

`convert` animates the helm the way Flash items in AQW are animated: every moving part becomes its own looping clip.
By default the eyes blink and the hair locks (and any back hair) sway; `--no-animate` writes a still helm.

- **Blink** (eyes) repeats AQW's own eye clip frame for frame: an 87-frame loop where, on frames 11-12, the eye white and
  iris disappear and the upper lid line comes down over the skin, then on frames 13-16 the eye comes back squashed while
  the lid goes up. Settings: `interval` (loop length, default 87 frames), `speed` (1 = AQW's speed; 0.5 to 2) and
  `double` (blink twice).
- **Sway** (hair locks, ears, ribbons, feathers, soft cloth, back hair) runs a chain of springs from the part's root to
  its tip, solved into a seamless loop; neighbouring locks follow each other a few frames apart, like a wave. Each part
  turns about its root and bends (a Flash shape tween). Settings: `stiffness` (0 floppy to 1 stiff, default 0.5),
  `amplitude` (degrees at the tip, default 12), `wind` (0 to 1, default 0.3), `delay` (frames between neighbouring
  parts, default 4) and `length` (frames per loop, default 48 = 2 seconds).
- **Twitch** (ears and similar): a quick turn that settles, once per loop. Settings: `angle` (degrees, default 10),
  `every` (loop length, default 72) and `settle` (frames, default 12).
- **Pulse** (glowing eyes, gems): brightness (and optionally alpha) goes up and down. Settings: `length` (default 48),
  `brightness` (-1 to 1, default 0.35) and `alpha` (the lowest alpha, default 1).

Only parts with their hidden area filled can move (eyes, locks, ears, accessories, back hair), so nothing opens up
behind them; Pulse works on any part. Options: `--animate "Ear L=Twitch"` (a preset for a part, or `none`), and
`--blink`, `--sway`, `--twitch`, `--pulse KEY=VALUE` (a setting for every part that uses that preset), e.g.
`--sway amplitude=20 --blink double=on`. The same choices, and keyframes you edit by hand, go in `my-helm.anim.json`
next to the drawing (or `--anim FILE`); frames count from 1, as in Animate:

```json
{
  "presets": {"Sway": {"amplitude": 15, "length": 72}},
  "parts": {"Ear L": "Twitch", "Lock 2": "none", "Accessory 1": {"preset": "Pulse", "brightness": 0.5}},
  "keys": [{"part": "Lock 3", "frame": 12, "rotation": 6}]
}
```

A keyframe sets any of `x`, `y` (head units), `rotation` (degrees), `scale_x`, `scale_y`, `alpha`, `brightness` and
`bend` (0 to 1) of one frame, on top of what the preset made; `"tween": true` blends it into the next keyframe. AQW
plays items at 24 frames per second, and so does `preview`.

`download-aqw` fetches the current AQW game client and one armor (for the preview body) from AQW's public server.
AQW files are only downloaded when you ask, stay on your computer (in `cache/`), and are never committed or shared.
Other commands: `inspect FILE` describes a SWF, `render FILE --class NAME --out OUT.png` renders one class, and
`fidelity` compares the renderer with JPEXS FFDec on official items.

## Disclaimer

AutoSWF is an independent fan-made tool. It is not affiliated with or endorsed by Artix Entertainment.
AdventureQuest Worlds and all of its art belong to Artix Entertainment. This repository contains no AQW
game files: the app only downloads reference files from AQW's public servers on the user's own computer,
for preview, and never redistributes them.
