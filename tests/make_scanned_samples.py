"""Generate scanned-looking PDFs (image only, no text layer) for manual OCR checks."""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

SAMPLES = {
    "Certified ID.pdf": [
        "REPUBLIC OF SOUTH AFRICA",
        "IDENTITY CARD",
        "Surname",
        "HLUNGWANE",
        "Names",
        "SINGITA",
        "Sex: F   Nationality: RSA",
        "Identity Number",
        "030812 1234 08 9",
        "Date of Birth: 12 AUG 2003",
    ],
    "BBBE certification .pdf": [
        "BBBE Certification: Affidavit to Confirm Unemployment",
        "I hereby confirm that I am unemployed and have not previously",
        "participated in any or been employed as part of any funded",
        "Programme / or SETA funded programme.",
    ],
    "Declaration of criminal record status.pdf": [
        "AFFIDAVIT: DECLARATION OF CRIMINAL RECORD STATUS",
        "I, the undersigned:",
        "Full Names: SINGITA HLUNGWANE",
        "Identity Number: 0308121234089",
        "Residential Address: 6 Gardens Street",
        "do hereby declare that I have no criminal record.",
    ],
}


def render(lines, path):
    img = Image.new("L", (1240, 1754), 245)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    y = 120
    for line in lines:
        draw.text((90, y), line, fill=40, font=font)
        y += 70
    img.convert("RGB").save(path, "PDF", resolution=200)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, lines in SAMPLES.items():
        render(lines, os.path.join(OUT_DIR, name))
    print(f"wrote {len(SAMPLES)} sample PDFs to {OUT_DIR}")


if __name__ == "__main__":
    sys.exit(main())
