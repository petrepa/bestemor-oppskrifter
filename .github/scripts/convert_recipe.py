"""Convert scanned recipe images to markdown using Claude API.

Two-pass process:
1. Transcribe the handwritten recipe from the image
2. Review the transcription for errors, fix them, and document changes

Outputs a JSON array of processed recipes to stdout for the workflow to use.
"""

import anthropic
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TRANSCRIBE_PROMPT = """You are an expert at reading handwritten Norwegian recipes and converting them to well-formatted Markdown.

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

REVIEW_PROMPT = """You are a careful proofreader and recipe expert reviewing a transcription of a handwritten Norwegian recipe.

You will receive:
1. The original image of the handwritten recipe
2. A markdown transcription of that recipe

Your job is to review the transcription and fix any issues:

- **Spelling errors**: Fix obvious misspellings in Norwegian (nynorsk)
- **Ingredients that don't make sense**: If an ingredient seems wrong (e.g. misread handwriting), correct it based on what makes sense for this type of recipe
- **Quantities that seem off**: If amounts seem unreasonable (e.g. 50 liters of milk), fix them to something sensible
- **Missing or garbled steps**: If a step in the method is unclear or incomplete, try to make it coherent
- **General coherence**: Make sure the recipe reads naturally and makes sense as a whole

You MUST respond with a JSON object (no code fences) with exactly two fields:
{
  "markdown": "the corrected full markdown content here",
  "changes": ["list", "of", "changes", "made"]
}

Each entry in "changes" should be a short description in Norwegian (nynorsk) of what was changed and why, e.g.:
- "Retta 'mølk' til 'mjølk' (skrivefeil)"
- "Endra mengde frå '50 liter mjølk' til '5 dl mjølk' (urimeleg mengde)"
- "Tolka 'grsjk' som 'graslauk' basert på kontekst"

If nothing needs to be changed, return the original markdown unchanged and an empty changes list.
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
    image_names_env = os.environ.get("IMAGE_NAMES", "").strip()
    if image_names_env:
        paths = []
        for name in image_names_env.split(","):
            name = name.strip()
            if name:
                p = SKANNAR_DIR / name
                if p.suffix.lower() in MEDIA_TYPES and p.exists():
                    paths.append(p)
                else:
                    print(f"Warning: {name} not found or unsupported format, skipping.", file=sys.stderr)
        return paths

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


def transcribe_image(client: anthropic.Anthropic, image_data: str, media_type: str) -> str:
    """Pass 1: Transcribe the handwritten recipe from the image."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=TRANSCRIBE_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": "Please transcribe and convert this handwritten recipe to Markdown."},
            ],
        }],
    )
    return response.content[0].text


def review_transcription(client: anthropic.Anthropic, image_data: str, media_type: str, markdown: str) -> dict:
    """Pass 2: Review transcription against the original image and fix errors."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=REVIEW_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": f"Here is the transcription to review:\n\n{markdown}"},
            ],
        }],
    )

    raw = response.content[0].text
    # Strip code fences if present
    raw = re.sub(r"^```(?:json)?\s*\n", "", raw)
    raw = re.sub(r"\n```\s*$", "", raw)

    try:
        result = json.loads(raw)
        return {
            "markdown": result.get("markdown", markdown),
            "changes": result.get("changes", []),
        }
    except json.JSONDecodeError:
        print(f"Warning: Could not parse review response as JSON, using original.", file=sys.stderr)
        return {"markdown": markdown, "changes": []}


def git(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=REPO_ROOT, check=True, **kwargs)


def process_image(client: anthropic.Anthropic, image_path: Path) -> dict:
    print(f"Converting: {image_path.name}", file=sys.stderr)

    # Read and encode image once
    image_data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    media_type = MEDIA_TYPES.get(image_path.suffix.lower(), "image/jpeg")

    # Pass 1: Transcribe
    print(f"  Pass 1: Transcribing...", file=sys.stderr)
    markdown = transcribe_image(client, image_data, media_type)

    # Strip code fences if present
    markdown = re.sub(r"^```\w*\n", "", markdown)
    markdown = re.sub(r"\n```$", "", markdown)

    # Pass 2: Review and fix
    print(f"  Pass 2: Reviewing...", file=sys.stderr)
    review = review_transcription(client, image_data, media_type, markdown)
    markdown = review["markdown"]
    changes = review["changes"]

    if changes:
        print(f"  Made {len(changes)} correction(s).", file=sys.stderr)
    else:
        print(f"  No corrections needed.", file=sys.stderr)

    title = extract_title(markdown)
    slug = slugify(title)
    branch = f"recipe/{slug}"

    # Start a clean branch from main for this recipe
    git(["checkout", "main"])
    git(["checkout", "-b", branch])

    # Rename the image to match the recipe slug
    new_image_name = f"{slug}{image_path.suffix.lower()}"
    new_image_path = image_path.parent / new_image_name
    if new_image_path != image_path:
        git(["mv", str(image_path), str(new_image_path)])
        print(f"  Renamed: {image_path.name} -> {new_image_name}", file=sys.stderr)

    # Update the original_skann field in markdown
    markdown = markdown.replace("FILENAME", new_image_name)
    markdown = re.sub(
        r'original_skann:\s*"skannar/[^"]*"',
        f'original_skann: "skannar/{new_image_name}"',
        markdown,
    )

    # Write and stage the markdown file
    OPPSKRIFTER_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OPPSKRIFTER_DIR / f"{slug}.md"
    md_path.write_text(markdown, encoding="utf-8")
    git(["add", str(md_path)])
    print(f"  Created: {md_path.name}", file=sys.stderr)

    # Commit and push
    git(["commit", "-m", f"Add recipe: {title}\n\nCo-Authored-By: Claude <noreply@anthropic.com>"])
    git(["push", "origin", branch])
    print(f"  Pushed branch: {branch}", file=sys.stderr)

    # Return to main before processing next image
    git(["checkout", "main"])

    return {
        "title": title,
        "slug": slug,
        "branch": branch,
        "image": image_path.name,
        "changes": changes,
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
