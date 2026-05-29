import asyncio
import io
from PIL import Image

SUPPORTED_LANGUAGES = {
    "English":        "en",
    "Tiếng Việt":     "vi",
    "日本語":          "ja",
    "한국어":          "ko",
    "中文 (简体)":     "zh-Hans-CN",
    "中文 (繁體)":     "zh-Hant-TW",
    "Français":       "fr",
    "Deutsch":        "de",
    "Español":        "es",
    "Русский":        "ru",
}


async def _recognize_async(image: Image.Image, lang_tag: str) -> str:
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import (
        BitmapDecoder, SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode,
    )
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter

    # Chuyển PIL image thành bytes BMP
    buf = io.BytesIO()
    image.save(buf, format="BMP")
    data = bytearray(buf.getvalue())

    # Đưa vào WinRT stream
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)

    # Giải mã thành SoftwareBitmap
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    # OCR yêu cầu định dạng BGRA8 + premultiplied alpha
    if (bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8
            or bitmap.bitmap_alpha_mode != BitmapAlphaMode.PREMULTIPLIED):
        bitmap = SoftwareBitmap.convert(
            bitmap, BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED
        )

    # Lấy OCR engine
    language = Language(lang_tag)
    engine = (
        OcrEngine.try_create_from_language(language)
        if OcrEngine.is_language_supported(language)
        else OcrEngine.try_create_from_user_profile_languages()
    )
    if engine is None:
        raise RuntimeError(
            f"Không tìm thấy OCR engine cho ngôn ngữ '{lang_tag}'.\n"
            "Vào: Cài đặt Windows > Thời gian & Ngôn ngữ > Ngôn ngữ để cài thêm gói ngôn ngữ."
        )

    result = await engine.recognize_async(bitmap)
    return result.text


def recognize(image: Image.Image, lang_tag: str = "en") -> str:
    """Nhận dạng văn bản trong ảnh PIL bằng Windows OCR API."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_recognize_async(image, lang_tag))
    finally:
        loop.close()
