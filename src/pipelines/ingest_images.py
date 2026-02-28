"""Parse medical images (JPEG/PNG) into ImageMetadata with base64 thumbnails."""
import base64
import io
from datetime import date
from pathlib import Path

from loguru import logger
from PIL import Image

from src.core.types import ImageMetadata

THUMBNAIL_SIZE = (512, 512)
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


def _extract_date_from_filename(filename: str) -> date | None:
    """Try to extract a date from common filename patterns like ct_2024_06.jpg."""
    import re
    patterns = [
        r"(\d{4})[-_](\d{2})[-_](\d{2})",  # 2024-06-15 or 2024_06_15
        r"(\d{4})[-_](\d{2})",              # 2024-06 or 2024_06
    ]
    for pattern in patterns:
        m = re.search(pattern, filename)
        if m:
            groups = m.groups()
            try:
                if len(groups) == 3:
                    return date(int(groups[0]), int(groups[1]), int(groups[2]))
                elif len(groups) == 2:
                    return date(int(groups[0]), int(groups[1]), 1)
            except ValueError:
                continue
    return None


def _guess_modality(filename: str) -> str | None:
    lower = filename.lower()
    if "ct" in lower or "scan" in lower or "scanner" in lower:
        return "CT"
    if "pet" in lower:
        return "PET"
    if "rx" in lower or "radio" in lower or "chest" in lower:
        return "RX"
    if "mri" in lower or "irm" in lower:
        return "MRI"
    return None


def _image_to_b64_thumbnail(img: Image.Image) -> str:
    """Convert PIL image to base64 JPEG thumbnail string."""
    img_copy = img.copy()
    img_copy.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    if img_copy.mode not in ("RGB", "L"):
        img_copy = img_copy.convert("RGB")
    buf = io.BytesIO()
    img_copy.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def ingest_images(paths: list[Path]) -> list[ImageMetadata]:
    """Load and process a list of image paths into ImageMetadata objects."""
    results = []
    for path in paths:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.warning(f"Skipping unsupported image format: {path.name}")
            continue
        if not path.exists():
            logger.warning(f"Image not found: {path}")
            continue

        try:
            img = Image.open(path)
            width, height = img.size
            thumbnail_b64 = _image_to_b64_thumbnail(img)
            exam_date = _extract_date_from_filename(path.name)
            modality = _guess_modality(path.name)

            metadata = ImageMetadata(
                file_path=path,
                filename=path.name,
                exam_date=exam_date,
                modality=modality,
                width=width,
                height=height,
                thumbnail_b64=thumbnail_b64,
            )
            results.append(metadata)
            logger.info(f"Loaded image: {path.name} ({width}x{height}, modality={modality})")
        except Exception as e:
            logger.error(f"Failed to process image {path.name}: {e}")

    return results
