import argparse
import os
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real GPU background removal API")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument("--api-key", default=os.getenv("API_KEY"))
    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key or API_KEY is required")
    if not args.image.is_file():
        parser.error(f"Image does not exist: {args.image}")

    with args.image.open("rb") as image_file:
        response = httpx.post(
            f"{args.base_url.rstrip('/')}/v1/remove-background",
            headers={"X-API-Key": args.api_key},
            files={"file": (args.image.name, image_file, "image/jpeg")},
            timeout=180.0,
        )

    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as result:
        if result.format != "PNG" or result.mode != "RGBA":
            raise RuntimeError(
                f"Expected RGBA PNG, got format={result.format!r}, mode={result.mode!r}"
            )
        print(f"GPU smoke test passed: {result.width}x{result.height} RGBA PNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
