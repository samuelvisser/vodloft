"""Frame screenshots the way the WireLoft README does: rounded corners and a soft blue-grey border."""
import sys
from PIL import Image, ImageDraw

BORDER = 20
RADIUS = 28
OUTER = (143, 180, 199)
INNER = (125, 158, 175)


def frame(src: Image.Image) -> Image.Image:
    src = src.convert('RGBA')
    w, h = src.size
    W, H = w + 2 * BORDER, h + 2 * BORDER
    out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    # Border: concentric rounded rectangles fading from OUTER to INNER.
    border = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(border)
    for i in range(BORDER):
        t = i / (BORDER - 1)
        c = tuple(int(OUTER[k] + (INNER[k] - OUTER[k]) * t) for k in range(3)) + (255,)
        d.rounded_rectangle((i, i, W - 1 - i, H - 1 - i), radius=max(4, RADIUS - i), fill=c)
    out.alpha_composite(border)
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=max(4, RADIUS - BORDER), fill=255)
    inner = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    inner.paste(src, (0, 0), mask)
    out.alpha_composite(inner, (BORDER, BORDER))
    return out


def side_by_side(a: Image.Image, b: Image.Image, gap: int = 40) -> Image.Image:
    h = min(a.height, b.height)
    a = a.resize((round(a.width * h / a.height), h), Image.LANCZOS)
    b = b.resize((round(b.width * h / b.height), h), Image.LANCZOS)
    out = Image.new('RGBA', (a.width + gap + b.width, h), (0, 0, 0, 0))
    out.alpha_composite(a, (0, 0))
    out.alpha_composite(b, (a.width + gap, 0))
    return out


if __name__ == '__main__':
    src_dir, out_dir = sys.argv[1], sys.argv[2]
    for scheme in ('dark', 'light'):
        lib = Image.open(f'{src_dir}/library-{scheme}.png')
        frame(lib).save(f'{out_dir}/library-{scheme}.png', optimize=True)
        col = Image.open(f'{src_dir}/collection-{scheme}.png')
        ep = Image.open(f'{src_dir}/episode-{scheme}.png')
        # Show both at the width of WireLoft's pair: crop the right edge so each is a bit narrower than 16:10.
        side_by_side(frame(col), frame(ep)).save(f'{out_dir}/collection-episode-{scheme}.png', optimize=True)
