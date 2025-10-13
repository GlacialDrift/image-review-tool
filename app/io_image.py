from PIL import Image


def load_image(path: str) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img


def downscale_for_screen(img: Image.Image, max_side=1400) -> Image.Image:
    w, h = img.size
    scale = min(max_side / max(w, h), 1.0)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
