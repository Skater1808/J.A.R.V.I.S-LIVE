"""
Jarvis V2 — Screen Capture
Takes screenshots and describes them via Gemini Vision.
"""

import base64
import io
from PIL import ImageGrab, Image


def capture_screen() -> bytes:
    """Capture the entire screen, return PNG bytes."""
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def describe_screen_gemini(gemini_client) -> str:
    """Capture screen and describe it using Gemini Vision."""
    png_bytes = capture_screen()

    # Gemini expects PIL Image object
    img = Image.open(io.BytesIO(png_bytes))

    # Generate description using new google-genai SDK
    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=[
            "Beschreibe kurz auf Deutsch was auf diesem Bildschirm zu sehen ist. Maximal 2-3 Saetze. Nenne die wichtigsten offenen Programme und Inhalte.",
            img
        ]
    )

    return response.text


# Legacy function for backwards compatibility (if needed)
async def describe_screen(anthropic_client) -> str:
    """Legacy function - redirects to Gemini."""
    # This requires gemini_model to be passed, but for backwards compatibility
    # we just return a placeholder
    return "Screenshot-Funktion nur mit Gemini verfügbar. Nutze describe_screen_gemini()."
