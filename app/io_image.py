from PIL import Image


def load_image(path: str) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img

def _crop_for_display(img: Image.Image, cfg_image: dict | None):
    """Optionally crop based on config. If no valid crop in config, return image unchanged."""
    if not cfg_image:
        return img, (0,0,img.size[0],img.size[1])
    cw = cfg_image.get("crop_width")
    ch = cfg_image.get("crop_height")
    if not cw or not ch:
        W, H = img.size
        return img, (0,0,W,H)

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
    return img.crop((int(x0), int(y0), int(x1), int(y1))), (int(x0), int(y0), int(cw), int(ch))

def resize_for_screen(img: Image.Image, max_side=1280):
    w, h = img.size
    scale = max_side / max(w,h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS), scale

def prepare_for_display(img: Image.Image, cfg_image: dict | None):
    """
    Returns (processed_image, info) where info contains:
      - original_size: (W, H)
      - crop: (x0, y0, cw, ch) in original coords
      - scale: displayed_size / cropped_size (float)
      - displayed_size: (dw, dh)
    """
    W, H = img.size
    cropped, (x0, y0, cw, ch) = _crop_for_display(img, cfg_image)
    max_side = 1280
    if cfg_image and isinstance(cfg_image.get("max_display_side"), int):
        max_side = cfg_image["max_display_side"]
    disp, scale = resize_for_screen(cropped, max_side=max_side)
    dw, dh = disp.size
    info = {
        "original_size": (W, H),
        "crop": (x0, y0, cw, ch),
        "scale": scale,
        "displayed_size": (dw, dh),
    }
    return disp, info