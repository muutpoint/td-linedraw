# linedraw for TouchDesigner

A real-time GLSL port of [LingDong-/linedraw](https://github.com/LingDong-/linedraw): wobbly contours plus hatching that looks like a pen-plotter drawing, built as one component with custom parameters.

It runs in two modes:

| Mode | Input | What it uses |
|---|---|---|
| **Image** | any TOP wired into the component | luminance only, like the original |
| **Scene** | a Render TOP picked in the parameters | depth, normals and object IDs from an internal G-buffer render, plus the beauty pass for tone |

## Image TOP or render-aware?

Render-aware gives better results in a 3D scene, so the component does both.

* **Cleaner contours.** In Image mode, edges come from brightness changes. A grey sphere against a grey sky loses its outline, and textures and lighting add noise. Scene mode draws silhouettes from depth breaks, creases from normal changes, and boundaries from object-ID changes. These lines stay clean whatever the lighting is.
* **Hatching that sticks to the surface.** Screen-space hatching stays fixed on screen while objects move under it (the "shower door" effect). With **Hatch Space = Surface** or **UV**, the lines are attached to the geometry so they rotate and move with it. **Surface LOD** keeps line spacing on screen close to *Hatch Size*, so distant or grazing surfaces don't fill in solid black.
* **Separate tone control.** Hatch density can come from the render, from a virtual key light on the normals (*Tone From = Key Light*), or from both combined.

In Scene mode, image edges from the beauty pass are still added (toggle *Image Edges*), so textures still get some contours.

## Install

TouchDesigner 2023.11000 or newer is needed (Vulkan GLSL and sequence parameters).

1. Create a **Text DAT**, paste in `build_linedraw.py`, then right-click it and choose **Run Script**.
   (Or in the Textport: `exec(open(r'C:/path/build_linedraw.py').read())`.)
2. The script creates:
   * `linedraw1`: the component. Wire any TOP into it.
   * `linedraw_demo`: a small scene with a spinning torus, a box, a sphere and a floor. It contains one copy in Scene mode (surface-locked hatching) and one in Image mode on the same render, so you can compare them.
   To skip either one, set `BUILD_COMPONENT` / `BUILD_DEMO` at the top of the script.
3. To use Scene mode on your own scene: set **Source = Scene** and drag your Render TOP onto **Render TOP**. The camera, geometry and resolution are copied from it. *Camera / Geometry (override)* let you choose something different.

Right-click the component and use **Save Component .tox** to reuse it.

## How it works

```
in1 / Render TOP ─► tone_src ─► levels (1x1 auto-contrast)
                         └────► prep (tone, levels, gamma; key-light shading in Scene mode)
                                  ├─► edges (Canny-style NMS + G-buffer silhouettes/creases/ids, at Design Width / Simplify)
                                  │     └─► hyst (N passes: hysteresis + speck removal)
                                  │           └─► chords (straight segment per 8x8 block = linedraw's point skipping)
                                  └─────────────────► ink (hatching layers + contour strokes + composite) ─► out1
gbuf_render (Override Material = gbuf_mat GLSL MAT, 3 x 32-bit buffers) ─► g0/g1/g2 switches (dummy in Image mode)
```

* **Hatching** follows linedraw's rules. The image is split into *Hatch Size* cells. Below 0.565 tone a horizontal line is drawn, below 0.25 a "/" diagonal is added, and below 0.063 a second horizontal is added. Each line gets its own Perlin wobble and the same slight slant as the original. Lines are drawn analytically, so stroke width stays constant and smooth at any resolution. **Cell Quantize = 1** makes segments start and stop on the cell grid, which is the blocky plotter look.
* **Contours** are drawn as strokes along the edge pixels at sub-pixel positions. **Angular** style replaces each simple curve with one straight chord per *Chord Length* block, which copies linedraw keeping only every 8th point. **Sketch Passes** draws the contours again with different displacement and jitter; the original traced every edge twice.
* All sizes are in **design pixels** (1 unit = 1 px of a *Design Width*-wide image; linedraw used 1024). The look doesn't change when the output resolution does. **Output Resolution = Custom** renders crisp lines larger than the source.

## Parameters

**Linedraw**: Source, Render TOP, Camera/Geometry overrides, Tone Image (scene), Output (Ink on Paper / Ink Only with alpha / Channels R=contour G=hatch B=tone / debug views for tone, edges, normals, depth, IDs, hatch coords), Output Resolution, Design Width, Antialias Width, Seed, **Boil Rate** (re-rolls the wobble N times per second for a hand-animated look).

**Tone**: Auto Levels and Auto Cutoff (PIL `autocontrast(10)` like the original), Black/White Point, Gamma, Contrast, Brightness, Invert. Scene only: Tone From, Key Light Dir (view space), Ambient, Hatch Background, Clip Hatch to Geometry.

**Hatch**: Draw, Opacity, Hatch Size, Hatch Weight, Cell Quantize, Wobble, Wobble Freq, Weight Variation (pen pressure), Gaps (pen skipping). Surface: Hatch Space (Screen / Surface triplanar / UV), Triplanar Space (object/world), Surface Spacing, UV Spacing, Surface LOD, LOD Density. **Layers 1–4**: on/off, threshold, angle, phase, spacing multiplier. Layers 1–3 match linedraw; layer 4 is an optional cross-hatch.

**Contours**: Draw, Opacity, Weight, Style (Smooth / Angular), Chord Length, Contour Simplify. Image edges: Low/High Threshold, Hysteresis Passes, Speck Removal. Scene edges: Silhouettes/Depth (+ threshold), Creases (+ angle), Object Boundaries. Sketchiness: Sketch Passes, Displacement (+ freq), Jitter (+ freq), Jitter Angularity.

**Look**: Ink Color, Paper Color (premultiplied output; set paper alpha to 0 for ink over transparency), Paper Grain.

## Tips

* For video, the default is still screen-space hatching, which matches the original. Turn on **Boil Rate** (8–12 fps) for hand-drawn flicker. In Scene mode, use **Surface** for hatching that moves with objects.
* When the contours in Scene mode are too busy, turn off *Image Edges* to keep only the geometric lines.
* Most of the cost is in `ink`. Use fewer *Sketch Passes*, turn off Layer 4, or render at a lower Output Resolution to speed it up.

## Testing and caveats

* I couldn't open TouchDesigner here. The shaders were compiled and run in a GLSL 4.5 emulation of the GLSL TOP / GLSL MAT environment (on sample images, a ray-cast G-buffer, and meshes rendered through `gbuf_mat`). The builder ran against a mock of TD's Python API, and the operator parameter names were checked against the current Derivative docs. If something fails on first run, the error shows on the node (and in its docked info DAT) or in the Textport.
* Object IDs come from a hash of each Geometry COMP's world transform plus the instance ID. Two objects with exactly the same transform get the same ID, but depth and normal edges still separate them.
* Scene mode uses the first camera of the Render TOP. The G-buffer takes its aspect from the Render TOP's resolution.
* The output is raster only. The original's SVG export and stroke-order optimisation for plotters aren't reproduced.

## Files

| File | What it is |
|---|---|
| `build_linedraw.py` | The builder. Paste into a Text DAT and run it to create the `linedraw1` component and the `linedraw_demo` scene. All shaders are embedded in it. |
| `shaders/ld_prep.glsl` | Tone prep: levels, gamma, contrast; key-light shading from normals in Scene mode. |
| `shaders/ld_levels.glsl` | 1x1 auto-contrast pass (the original's `autocontrast`). |
| `shaders/ld_edges.glsl` | Canny-style edges with non-max suppression, plus G-buffer silhouettes, creases and object-ID boundaries. |
| `shaders/ld_hyst.glsl` | Hysteresis passes and speck removal. |
| `shaders/ld_chords.glsl` | One straight chord per block for the Angular contour style. |
| `shaders/ld_ink.glsl` | Hatching layers, contour strokes and the final composite. |
| `shaders/ld_gbuffer_vert.glsl`, `ld_gbuffer_frag.glsl` | The GLSL MAT that renders depth, normals and object IDs for Scene mode. |
| `images/` | Comparison renders used to check the port against the original. |
| `third_party/LICENSE-linedraw.txt` | MIT licence for Lingdong Huang's linedraw. |

The `shaders/` files are readable copies of what the builder embeds. Edit the builder if you want a change to stick.

## Credits

Original algorithm: **linedraw** by Lingdong Huang, MIT License.

> Copyright (c) 2017 Lingdong Huang
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

TouchDesigner port: © Ro Mayz 2026. All rights reserved.
