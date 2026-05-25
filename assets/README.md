# Auryn assets

`Auryn.svg` is the source of truth for the application icon. The PNG sizes
(`Auryn_16.png`, `Auryn_32.png`, `Auryn_48.png`, `Auryn_256.png`) are exported
from it and are the files referenced by the `.deb` / `.rpm` packaging and the
Windows spec.

## Re-exporting the PNG sizes

After editing `Auryn.svg`, regenerate the PNGs so packaging stays in sync. Any
SVG rasterizer works; for example with `cairosvg`:

```bash
pip install cairosvg
for s in 16 32 48 256; do
  cairosvg Auryn.svg -W $s -H $s -o Auryn_${s}.png
done
```

Equivalent with `rsvg-convert` (librsvg) or Inkscape:

```bash
for s in 16 32 48 256; do rsvg-convert -w $s -h $s Auryn.svg -o Auryn_${s}.png; done
# or
for s in 16 32 48 256; do inkscape Auryn.svg -w $s -h $s -o Auryn_${s}.png; done
```

`Auryn_ui.png` is a screenshot of the running application used in the top-level
`README.md`. Replace it with a fresh capture when the UI changes noticeably.
