"""Generate brand images (icon.png, logo.png) for the integration."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent.parent / "custom_components/hikvision_nvr_arm/brand"
S = 4  # supersampling


def icon(size: int, dark: bool = False) -> Image.Image:
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # rounded square with vertical gradient
    top, bot = ((24, 90, 140), (10, 45, 85)) if not dark else ((60, 130, 190), (30, 80, 130))
    grad = Image.new("RGBA", (n, n))
    gd = ImageDraw.Draw(grad)
    for y in range(n):
        t = y / n
        gd.line([(0, y), (n, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    # white shield
    def p(x, y):
        return (x * n / 100, y * n / 100)
    shield = [p(50, 14), p(80, 25), p(80, 50), p(76, 64), p(50, 86), p(24, 64), p(20, 50), p(20, 25)]
    d.polygon(shield, fill=(255, 255, 255, 255))
    # bell (blue) inside the shield
    c = (18, 70, 115, 255)
    d.pieslice([p(36, 34), p(64, 62)], 180, 360, fill=c)
    d.rectangle([p(36, 48), p(64, 60)], fill=c)
    d.polygon([p(33, 60), p(67, 60), p(70, 65), p(30, 65)], fill=c)
    d.ellipse([p(46, 64), p(54, 72)], fill=c)
    d.ellipse([p(47.5, 30), p(52.5, 35)], fill=c)
    return img.resize((size, size), Image.LANCZOS)


def logo(height: int = 256) -> Image.Image:
    ic = icon(height)
    try:
        font = ImageFont.truetype("segoeuib.ttf", int(height * 0.24))
        small = ImageFont.truetype("segoeui.ttf", int(height * 0.17))
    except OSError:
        font = small = ImageFont.load_default()
    text1, text2 = "Hikvision NVR", "Arm / Disarm"
    w = height + int(height * 0.12) + int(max(font.getlength(text1), small.getlength(text2))) + 8
    img = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    img.paste(ic, (0, 0), ic)
    d = ImageDraw.Draw(img)
    x = height + int(height * 0.12)
    d.text((x, int(height * 0.30)), text1, font=font, fill=(18, 70, 115, 255))
    d.text((x, int(height * 0.56)), text2, font=small, fill=(90, 110, 130, 255))
    return img


OUT.mkdir(parents=True, exist_ok=True)
icon(256).save(OUT / "icon.png")
icon(512).save(OUT / "icon@2x.png")
icon(256, dark=True).save(OUT / "dark_icon.png")
icon(512, dark=True).save(OUT / "dark_icon@2x.png")
logo(256).save(OUT / "logo.png")
logo(512).save(OUT / "logo@2x.png")
print(sorted(p.name for p in OUT.iterdir()))
