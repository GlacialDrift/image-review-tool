from PIL import Image


def load_image(path: str) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img

def _crop_for_display(img: Image.Image, cfg_image: dict | None) -> Image.Image:
    """Optionally crop based on config. If no valid crop in config, return image unchanged."""
    if not cfg_image:
        return img
    cw = cfg_image.get("crop_width")
    ch = cfg_image.get("crop_height")
    print(cw)
    print(ch)
    if not cw or not ch:
        return img

    W, H = img.size
    cw = min(max(1,cw), W)
    ch = min(max(1,ch), H)

    h_align = cfg_image.get("h_align", "center")
    v_align = cfg_image.get("v_align", "center")

    if h_align == "left":
        x0 = 0
    elif h_align == "right":
        x0 = W - cw
    else:  # center
        x0 = (W - cw) // 2

    if v_align == "top":
        y0 = 0
    elif v_align == "bottom":
        y0 = H - ch
    else:  # center
        y0 = (H - ch) // 2

    x1 = x0+cw
    y1 = y0+ch
    return img.crop((int(x0), int(y0), int(x1), int(y1)))

def resize_for_screen(img: Image.Image, max_side=1280) -> Image.Image:
    w, h = img.size
    scale = max_side / max(w,h)
    print(scale)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

def prepare_for_display(img: Image.Image, cfg_image: dict | None) -> Image.Image:
    """
        New: apply optional crop, then downscale.
        Falls back to current behavior if cfg_image is None or missing crop settings.
        """
    max_side = 1280
    if cfg_image and isinstance(cfg_image.get("max_display_side"), int):
        max_side = cfg_image["max_display_side"]
    cropped = _crop_for_display(img, cfg_image)
    return resize_for_screen(cropped, max_side=max_side)