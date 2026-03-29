"""Convert scanned recipe images to markdown using Claude API.

Outputs a JSON array of processed recipes to stdout for the workflow to use.
"""

import anthropic
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

SYSTEM_PROMPT = """You are an expert at reading handwritten Norwegian recipes and converting them to well-formatted Markdown.

Your task:
1. Carefully transcribe the handwritten recipe from the provided image(s).
2. Convert it to Markdown using the exact frontmatter format shown below.
3. Use Nynorsk (nynorsk) throughout. If the original is in Bokmål or dialect, translate to Nynorsk but keep the spirit of the original.
4. Guess appropriate tags and category based on the content.
5. Structure ingredients as a bullet list under "## Ingrediensar"
6. Structure the method as numbered steps under "## Framgangsmåte"
7. If something is illegible, mark it with [ulesleg]
8. Return ONLY the Markdown content, nothing else. No code fences.

Frontmatter format:
---
tittel: "Recipe title in Nynorsk"
tags: ["tag1", "tag2"]
kategori: "Category"
dato: YYYY-MM-DD (use today's date)
original_skann: "skannar/FILENAME"
---

The original_skann field should use the FILENAME placeholder — it will be replaced with the actual filename.

Available categories:
- Bakverk
- Middag
- Supper og gryter
- Fisk og sjømat
- Dessert
- Frukost
- Drikke og saft
- Sylting og konservering
- Tradisjonelt og høgtid
"""

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKANNAR_DIR = REPO_ROOT / "recipes-site" / "public" / "skannar"
OPPSKRIFTER_DIR = REPO_ROOT / "recipes-site" / "src" / "content" / "oppskrifter"

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[æ]", "ae", text)
    text = re.sub(r"[ø]", "o", text)
    text = re.sub(r"[å]", "a", text)
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def extract_title(markdown: str) -> str:
    match = re.search(r'tittel:\s*"(.+?)"', markdown)
    return match.group(1) if match else "oppskrift"


def get_new_images() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", "HEAD~1", "HEAD", "--", "recipes-site/public/skannar/*"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    paths = []
    for line in result.stdout.strip().splitlines():
        p = REPO_ROOT / line
        if p.suffix.lower() in MEDIA_TYPES and p.exists():
            paths.append(p)
    return paths


def convert_image(client: anthropic.Anthropic, image_path: Path) -> str:
    image_data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    media_type = MEDIA_TYPES.get(image_path.suffix.lower(), "image/jpeg")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": "Please transcribe and convert this handwritten recipe to Markdown."},
            ],
        }],
    )

    return response.content[0].text


def process_image(client: anthropic.Anthropic, image_path: Path) -> dict:
    print(f"Converting: {image_path.name}", file=sys.stderr)

    markdown = convert_image(client, image_path)

    # Strip code fences if present
    markdown = re.sub(r"^```\w*\n", "", markdown)
    markdown = re.sub(r"\n```$", "", markdown)

    title = extract_title(markdown)
    slug = slugify(title)

    # Rename the image file to match the recipe title
    new_image_name = f"{slug}{image_path.suffix.lower()}"
    new_image_path = image_path.parent / new_image_name

    if new_image_path != image_path:
        subprocess.run(
            ["git", "mv", str(image_path), str(new_image_path)],
            cwd=REPO_ROOT, check=True,
        )
        print(f"Renamed: {image_path.name} -> {new_image_name}", file=sys.stderr)

    # Update the original_skann field in markdown
    markdown = markdown.replace("FILENAME", new_image_name)
    markdown = re.sub(
        r'original_skann:\s*"skannar/[^"]*"',
        f'original_skann: "skannar/{new_image_name}"',
        markdown,
    )

    # Write the markdown file
    OPPSKRIFTER_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OPPSKRIFTER_DIR / f"{slug}.md"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"Created: {md_path.name}", file=sys.stderr)

    return {
        "title": title,
        "slug": slug,
        "image": image_path.name,
        "new_image": new_image_name,
        "md_file": f"{slug}.md",
    }


def main():
    images = get_new_images()
    if not images:
        print("No new images to process.", file=sys.stderr)
        print("[]")
        return

    client = anthropic.Anthropic()
    results = []

    for image_path in images:
        result = process_image(client, image_path)
        results.append(result)

    print(f"Done! Processed {len(images)} image(s).", file=sys.stderr)
    print(json.dumps(results))


if __name__ == "__main__":
    main()
