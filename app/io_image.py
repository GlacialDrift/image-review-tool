"""Image I/O and transformation utilities for the Image Review Tool.

This module handles loading, cropping, and resizing of images for display
within the Tkinter GUI. It is designed to maintain a clear mapping between
the displayed image (potentially cropped and scaled) and the original image
space, enabling accurate click annotation recording.

Functions:
    load_image(path):            Load an image from disk using Pillow (PIL).
    _crop_for_display(img, cfg): Crop according to configuration parameters.
    resize_for_screen(img, n):   Resize an image while maintaining aspect ratio.
    prepare_for_display(img, c): Full preprocessing pipeline returning both
                                 the display image and the geometric transform
                                 metadata (for reverse-mapping click points).

Coordinate conventions:
    - Image coordinates follow Pillow’s standard (x=horizontal, y=vertical)
      with (0,0) at the top-left corner.
    - All normalized annotation coordinates (x_norm, y_norm) are relative to
      the *original* uncropped image dimensions.
"""

from PIL import Image

def load_image(path: str) -> Image.Image:
    """Load an image from disk into a Pillow Image object.

    Args:
        path: Filesystem path to the image.

    Returns:
        A fully loaded `PIL.Image.Image` object.

    Raises:
        FileNotFoundError: If the path does not exist.
        OSError: If the file cannot be read as an image.
    """
    img = Image.open(path)
    img.load()
    return img

def _crop_for_display(img: Image.Image, cfg_image: dict | None):
    """Optionally crop an image based on configuration parameters.

    Args:
        img: Pillow image to crop.
        cfg_image: Dictionary of image display configuration, e.g.:
            {
              "crop_width": int,
              "crop_height": int,
              "h_align": "left" | "center" | "right",
              "v_align": "top"  | "center" | "bottom"
            }

    Returns:
        tuple:
          (cropped_image, (x0, y0, cw, ch))
          where:
            x0, y0  — top-left crop offset in original image coordinates
            cw, ch  — crop width and height in pixels

    Notes:
        - If crop dimensions are missing or invalid, the original image is
          returned unchanged.
        - Cropping is clamped to the image boundaries.
    """
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
    """Resize an image to fit within a given bounding box.

    Maintains the aspect ratio and scales the image such that its longest
    side equals `max_side`.

    Args:
        img: Pillow Image to resize.
        max_side: Maximum pixel length of the longer side of the resized image.

    Returns:
        tuple:
          (resized_image, scale)
          where `scale` = resized_side / original_side (float).

    Notes:
        The resize uses LANCZOS resampling for high-quality downscaling.
    """
    w, h = img.size
    scale = max_side / max(w,h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS), scale

def prepare_for_display(img: Image.Image, cfg_image: dict | None):
    """Prepare an image for on-screen display with optional crop and scale.

    Applies optional cropping and downscaling and returns both the processed
    image and metadata describing the geometric transform. This allows reverse
    mapping of GUI click coordinates to original image coordinates.

    Args:
        img: Pillow Image loaded from disk.
        cfg_image: Dictionary with optional display settings (see `_crop_for_display`).

    Returns:
        tuple:
          (display_image, info_dict)

          where info_dict includes:
            - original_size: (W, H) — original image dimensions
            - crop: (x0, y0, cw, ch) — crop rectangle in original coordinates
            - scale: float — scaling factor (display/original)
            - displayed_size: (dw, dh) — display image pixel dimensions

    Example:
        disp, info = prepare_for_display(img, cfg)
        tkimg = ImageTk.PhotoImage(disp)
        # info can be used to map click points back to original coordinates.
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