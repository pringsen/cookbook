"""AI recipe extraction (photos or page text) using Claude."""
import base64
import io
import json
import logging

import anthropic
from PIL import Image, ImageOps

from .importer import RecipeDraft

log = logging.getLogger(__name__)

RECIPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["found", "title", "description", "servings", "prep_minutes", "cook_minutes",
                 "ingredients", "instructions", "notes", "tags"],
    "properties": {
        "found": {"type": "boolean", "description": "false if no recipe is visible"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "servings": {"type": ["integer", "null"]},
        "prep_minutes": {"type": ["integer", "null"]},
        "cook_minutes": {"type": ["integer", "null"]},
        "ingredients": {"type": "array", "items": {"type": "string"}},
        "instructions": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM = (
    "You transcribe recipes for a personal cookbook app. Copy the recipe faithfully in its original "
    "language; do not translate, invent, or embellish. Rules:\n"
    "- ingredients: one entry per ingredient, formatted 'quantity unit name, preparation' "
    "(e.g. '200 g flour', '2 eggs, beaten'). If the recipe groups ingredients, add the group name "
    "as its own entry ending with a colon (e.g. 'For the sauce:').\n"
    "- instructions: one entry per step, without leading step numbers.\n"
    "- servings / times: numbers only, null if not stated. Times in minutes.\n"
    "- notes: tips, variations, or storage hints that appear in the source; otherwise empty.\n"
    "- tags: up to 5 short tags (cuisine, course, main ingredient), in the recipe's language.\n"
    "- If several photos are given they are pages of the same recipe, in order.\n"
    "- If you cannot find a recipe, set found to false and leave other fields empty."
)


class AIError(Exception):
    pass


def _prepare_image(data: bytes) -> tuple[str, str]:
    """Downscale so the long edge is <= 1568px (what the model uses anyway) and return base64 JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((1568, 1568))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()
    except Exception as e:
        raise AIError(f"Could not read the image: {e}") from e


def _call(api_key: str, model: str, content: list) -> RecipeDraft:
    if not api_key:
        raise AIError("No Anthropic API key configured. Add one under Settings.")
    client = anthropic.Anthropic(api_key=api_key, timeout=180, max_retries=2)
    params = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": RECIPE_SCHEMA}},
    )
    try:
        try:
            # If the model declines, let the API retry on a suitable fallback model.
            response = client.beta.messages.create(
                **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except anthropic.BadRequestError as e:
            # Older/other models may not accept server-side fallbacks; retry without them.
            if "fallback" not in str(e.message).lower():
                raise
            log.info("Retrying without fallbacks: %s", e.message)
            response = client.messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise AIError("The Anthropic API key was rejected. Check it under Settings.") from e
    except anthropic.NotFoundError as e:
        raise AIError(f"Model '{model}' was not found. Check the model name under Settings.") from e
    except anthropic.RateLimitError as e:
        raise AIError("The AI service is rate limiting requests. Try again in a minute.") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"AI request failed ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Could not reach the Anthropic API. Check the server's internet access.") from e

    if response.stop_reason == "refusal":
        raise AIError("The AI declined to process this input.")
    if response.stop_reason == "max_tokens":
        raise AIError("The recipe was too long for one request.")
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.warning("Bad AI JSON: %s", text[:500])
        raise AIError("The AI returned an unreadable answer. Please try again.") from e
    if not data.get("found"):
        raise AIError("No recipe could be found in the input.")
    return RecipeDraft(
        title=data.get("title", "").strip(),
        description=data.get("description", "").strip(),
        servings=data.get("servings"),
        prep_minutes=data.get("prep_minutes"),
        cook_minutes=data.get("cook_minutes"),
        ingredients=[i.strip() for i in data.get("ingredients", []) if i.strip()],
        instructions=[i.strip() for i in data.get("instructions", []) if i.strip()],
        notes=data.get("notes", "").strip(),
        tags=[t.strip() for t in data.get("tags", []) if t.strip()],
    )


def extract_from_images(api_key: str, model: str, images: list[bytes], hint: str = "") -> RecipeDraft:
    content: list = []
    for i, data in enumerate(images[:6], 1):
        media_type, b64 = _prepare_image(data)
        if len(images) > 1:
            content.append({"type": "text", "text": f"Photo {i}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
    prompt = "Transcribe the recipe shown in these photos." if len(images) > 1 else "Transcribe the recipe in this photo."
    if hint:
        prompt += f"\nNote from the user: {hint}"
    content.append({"type": "text", "text": prompt})
    return _call(api_key, model, content)


def extract_from_text(api_key: str, model: str, text: str, url: str = "") -> RecipeDraft:
    content = [{"type": "text", "text": (
        f"Extract the recipe from this web page text (source: {url}).\n\n<page>\n{text}\n</page>")}]
    d = _call(api_key, model, content)
    d.source_url = url
    return d
