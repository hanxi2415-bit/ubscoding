import os
from fastmcp import FastMCP
import base64
import cv2
import numpy as np

mcp = FastMCP("NurseryServer")

@mcp.tool
def get_name() -> str:
    """Return the agent's name."""
    return "BabyBot"

@mcp.tool
def calculate(a: int, operator: str, b: int) -> float:
    """Calculate a + b, a - b, a * b, or a / b."""
    if operator == "+":
        return a + b
    elif operator == "-":
        return a - b
    elif operator == "*":
        return a * b
    elif operator == "/":
        return a / b
    else:
        raise ValueError("Unsupported operator")

@mcp.tool
def identify_shape(image_base64: str) -> str:
    """Identify whether a base64-encoded PNG contains a triangle, rectangle, or circle."""

    image_bytes = base64.b64decode(image_base64)
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_GRAYSCALE)

    if image is None:
        raise ValueError("Invalid PNG image")

    _, threshold = cv2.threshold(
        image,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    contours, _ = cv2.findContours(
        threshold,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        raise ValueError("No shape found")


    contour = max(contours, key=cv2.contourArea)

    perimeter = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)

    vertices = len(approx)

    if vertices == 3:
        return "triangle"
    elif vertices == 4:
        return "rectangle"
    else:
        return "circle"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp"
    )