"""Extract searchable metadata from scanned recipe images using the Claude API.

Single pass per scan: classify (title, category, tags) and produce a rough
transcription used only for search. The original scanned image is what readers
see on the site and is the authoritative recipe — the transcription is search
fodder and does NOT need to be accurate.

For each new scan the script renames the image to a slug, writes a markdown file
into the Astro content collection, and stages both. All new recipes are committed
once, directly to main (no per-recipe branches or PRs). The workflow pushes and
triggers a deploy.

Use --dry-run to print the extracted metadata and intended markdown for one or
more images without touching git or the filesystem.
"""

import anthropic
import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

CATEGORIES = [
    "Bakverk",
    "Middag",
    "Supper og gryter",
    "Fisk og sjømat",
    "Dessert",
    "Frukost",
    "Drikke og saft",
    "Sylting og konservering",
    "Tradisjonelt og høgtid",
]

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = f"""You are an archivist digitising a grandmother's handwritten Norwegian recipes so they can be searched in an online archive.

The scanned image is what readers will see and is the authoritative recipe — you are NOT producing a clean, corrected recipe. Your only job is to make each scan findable through search. Broad recall matters; accuracy does not. Transcription errors are fine because the transcription is never shown as the recipe.

From the image, produce:
1. tittel: a short title in Nynorsk naming the dish. Guess if it is unclear.
2. kategori: the single best-fitting category from this list: {", ".join(CATEGORIES)}.
3. tags: 3-8 short lowercase Nynorsk keywords someone might search for — the dish name, the main ingredients, dialect or alternative names, and closely related dishes (e.g. for lefse: "lefse", "potet", "mjol", "flatbraud", "baking").
4. transkripsjon: a rough, best-effort plain reading of everything written on the scan (ingredients and method). Expand shorthand and dialect into full searchable words, and guess liberally at unclear handwriting rather than stalling. Mark genuinely illegible fragments with [ulesleg]. Because this text is only used for search, err on the side of including more searchable words.

Write everything in Nynorsk."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tittel": {"type": "string"},
        "kategori": {"type": "string", "enum": CATEGORIES},
        "tags": {"type": "array", "items": {"type": "string"}},
        "transkripsjon": {"type": "string"},
    },
    "required": ["tittel", "kategori", "tags", "transkripsjon"],
    "additionalProperties": False,
}

ROTATION_PROMPT = (
    "Above are four versions (A, B, C, D) of the same scanned handwritten recipe, "
    "each rotated differently. Exactly one is upright: the lines of handwriting run "
    "horizontally and read naturally left to right, top to bottom. "
    "Which one is upright?"
)

ROTATION_SCHEMA = {
    "type": "object",
    "properties": {"opprett": {"type": "string", "enum": ["A", "B", "C", "D"]}},
    "required": ["opprett"],
    "additionalProperties": False,
}

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
    return text.strip("-") or "oppskrift"


def unique_slug(base: str, taken: set[str], suffix: str) -> str:
    """Return a slug not already used as <slug>.md or <slug><suffix> on disk or in this batch."""
    slug = base
    n = 2
    while (
        slug in taken
        or (OPPSKRIFTER_DIR / f"{slug}.md").exists()
        or (SKANNAR_DIR / f"{slug}{suffix}").exists()
    ):
        slug = f"{base}-{n}"
        n += 1
    taken.add(slug)
    return slug


def load_upright(image_path: Path) -> tuple[bytes, bool]:
    """Return image bytes with EXIF orientation baked in as real pixels.

    Phone cameras often store a photo sideways with an EXIF "rotate me" flag.
    Baking the rotation in makes the scan display upright in every viewer and
    lets Claude read it the right way up. Returns (bytes, rotated). When the
    orientation is missing or already upright (1) the original bytes are
    returned unchanged — no re-encode, no quality loss.
    """
    raw = image_path.read_bytes()
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(raw))
        orientation = img.getexif().get(0x0112)  # EXIF Orientation tag
        if orientation in (None, 1):
            return raw, False
        upright = ImageOps.exif_transpose(img)  # applies rotation, drops the tag
        buf = io.BytesIO()
        fmt = (img.format or "JPEG").upper()
        save_kwargs = {"quality": 95} if fmt in ("JPEG", "WEBP") else {}
        upright.save(buf, format=fmt, **save_kwargs)
        return buf.getvalue(), True
    except Exception as exc:  # never let orientation handling block ingestion
        print(f"  Could not normalise orientation for {image_path.name}: {exc}", file=sys.stderr)
        return raw, False


# Downscaled copies served by the site: thumb for card grids / search results,
# web for the inline scan on the detail page. The full original is only loaded
# in the zoom view.
DERIVATIVE_SPECS = {
    "thumb": {"max_px": 640, "quality": 72},
    "web": {"max_px": 1600, "quality": 80},
}


def make_derivatives(image_bytes: bytes, name: str) -> None:
    """Write and stage downscaled copies under skannar/thumb/ and skannar/web/."""
    from PIL import Image

    for kind, spec in DERIVATIVE_SPECS.items():
        out_dir = SKANNAR_DIR / kind
        out_dir.mkdir(exist_ok=True)
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail((spec["max_px"], spec["max_px"]))  # in place, keeps aspect ratio
        out = out_dir / name
        if out.suffix.lower() in (".jpg", ".jpeg") and img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out, quality=spec["quality"])
        git(["add", str(out)])


def rotate_bytes(image_bytes: bytes, degrees_cw: int) -> bytes:
    """Rotate image pixels clockwise by 90/180/270 degrees and re-encode."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    fmt = (img.format or "JPEG").upper()
    rotated = img.rotate(-degrees_cw, expand=True)  # PIL rotates CCW; negate for CW
    buf = io.BytesIO()
    save_kwargs = {"quality": 95} if fmt in ("JPEG", "WEBP") else {}
    rotated.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def detect_rotation(client: anthropic.Anthropic, image_bytes: bytes) -> int:
    """Return how many degrees clockwise a scan must rotate to read upright.

    Shows all four candidate rotations side by side and asks which one is
    upright. Recognition is far more reliable than asking the model to mentally
    rotate a single image — direction confusion there ("is rotated 90" vs
    "rotate by 90") left sideways scans upside down.
    """
    from PIL import Image

    letters = ["A", "B", "C", "D"]
    degrees = [0, 90, 180, 270]

    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((512, 512))  # small variants keep the request cheap

    content = []
    for letter, deg in zip(letters, degrees):
        variant = img.rotate(-deg, expand=True)  # variant = original rotated deg CW
        buf = io.BytesIO()
        variant.save(buf, format="JPEG", quality=70)
        data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        content.append({"type": "text", "text": f"Bilde {letter}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({"type": "text", "text": ROTATION_PROMPT})

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        output_config={"format": {"type": "json_schema", "schema": ROTATION_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    # The chosen variant was made by rotating deg CW, so deg is the fix itself.
    return degrees[letters.index(json.loads(text)["opprett"])]


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
        # Only top-level scans count — thumb/ and web/ hold generated derivatives.
        if p.suffix.lower() in MEDIA_TYPES and p.exists() and p.parent == SKANNAR_DIR:
            paths.append(p)
    return paths


def classify_image(client: anthropic.Anthropic, image_data: str, media_type: str) -> dict:
    """Single pass: extract search metadata + a rough transcription as JSON."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": "Extract search metadata and a rough transcription from this scanned recipe."},
            ],
        }],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def build_markdown(result: dict, image_name: str) -> str:
    def q(s: str) -> str:
        return s.replace('"', "'").strip()

    tags = ", ".join(f'"{q(t)}"' for t in result["tags"])
    # Which book the scan comes from (id in the boker collection), set via the
    # workflow's kjelde input when a batch is dispatched.
    kjelde = os.environ.get("KJELDE", "").strip()
    kjelde_line = f'kjelde: "{q(kjelde)}"\n' if kjelde else ""
    return (
        "---\n"
        f'tittel: "{q(result["tittel"])}"\n'
        f"tags: [{tags}]\n"
        f'kategori: "{q(result["kategori"])}"\n'
        f"dato: {date.today().isoformat()}\n"
        f'original_skann: "skannar/{image_name}"\n'
        f"{kjelde_line}"
        "---\n\n"
        f"{result['transkripsjon'].strip()}\n"
    )


def git(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("stdout", subprocess.DEVNULL)
    return subprocess.run(["git"] + args, cwd=REPO_ROOT, check=True, **kwargs)


def process_image(client: anthropic.Anthropic, image_path: Path, taken: set[str], dry_run: bool) -> bool:
    print(f"Processing: {image_path.name}", file=sys.stderr)
    image_bytes, rotated = load_upright(image_path)

    # Straighten photos taken sideways BEFORE classifying, so the transcription
    # is read from an upright scan (no EXIF flag to go on — the four-way check
    # judges from the handwriting direction).
    try:
        degrees = detect_rotation(client, image_bytes)
    except Exception as exc:
        print(f"  Rotation check failed for {image_path.name}, keeping as-is: {exc}", file=sys.stderr)
        degrees = 0
    if degrees:
        try:
            image_bytes = rotate_bytes(image_bytes, degrees)
            rotated = True
            print(f"  Rotating {degrees} deg clockwise (handwriting was sideways)", file=sys.stderr)
        except Exception as exc:
            print(f"  Could not rotate {image_path.name}: {exc}", file=sys.stderr)

    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    media_type = MEDIA_TYPES.get(image_path.suffix.lower(), "image/jpeg")

    try:
        result = classify_image(client, image_data, media_type)
    except Exception as exc:  # keep one bad scan from killing the whole batch
        print(f"  Failed to classify {image_path.name}: {exc}", file=sys.stderr)
        return False

    suffix = image_path.suffix.lower()
    slug = unique_slug(slugify(result["tittel"]), taken, suffix)
    new_image_name = f"{slug}{suffix}"
    markdown = build_markdown(result, new_image_name)

    if dry_run:
        print(f"\n=== {image_path.name} -> {slug} ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("--- markdown ---")
        print(markdown)
        return True

    # Write the (upright) image under the slug name and stage the change.
    # Writing the bytes covers both the rotated case (re-encoded) and the plain
    # rename (byte-identical); staging the old path records the deletion.
    new_image_path = image_path.parent / new_image_name
    new_image_path.write_bytes(image_bytes)
    git(["add", str(new_image_path)])
    try:
        make_derivatives(image_bytes, new_image_name)
    except Exception as exc:
        print(f"  Could not make derivatives for {new_image_name}: {exc}", file=sys.stderr)
    if new_image_path != image_path:
        image_path.unlink(missing_ok=True)
        git(["add", str(image_path)])
    action = "Rotated + saved" if rotated else "Saved"
    print(f"  {action}: {image_path.name} -> {new_image_name}", file=sys.stderr)

    OPPSKRIFTER_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OPPSKRIFTER_DIR / f"{slug}.md"
    md_path.write_text(markdown, encoding="utf-8")
    git(["add", str(md_path)])
    print(f"  Wrote: {md_path.name} ({result['kategori']})", file=sys.stderr)
    return True


def fix_rotation(client: anthropic.Anthropic, dry_run: bool) -> None:
    """Repair pass: check every scan in the archive and rotate the sideways ones.

    Uses the direction of the handwriting (judged by Claude) since phone photos
    of sideways paper carry no EXIF orientation to correct from.
    """
    images = sorted(p for p in SKANNAR_DIR.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_TYPES)
    print(f"Checking rotation of {len(images)} scan(s)...", file=sys.stderr)
    fixed = 0
    for p in images:
        raw, exif_rotated = load_upright(p)
        try:
            degrees = detect_rotation(client, raw)
        except Exception as exc:
            print(f"  Failed rotation check for {p.name}: {exc}", file=sys.stderr)
            continue
        if degrees == 0 and not exif_rotated:
            print(f"  OK: {p.name}", file=sys.stderr)
            continue
        print(f"  Rotating {p.name}: {degrees} deg clockwise", file=sys.stderr)
        if dry_run:
            fixed += 1
            continue
        if degrees:
            raw = rotate_bytes(raw, degrees)
        p.write_bytes(raw)
        git(["add", str(p)])
        try:  # derivatives must match the corrected original
            make_derivatives(raw, p.name)
        except Exception as exc:
            print(f"  Could not refresh derivatives for {p.name}: {exc}", file=sys.stderr)
        fixed += 1

    if dry_run:
        print(f"Dry run: {fixed} scan(s) would be rotated.", file=sys.stderr)
        return
    if fixed == 0:
        print("All scans already upright; nothing to commit.", file=sys.stderr)
        return
    git(["commit", "-m", f"Fix rotation of {fixed} scan(s)\n\nCo-Authored-By: Claude <noreply@anthropic.com>"])
    print(f"Committed rotation fixes for {fixed} scan(s).", file=sys.stderr)


def make_all_derivatives(dry_run: bool) -> None:
    """Backfill pass (no API calls): generate missing thumb/web copies for every scan."""
    images = sorted(p for p in SKANNAR_DIR.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_TYPES)
    made = 0
    for p in images:
        missing = [k for k in DERIVATIVE_SPECS if not (SKANNAR_DIR / k / p.name).exists()]
        if not missing:
            continue
        print(f"  Deriving {'/'.join(missing)} for {p.name}", file=sys.stderr)
        if dry_run:
            made += 1
            continue
        try:
            make_derivatives(p.read_bytes(), p.name)
            made += 1
        except Exception as exc:
            print(f"  Failed derivatives for {p.name}: {exc}", file=sys.stderr)

    if dry_run:
        print(f"Dry run: {made} scan(s) would get derivatives.", file=sys.stderr)
        return
    if made == 0:
        print("All derivatives present; nothing to commit.", file=sys.stderr)
        return
    git(["commit", "-m", f"Generate thumb/web derivatives for {made} scan(s)\n\nCo-Authored-By: Claude <noreply@anthropic.com>"])
    print(f"Committed derivatives for {made} scan(s).", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print results without touching git or files.")
    parser.add_argument("--fix-rotation", action="store_true",
                        help="Check every existing scan and rotate the ones whose handwriting is sideways.")
    parser.add_argument("--derivatives", action="store_true",
                        help="Generate missing thumb/web downscaled copies for every scan (no API calls).")
    args = parser.parse_args()

    if args.fix_rotation:
        fix_rotation(anthropic.Anthropic(), args.dry_run)
        return

    if args.derivatives:
        make_all_derivatives(args.dry_run)
        return

    images = get_new_images()
    if not images:
        print("No new images to process.", file=sys.stderr)
        return

    client = anthropic.Anthropic()
    taken: set[str] = set()
    processed = 0
    for image_path in images:
        if process_image(client, image_path, taken, args.dry_run):
            processed += 1

    if args.dry_run:
        print(f"\nDry run complete: {processed}/{len(images)} image(s) processed.", file=sys.stderr)
        return

    if processed == 0:
        print("No images processed successfully; nothing to commit.", file=sys.stderr)
        return

    git(["commit", "-m", f"Add {processed} scanned recipe(s) to the archive\n\nCo-Authored-By: Claude <noreply@anthropic.com>"])
    print(f"Committed {processed} recipe(s) to the current branch.", file=sys.stderr)


if __name__ == "__main__":
    main()
