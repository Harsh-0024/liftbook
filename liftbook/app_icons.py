"""Every icon and launch screen the app ships, built from one square source image.

An admin upload goes through prepare_source() once (sized, centered, stored in
the database); render() then builds each file on demand, so the browser tab,
home screen and launch screens always match whatever icon is current.
"""
import io

import numpy as np
from PIL import Image, ImageChops

SOURCE_SIZE = 1024
FIGURE_SHARE = 0.78   # the figure's width (or height) as a share of the icon
OPTICAL_LIFT = 0.03   # visual weight sits this far above the true center
FIGURE_CUTOFF = (30, 60)  # difference from the background that counts as figure

PLAIN_SIZES = {
    'app-icon-512.png': 512,
    'app-icon-192.png': 192,
    'apple-touch-icon.png': 180,
    'favicon-32.png': 32,
}

# Android crops "maskable" icons to a circle or squircle; the figure has to sit
# inside the middle 80% to survive that.
MASKABLE_SIZES = {
    'maskable-512.png': 512,
    'maskable-192.png': 192,
}
MASKABLE_SCALE = 0.88

# iPhone launch screens (portrait): CSS width, CSS height, pixel ratio.
# base.html links each one with the media query iOS matches it against.
IPHONE_SCREENS = [
    (440, 956, 3),  # 16 Pro Max, 17 Pro Max
    (420, 912, 3),  # Air
    (402, 874, 3),  # 16 Pro, 17, 17 Pro
    (430, 932, 3),  # 14 Pro Max, 15 Plus / Pro Max, 16 Plus
    (393, 852, 3),  # 14 Pro, 15, 15 Pro, 16, 16e
    (428, 926, 3),  # 12 / 13 Pro Max, 14 Plus
    (390, 844, 3),  # 12, 13, 14 and their Pros
    (375, 812, 3),  # X, XS, 11 Pro, 12 / 13 mini
    (414, 896, 3),  # XS Max, 11 Pro Max
    (414, 896, 2),  # XR, 11
    (414, 736, 3),  # 6 / 7 / 8 Plus
    (375, 667, 2),  # SE 2nd / 3rd gen, 6 / 7 / 8
    (320, 568, 2),  # SE 1st gen
]
SPLASH_ICON_FRACTION = 0.5  # icon width as a share of the screen width


def splash_filename(css_w, css_h, ratio):
    return f'splash/splash-{css_w * ratio}x{css_h * ratio}.png'


SPLASH_SIZES = {
    splash_filename(css_w, css_h, ratio): (css_w * ratio, css_h * ratio)
    for css_w, css_h, ratio in IPHONE_SCREENS
}

FILENAMES = frozenset({*PLAIN_SIZES, *MASKABLE_SIZES, *SPLASH_SIZES, 'favicon.ico'})


def background_color(image):
    """The icon's background: the median colour of its outer edge."""
    rgb = np.asarray(image.convert('RGB'))
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    return tuple(int(c) for c in np.median(edge, axis=0))


def _figure_mask(image, bg):
    """255 where the pixel is part of the figure, fading to 0 on the background."""
    diff = ImageChops.difference(image.convert('RGB'), Image.new('RGB', image.size, bg))
    r, g, b = diff.split()
    low, high = FIGURE_CUTOFF
    return ImageChops.lighter(r, ImageChops.lighter(g, b)).point(
        lambda v: 0 if v <= low else 255 if v >= high else round(255 * (v - low) / (high - low))
    )


def prepare_source(image):
    """Square, sized and optically centered icon on a flat background.

    The figure is cut out of whatever background it came with, scaled so it
    fills FIGURE_SHARE of the icon, centered left to right, and placed so its
    visual weight sits OPTICAL_LIFT above the middle. Full-bleed artwork (no
    background around it) is only squared and resized.
    """
    rgba = image.convert('RGBA')
    flat = Image.alpha_composite(Image.new('RGBA', rgba.size, (0, 0, 0, 255)), rgba).convert('RGB')
    bg = background_color(flat)

    side = max(flat.size)
    square = Image.new('RGB', (side, side), bg)
    square.paste(flat, ((side - flat.width) // 2, (side - flat.height) // 2))

    mask = _figure_mask(square, bg)
    box = mask.point(lambda v: 255 if v > 127 else 0).getbbox()
    if box is None or (box[2] - box[0] >= side * 0.97 and box[3] - box[1] >= side * 0.97):
        return square.resize((SOURCE_SIZE, SOURCE_SIZE), Image.LANCZOS)

    figure = square.crop(box)
    figure_mask = mask.crop(box)
    weights = np.asarray(figure_mask, dtype=np.float64)
    centroid_y = (weights.sum(axis=1) * np.arange(weights.shape[0])).sum() / weights.sum()

    scale = FIGURE_SHARE * SOURCE_SIZE / max(figure.width, figure.height)
    size = (max(1, round(figure.width * scale)), max(1, round(figure.height * scale)))
    figure = figure.resize(size, Image.LANCZOS)
    figure_mask = figure_mask.resize(size, Image.LANCZOS)

    x = (SOURCE_SIZE - size[0]) // 2
    y = round(SOURCE_SIZE * (0.5 - OPTICAL_LIFT) - centroid_y * scale)
    y = min(max(y, 0), SOURCE_SIZE - size[1])

    out = Image.new('RGB', (SOURCE_SIZE, SOURCE_SIZE), bg)
    out.paste(figure, (x, y), figure_mask)
    return out


def _png(image):
    buf = io.BytesIO()
    image.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def _on_background(source, bg, canvas_size, icon_width):
    canvas = Image.new('RGB', canvas_size, bg)
    icon = source.resize((icon_width, icon_width), Image.LANCZOS)
    canvas.paste(icon, ((canvas_size[0] - icon_width) // 2, (canvas_size[1] - icon_width) // 2))
    return canvas


def render(source, filename):
    """The bytes of one icon file, built from a prepare_source() image."""
    source = source.convert('RGB')
    if filename in PLAIN_SIZES:
        size = PLAIN_SIZES[filename]
        return _png(source.resize((size, size), Image.LANCZOS))
    if filename == 'favicon.ico':
        buf = io.BytesIO()
        source.save(buf, format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
        return buf.getvalue()

    # The source's background is flat, so pasting it onto a canvas of the same
    # colour leaves no visible square around the figure.
    bg = background_color(source)
    if filename in MASKABLE_SIZES:
        size = MASKABLE_SIZES[filename]
        return _png(_on_background(source, bg, (size, size), round(size * MASKABLE_SCALE)))
    if filename in SPLASH_SIZES:
        width, height = SPLASH_SIZES[filename]
        return _png(_on_background(source, bg, (width, height), round(width * SPLASH_ICON_FRACTION)))
    raise KeyError(filename)
