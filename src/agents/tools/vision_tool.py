"""Vision tool: analyze medical images via Claude vision API."""
import anthropic
from loguru import logger

from src.core.config import settings
from src.core.types import ImageMetadata

TOOL_DEFINITION = {
    "name": "vision_tool",
    "description": (
        "Analyze one or more medical images (CT, X-ray, PET) and return a structured "
        "radiological description. Describe what is visible: parenchyma, nodules, "
        "mediastinum, pleura, and any abnormalities."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "image_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Indices of images to analyze (from the provided image list)",
            },
            "focus": {
                "type": "string",
                "description": "Specific aspect to focus on (e.g. 'nodule size', 'pleural effusion')",
            },
        },
        "required": ["image_indices"],
    },
}


async def run_vision_tool(
    image_indices: list[int],
    images: list[ImageMetadata],
    focus: str | None = None,
) -> str:
    """Call Claude vision to analyze the selected images."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    selected = [images[i] for i in image_indices if i < len(images)]
    if not selected:
        return "No valid images provided for vision analysis."

    content: list[dict] = []

    for img_meta in selected:
        if img_meta.thumbnail_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_meta.thumbnail_b64,
                },
            })
            content.append({
                "type": "text",
                "text": (
                    f"Image: {img_meta.filename}"
                    + (f" (date: {img_meta.exam_date})" if img_meta.exam_date else "")
                    + (f", modality: {img_meta.modality}" if img_meta.modality else "")
                ),
            })

    focus_text = f"\n\nFocus particularly on: {focus}" if focus else ""
    content.append({
        "type": "text",
        "text": (
            "You are an expert radiologist. Analyze the medical image(s) above and provide "
            "a structured radiological description including:\n"
            "- Pulmonary parenchyma (nodules, consolidation, ground glass)\n"
            "- Mediastinum and vascular structures\n"
            "- Pleura and thoracic wall\n"
            "- Any notable findings or abnormalities\n"
            "Be precise, use radiological terminology, and note sizes in mm when visible."
            + focus_text
        ),
    })

    logger.info(f"Calling vision API for {len(selected)} image(s)")
    response = client.messages.create(
        model=settings.vision_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )

    result = response.content[0].text if response.content else "No vision output."
    logger.debug(f"Vision result ({len(result)} chars)")
    return result
