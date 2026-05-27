# Auryn assets

`Auryn.svg` is the source of truth for the application icon: a geometric
**"A" monogram** (its counter is a subtle play triangle — a quiet nod to
music) on a premium deep-teal → aqua tile that matches the in-app accent. The
PNG sizes (`Auryn_16.png`, `Auryn_32.png`, `Auryn_48.png`, `Auryn_256.png`)
and the multi-size Windows icon (`Auryn.ico`) are exported from it. These are
the files referenced by the `.deb` / `.rpm` packaging and the Windows spec.

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

## Re-exporting the Windows icon

`Auryn.ico` bundles several sizes for the Windows `.exe` (the PyInstaller spec
picks it up automatically when present). Regenerate it after editing the SVG,
for example with Pillow:

```bash
python3 - <<'PY'
import cairosvg
from PIL import Image
cairosvg.svg2png(url="Auryn.svg", write_to="Auryn_256.png", output_width=256, output_height=256)
Image.open("Auryn_256.png").convert("RGBA").save(
    "Auryn.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
PY
```

`Auryn_ui.png` is a screenshot of the running application used in the top-level
`README.md`. Replace it with a fresh capture when the UI changes noticeably.
