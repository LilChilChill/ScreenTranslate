import mss
from PIL import Image


def capture_region(region: tuple) -> Image.Image:
    """Chụp vùng màn hình. region = (x, y, width, height)"""
    x, y, w, h = region
    with mss.mss() as sct:
        mon = {"top": y, "left": x, "width": w, "height": h}
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
