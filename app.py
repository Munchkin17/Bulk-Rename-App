import os
import re
import io
import zipfile
import warnings
from difflib import SequenceMatcher

import pypdf
import streamlit as st
from PIL import Image

APP_VERSION = "2026-08-18.1"

# Large scanned documents are often legitimately high-resolution; suppress the
# PIL decompression-bomb warning for this app so OCR can continue without noise.
Image.MAX_IMAGE_PIXELS = None
warnings.filterwarnings("ignore", message=".*decompression bomb.*", category=UserWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="PIL.*")
try:
    warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)
except AttributeError:
    pass

# ── Shared utilities ─────────────────────────────────────────────────────────[...]

def _extract_text(uploaded_file) -> str:
    reader = pypdf.PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"
    return text
 
 
def _sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
 
 
def _extract_pdfs_from_zip(zip_upload) -> list:
    """Extract all PDFs from an uploaded ZIP and return as file-like objects."""
    pdfs = []
    with zipfile.ZipFile(zip_upload) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".pdf") and not name.startswith("__MACOSX"):
                data = zf.read(name)
                buf = io.BytesIO(data)
                buf.name = os.path.basename(name)
                buf.folder = os.path.dirname(name)
                pdfs.append(buf)
    return pdfs
 
 
def _extract_all_from_zip(zip_upload) -> list:
    """Extract all supported files from an uploaded ZIP and return as file-like objects."""
    supported = (".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png", ".tiff", ".tif")
    files = []
    with zipfile.ZipFile(zip_upload) as zf:
        for name in zf.namelist():
            if any(name.lower().endswith(ext) for ext in supported) and not name.startswith("__MACOSX"):
                data = zf.read(name)
                buf = io.BytesIO(data)
                buf.name = os.path.basename(name)
                buf.folder = os.path.dirname(name)
                files.append(buf)
    return files
 
 
def _render_results(logs, zip_buffer, renamed, skipped, errors, zip_name):
    skipped_details = [(logs[i].replace("⊘ Skipped: ", ""), logs[i+1].replace("  Reason: ", ""))
                       for i in range(len(logs) - 1)
                       if logs[i].startswith("⊘ Skipped:") and logs[i+1].startswith("  Reason:")]
    if skipped_details:
        st.warning(f"⚠️ {len(skipped_details)} file(s) could not be renamed:")
        for fname, reason in skipped_details:
            st.write(f"- **{fname}**: {reason}")
 
    st.write("📊 Summary:")
    st.write(f"  Renamed: {renamed}")
    st.write(f"  Skipped: {skipped}")
    st.write(f"  Errors:  {errors}")
    st.write(f"  Total:   {renamed + skipped + errors}")
    if renamed > 0:
        st.download_button("⬇️ Download Renamed PDFs", data=zip_buffer, file_name=zip_name, mime="application/zip")
 
 
# ── Completion Certificates ───────────────────────────────────────────────────
 
DEFAULT_COMPLETION_TEMPLATE = "{first_name}_{last_name}_{id}_Completionoftrainingcertificate.pdf"
 
 
def _build_filename(template: str, values: dict) -> str:
    try:
        result = template.format_map(values)
    except Exception as exc:
        raise ValueError(f"Template formatting error: {exc}") from exc
    result = _sanitize(result)
    if not result.lower().endswith(".pdf"):
        result += ".pdf"
    return result
 
 
def _match_completion(text: str):
    """Try progressively looser patterns to extract name and ID from completion cert text."""
    # Pass 1: strict — name directly before 13-digit ID after 'issued to'
    match = re.search(r'issued to\s+([A-Za-z]+(?:\s[A-Za-z]+){1,2})\s+(\d{13})', text, re.I)
    if match:
        return match.group(1).strip(), match.group(2), None
 
    # Pass 2: find name and ID anywhere in text independently
    name_match = re.search(r'issued to\s+([A-Za-z]+(?:\s[A-Za-z]+){1,2})', text, re.I)
    id_match = re.search(r'\b(\d{13})\b', text)
 
    if name_match and id_match:
        return name_match.group(1).strip(), id_match.group(1), None
 
    # Determine specific reason for failure
    if not re.search(r'issued to', text, re.I):
        reason = "'issued to' phrase not found in document"
    elif not name_match:
        reason = "name could not be extracted after 'issued to'"
    elif not id_match:
        reason = "no 13-digit ID number found in document"
    else:
        reason = "name and ID found separately but could not be matched together"
 
    return None, None, reason
 
 
def process_completion_certs(uploaded_files, template: str):
    renamed, skipped, errors, logs = 0, 0, 0, []
    zip_buffer = io.BytesIO()
 
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in uploaded_files:
            filename = f.name
            try:
                f.seek(0)
                text = _extract_text(f)
                if not text.strip():
                    logs.append(f"⊘ Skipped: {filename}")
                    logs.append(f"  Reason: PDF appears to be empty or text could not be extracted (possibly a scanned image)")
                    skipped += 1
                    continue
 
                full_name, id_number, reason = _match_completion(text)
                if full_name and id_number:
                    parts = full_name.split()
                    first_name, last_name = parts[0], parts[-1]
                    try:
                        new_name = _build_filename(template, {
                            "first_name": first_name, "last_name": last_name,
                            "id": id_number, "original_name": filename,
                            "original_basename": os.path.splitext(filename)[0],
                        })
                    except ValueError as exc:
                        logs.append(f"✗ Invalid template: {exc}")
                        errors += 1
                        continue
                    folder_name = _sanitize(f"{first_name} {last_name}")
                    f.seek(0)
                    zf.writestr(f"{folder_name}/{new_name}", f.read())
                    logs.append(f"✓ Renamed: {filename} -> {folder_name}/{new_name}")
                    renamed += 1
                else:
                    logs.append(f"⊘ Skipped: {filename}")
                    logs.append(f"  Reason: {reason}")
                    skipped += 1
            except Exception as e:
                logs.append(f"✗ Error: {filename}: {e}")
                errors += 1
 
    zip_buffer.seek(0)
    return logs, zip_buffer, renamed, skipped, errors
 
 
def page_completion():
    st.header("Completion Certificate Renamer")
    st.write("Renames certificates by extracting the name and 13-digit ID number.")
 
    upload_mode = st.radio("Upload mode:", ["Individual files", "Folder (ZIP)"], horizontal=True, key="mode_completion")
    if upload_mode == "Individual files":
        uploaded_files = st.file_uploader("Upload PDF files", type="pdf", accept_multiple_files=True, key="completion_files")
    else:
        zip_file = st.file_uploader("Upload a ZIP of your folder", type="zip", key="completion_zip")
        uploaded_files = _extract_pdfs_from_zip(zip_file) if zip_file else []
 
    template = st.text_input(
        "Filename template:", DEFAULT_COMPLETION_TEMPLATE,
        help="Placeholders: {first_name}, {last_name}, {id}, {original_name}, {original_basename}",
    )
    st.caption("Placeholders: {first_name}, {last_name}, {id}, {original_name}, {original_basename}")
 
    if st.button("Rename PDFs", key="btn_completion"):
        if not uploaded_files:
            st.error("Please upload at least one PDF file.")
        else:
            with st.spinner("Processing..."):
                logs, zip_buffer, renamed, skipped, errors = process_completion_certs(uploaded_files, template)
            _render_results(logs, zip_buffer, renamed, skipped, errors, "completion_renamed.zip")
 
 
# ── Coursera Certificates ─────────────────────────────────────────────────────
 
def _normalize_coursera_text(text: str) -> str:
    # Normalize line breaks and multiple spaces, but preserve single spaces between names
    normalized = re.sub(r'[\r\n]+', ' ', text)
    return re.sub(r' {2,}', ' ', normalized).strip()


def _match_coursera(normalized: str):
    """Extract name and course from Coursera cert text using progressively looser patterns.
    
    Key insight: the name and course title are almost always in "NAME has successfully 
    completed COURSE_TITLE" structure. We extract both if this structure exists.
    """
    # Try to find a candidate name before "has successfully completed"
    # Support multiple capitalization patterns: "John Smith", "JOHN SMITH", "john smith"
    # Pattern: 1-4 words (letters only, 2+ chars each) before "has successfully completed"
    # Use word boundaries and case-insensitive matching, but exclude common certificate preambles
    
    # First, try to find "has successfully completed" to anchor our search
    completed_match = re.search(r'has\s+successfully\s+completed', normalized, re.I)
    if not completed_match:
        return None, None, "'successfully completed' phrase not found — may not be a Coursera certificate"
    
    # Look backwards from "has successfully completed" to find the name
    # Name is typically the last 2-4 words before this phrase
    text_before = normalized[:completed_match.start()].strip()
    
    # Extract candidate: last 2-4 alphabetic words, excluding common certificate preamble words
    preamble_words = {'this', 'is', 'to', 'certify', 'that', 'hereby', 'certificate', 'coursera'}
    
    # Split and work backwards to find name words
    words = text_before.split()
    name_words = []
    for word in reversed(words):
        # Only accept alphabetic words with 2+ letters
        if re.match(r'^[A-Za-z]{2,}$', word) and word.lower() not in preamble_words:
            name_words.insert(0, word.capitalize())
            if len(name_words) == 4:  # Max 4 words for a name
                break
        else:
            # Stop when we hit a non-name word (unless we haven't collected any name words yet)
            if name_words:
                break
    
    if len(name_words) < 2:
        return None, None, "no recognisable candidate name found in document"
    
    full_name = ' '.join(name_words)
    
    # Extract course name after "has successfully completed"
    # Try multiple patterns (course may be a specialization, single course, etc.)
    start_pos = completed_match.end()
    text_after = normalized[start_pos:].strip()
    
    # Pattern 1: course title followed by "an online course", "specialization", or end-of-line
    course_patterns = [
        r'(?:the\s+)?online\s+course\s+([A-Za-z][A-Za-z\s&:\-]+?)(?:\s+an\s+online|[.!]|$)',
        r'([A-Za-z][A-Za-z\s&:\-]+?)\s+an\s+online\s+course',
        r'(?:the\s+)?online\s+Specialization\s+([A-Za-z][A-Za-z\s&:\-]+?)(?:[.!]|$)',
        r'([A-Za-z][A-Za-z\s&:\-]+?)\s+Specialization',
        r'([A-Za-z][A-Za-z\s&:\-]+?)(?:\s+(?:Certificate|Specialization))?(?:[.!]|$)',
    ]
    
    for pattern in course_patterns:
        match = re.search(pattern, text_after, re.I)
        if match:
            course_title = match.group(1).strip()
            # Clean up course title: remove trailing noise
            course_title = re.sub(r'\s+(?:Certificate|Thank|This|Those|Verify|Course).*$', '', course_title, flags=re.I)
            course_title = re.sub(r'[^\w\s&:\-]', '', course_title).strip()
            # Reject if it's too short or looks like certificate boilerplate
            if len(course_title) > 2 and course_title.lower() not in {'the', 'and', 'for', 'from'}:
                return full_name, course_title, None
    
    # If we found a name but no course, report it as no match
    return None, None, "course title could not be extracted after 'successfully completed'"


def _extract_name_from_coursera_filename(filename: str) -> tuple:
    """Extract first name and last name from Coursera certificate filename.
    
    Assumes filenames follow pattern: "FirstName LastName [CourseTopic].pdf"
    Returns: (first_name, last_name) with proper capitalization, or (None, None)
    """
    # Remove extension
    name_part = os.path.splitext(filename)[0]
    
    # Split by spaces
    words = name_part.split()
    
    # Collect capitalized words that look like name parts (2+ letters, only alphabetic)
    name_words = []
    for word in words:
        # Stop at common course keywords
        if word.lower() in {'and', 'or', 'the', 'a', 'an', 'essentials', 'google', 'course', 'certificate', 'coursera'}:
            break
        # Accept alphabetic words with 2+ letters
        if re.match(r'^[A-Za-z]{2,}$', word):
            name_words.append(word.capitalize())
        else:
            # Stop if we hit a non-alphabetic word (unless we have name words already)
            if name_words:
                break
    
    # Need at least 2 words for a name
    if len(name_words) >= 2:
        return (name_words[0], name_words[1])
    
    return (None, None)


def process_coursera_certs(uploaded_files):
    """Process Coursera certificates using bulk_pdfCoursera.py logic."""
    renamed, skipped, errors, logs = 0, 0, 0, []
    zip_buffer = io.BytesIO()
 
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in uploaded_files:
            filename = f.name
            try:
                f.seek(0)
                reader = pypdf.PdfReader(f)
                text = ""

                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"

                if not text.strip():
                    logs.append(f"⊘ Skipped: {filename}")
                    logs.append(f"  Reason: PDF appears to be empty or text could not be extracted (possibly a scanned image)")
                    skipped += 1
                    continue

                # Normalize text as in bulk_pdfCoursera.py (preserve name spaces)
                normalized = re.sub(r'[\r\n]+', ' ', text)
                normalized = re.sub(r' {2,}', ' ', normalized)

                # Pattern 1: [Name][Course]an online course...has successfully completed
                match = re.search(
                    r'([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})([A-Z].+?)(?:an online course|a non-?online)',
                    normalized
                )

                # Pattern 2 (Specialization): [Name]has successfully completed the online Specialization[Course]
                if not match:
                    match = re.search(
                        r'([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})has successfully completed the online Specialization([A-Z][A-Za-z ]{2,50}?)(?:Those|Verify|\d|$)',
                        normalized
                    )

                if match:
                    full_name = match.group(1).strip().split()
                    first_name = full_name[0]
                    last_name = full_name[-1]
                    course_name = match.group(2).strip()
                    course_name = re.sub(r'[\\/*?:"<>|]', '', course_name).strip()

                    new_name = f"{first_name} {last_name} - {course_name}.pdf"
                    folder_name = _sanitize(f"{first_name} {last_name}")
                    f.seek(0)
                    zf.writestr(f"{folder_name}/{new_name}", f.read())
                    logs.append(f"✓ Renamed: {filename} -> {folder_name}/{new_name}")
                    renamed += 1
                else:
                    logs.append(f"⊘ Skipped: {filename} (could not extract name or course)")
                    logs.append(f"  DEBUG - Normalized snippet:\n{normalized[:300]}\n")
                    skipped += 1

            except Exception as e:
                logs.append(f"✗ Error: {filename}: {e}")
                errors += 1
 
    zip_buffer.seek(0)
    return logs, zip_buffer, renamed, skipped, errors
 
 
def page_coursera():
    st.header("Coursera Certificate Renamer")
    st.write("Renames Coursera certificates by extracting the name and course title.")
 
    upload_mode = st.radio("Upload mode:", ["Individual files", "Folder (ZIP)"], horizontal=True, key="mode_coursera")
    if upload_mode == "Individual files":
        uploaded_files = st.file_uploader("Upload PDF files", type="pdf", accept_multiple_files=True, key="coursera_files")
    else:
        zip_file = st.file_uploader("Upload a ZIP of your folder", type="zip", key="coursera_zip")
        uploaded_files = _extract_pdfs_from_zip(zip_file) if zip_file else []
 
    if st.button("Rename PDFs", key="btn_coursera"):
        if not uploaded_files:
            st.error("Please upload at least one PDF file.")
        else:
            with st.spinner("Processing..."):
                logs, zip_buffer, renamed, skipped, errors = process_coursera_certs(uploaded_files)
            _render_results(logs, zip_buffer, renamed, skipped, errors, "coursera_renamed.zip")
 
 
# ── SharePoint Documents ──────────────────────────────────────────────────────
 
DOC_TYPES = {
    "BA":                        ["beneficiary agreement"],
    "Cellphone Affidavit":       ["cellphone affidavit", "cell phone affidavit"],
    "Criminal Record Affidavit": ["declaration of criminal record status", "i am a participant in a programme administrated by capaciti, a division of uvu africa npc, and i am required to declare[...],"],
    "Declaration":               ["declare that the information supplied in my curriculum vitae and application link to capaciti", "uvuafrica.com"],
    "EEA1":                      ["department of labour", "declaration by employee"],
    "ID":                        ["national identity ca", "republic of south afri", "identification act", "identity number", "identity card"],
    "MIE":                       ["processing notification - background screening request"],
    "Social Media Form":         ["consent/release form for news media", "naspers labs", "authorize naspers"],
    "Completion Certificate":    ["document name: capaciti ben", "document name: capaciti bene"],
    "Attendance Register":       ["attendance register", "attendance sheet", "attendance list"],
    "Qualification":             ["certificate of achievement", "diploma awarded", "degree conferred"],
    "Unemployment Affidavit":    ["bbbe certification", "affidavit.*unemployment", "confirm that.*unemployed"],
}
 
# Filename fragment -> doc type (checked before text keywords)
_FILENAME_DOC_TYPE_MAP = [
    ("completion certificate",    "Completion Certificate"),
    ("cellphone affidavit",       "Cellphone Affidavit"),
    ("cell phone affidavit",      "Cellphone Affidavit"),
    ("criminal record affidavit", "Criminal Record Affidavit"),
    ("criminal record",           "Criminal Record Affidavit"),
    ("unemployment affidavit",    "Unemployment Affidavit"),
    ("confirmation of unemployment", "Unemployment Affidavit"),
    ("bbbe",                      "Unemployment Affidavit"),
    ("attendance register",       "Attendance Register"),
    ("social media",              "Social Media Form"),
    ("declaration",               "Declaration"),
    ("qualification",             "Qualification"),
    ("umalusi",                   "Qualification"),
    ("matric",                    "Qualification"),
    ("mie",                       "MIE"),
    ("eea1",                      "EEA1"),
    ("identity document",         "ID"),
    ("certified id",              "ID"),
    (" id ",                      "ID"),
    (" id.",                      "ID"),
]
 
 
# Detect Poppler and Tesseract paths once at import time
_POPPLER_PATH = None
for _p in [
    r"C:\Program Files\Release-26.02.0-0\poppler-26.02.0\Library\bin",
    r"C:\Program Files\poppler\Library\bin",
    r"C:\poppler\Library\bin",
]:
    if os.path.isfile(os.path.join(_p, "pdftoppm.exe")):
        _POPPLER_PATH = _p
        break

_POPPLER_PATH = _POPPLER_PATH

_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


_OCR_DPI = 300
# Page segmentation modes worth trying: 6 = uniform block, 4 = columns, 11 = sparse text.
_OCR_CONFIGS = ("--oem 1 --psm 6", "--oem 1 --psm 4", "--oem 1 --psm 11")
# A digits-only pass recovers ID numbers that the general pass reads as letters.
_OCR_DIGITS_CONFIG = "--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789 "
# A text layer shorter than this is treated as unreliable and OCR is run as well.
_MIN_TEXT_LAYER_CHARS = 400


def _ocr_image(img) -> str:
    """OCR a single page image, combining several Tesseract passes.

    Scanned affidavits and ID cards read very differently depending on the page
    segmentation mode, so every pass is kept and searched later.
    """
    import pytesseract
    from PIL import ImageOps, ImageFilter, ImageEnhance

    # Enhanced preprocessing for scanned documents:
    # 1. Convert to grayscale
    # 2. Apply adaptive histogram equalization (via ImageEnhance contrast)
    # 3. Apply sharpening to improve text clarity
    # 4. Optional: denoise or apply threshold
    gray_img = img.convert("L")
    
    # Increase contrast significantly for better text detection
    contrast_enhancer = ImageEnhance.Contrast(gray_img)
    high_contrast = contrast_enhancer.enhance(2.0)
    
    # Sharpen to make text crisper
    sharpened = high_contrast.filter(ImageFilter.SHARPEN)
    
    # Apply slight denoising via median filter to reduce noise without losing text
    denoised = sharpened.filter(ImageFilter.MedianFilter(size=3))
    
    # Final preparation: auto-contrast for any remaining uneven lighting
    prepared = ImageOps.autocontrast(denoised)

    chunks = []
    for config in _OCR_CONFIGS:
        try:
            text = pytesseract.image_to_string(prepared, config=config)
        except Exception:
            continue
        if text.strip() and text.strip() not in (c.strip() for c in chunks):
            chunks.append(text)
        # Further passes only cost time once both fields have been read
        if _find_id_candidates(text) and all(_extract_name_from_text(text)):
            return "\n".join(chunks)
    try:
        digits = pytesseract.image_to_string(prepared, config=_OCR_DIGITS_CONFIG)
    except Exception:
        digits = ""
    if digits.strip():
        chunks.append(digits)
    return "\n".join(chunks)


def _ocr_pdf_pages(file_bytes: bytes) -> list:
    from pdf2image import convert_from_bytes
    kwargs = {"poppler_path": _POPPLER_PATH} if _POPPLER_PATH else {}
    images = convert_from_bytes(file_bytes, dpi=_OCR_DPI, **kwargs)
    return [_ocr_image(img) for img in images]


def _text_layer_is_usable(text: str) -> bool:
    """A text layer is trusted only when it is long enough or already contains an ID."""
    return len(text.strip()) >= _MIN_TEXT_LAYER_CHARS and bool(_find_id_candidates(text))


def _extract_text_with_ocr(file_bytes: bytes, filename: str) -> tuple:
    """Extract (full_text, first_page_text) from PDF, Word doc, or image."""
    import pypdf
    from PIL import Image
    import pytesseract
 
    if os.path.isfile(_TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_PATH
 
    ext = os.path.splitext(filename)[1].lower()
 
    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        text = _ocr_image(Image.open(io.BytesIO(file_bytes)))
        return text, text
 
    if ext in (".docx", ".doc"):
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        text = "\n".join(p.text for p in doc.paragraphs)
        return text, text
 
    if ext == ".pdf":
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages_text = []
        for page in reader.pages:
            extracted = page.extract_text()
            pages_text.append(extracted or "")
        full_text = "\n".join(pages_text)
        if _text_layer_is_usable(full_text):
            return full_text, pages_text[0] if pages_text else ""

        # OCR scanned pages, and also pages whose embedded text layer is too poor to use
        try:
            ocr_pages = _ocr_pdf_pages(file_bytes)
        except Exception as e:
            if full_text.strip():
                return full_text, pages_text[0] if pages_text else ""
            return "", f"[OCR ERROR: {e}]"

        merged = [f"{layer}\n{ocr}".strip() for layer, ocr in
                  zip(pages_text + [""] * len(ocr_pages), ocr_pages)]
        return "\n".join(merged), merged[0] if merged else ""

    return "", ""
 
 
def _detect_doc_type(text: str, filename: str = "", first_page_text: str = "") -> tuple:
    """Return (doc_type, reason) — filename checked first, then text keywords."""
    fname_lower = filename.lower().replace("+", " ").replace("%20", " ")
    for fragment, dt in _FILENAME_DOC_TYPE_MAP:
        if fragment in fname_lower:
            return dt, None
 
    text_lower = text.lower()
    first_page_lower = (first_page_text or text).lower()
    matches = []
    for dt, keywords in DOC_TYPES.items():
        search_text = first_page_lower if dt == "BA" else text_lower
        if any(re.search(kw, search_text) for kw in keywords):
            matches.append(dt)
 
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, f"multiple document types detected: {', '.join(matches)} — manual review required"
    return "Other", None


# Words that describe the document rather than the candidate, so they can never be part of a name
_FILENAME_STOPWORDS = {
    "certified", "cert", "id", "identity", "document", "doc", "declaration", "affidavit",
    "criminal", "record", "status", "matric", "certificate", "certification", "unemployment",
    "bbbe", "bbbe", "birth", "copy", "scan", "original", "statement", "application",
    "form", "notice", "receipt", "of", "the", "and", "to", "number", "identitydocument",
    "identitycard", "declarationofcriminalrecordstatus",
    "confirmation", "confirm", "consent", "proof", "residence", "address", "bank", "banking",
    "letter", "cv", "curriculum", "vitae", "qualification", "senior", "national", "school",
    "registration", "agreement", "beneficiary", "attendance", "register", "media", "social",
    "police", "clearance", "payslip", "results", "result", "transcript", "diploma", "degree",
    "report", "signed", "final", "updated", "completion", "training", "cellphone", "phone",
    "eea1", "mie", "ba", "capaciti", "coursera", "certificates", "docs", "files", "file",
    "online", "wk", "week", "batch", "folder", "candidate", "submission", "upload",
    "umalusi", "matric", "confirmation",
}

_GENERIC_NAME_TOKENS = {
    "online", "wk", "week", "batch", "folder", "documents", "document", "files", "file",
    "bbbe", "certification", "certificate", "affidavit", "declaration", "criminal",
    "record", "status", "unemployment", "id", "identity", "umalusi", "matric",
    "confirmation",
}


def _looks_like_generic_name_candidate(value: str) -> bool:
    """Reject obvious document labels and folder names that are not a real person's name."""
    if not value:
        return True
    cleaned = re.sub(r'[^A-Za-z\s]', ' ', value).strip()
    if not cleaned:
        return True
    tokens = [t.lower() for t in cleaned.split() if t]
    if not tokens:
        return True
    if any(token in _GENERIC_NAME_TOKENS for token in tokens):
        return True
    return len(tokens) == 2 and set(tokens) <= {"online", "wk"}


def _extract_name_and_id_from_filename(filename: str) -> tuple:
    """Try to extract first name, last name and ID from the filename itself.
    Heuristics:
      - Extract a 13-digit ID if present.
      - Only return a name when the filename contains a high-quality name candidate (2-4 alphabetic tokens,
        not common document stopwords, and not containing digits). Otherwise return (None, None, id)
    """
    basename = os.path.splitext(filename)[0]
    basename = basename.replace("+", " ").replace("%20", " ")
    # Normalize separators and remove punctuation we commonly see in filenames
    s = re.sub(r'[_\-\(\)\[\],]+', ' ', basename)
    s = re.sub(r'\s+', ' ', s).strip()

    # Extract 13-digit ID if present
    id_match = re.search(r'\b(\d{13})\b', s)
    id_number = id_match.group(1) if id_match else None

    tokens = [t for t in s.split() if t]
    if not tokens:
        return None, None, id_number

    def is_stopword(token: str) -> bool:
        return token.lower() in _FILENAME_STOPWORDS

    def token_is_alpha(token: str) -> bool:
        letters = re.sub(r"[^A-Za-z]", "", token)
        return len(letters) >= 2

    best_candidate = None
    best_score = 0

    # Consider windows sized 4 down to 2 (favor multi-word names)
    for size in range(4, 1, -1):
        for i in range(0, len(tokens) - size + 1):
            window = tokens[i:i + size]
            lw = [w.lower() for w in window]

            # Reject windows containing digits or stopwords
            if any(re.search(r'\d', w) for w in window):
                continue
            if any(is_stopword(w) for w in lw):
                continue

            # Score: prefer tokens with alphabetic content and capitalization patterns
            score = 0
            for w in window:
                if token_is_alpha(w):
                    score += 2
                if re.match(r'^[A-Z][a-z]+$', w) or re.match(r'^[A-Z]{2,}$', w):
                    score += 1

            # small penalty if any token is a single character
            if any(len(re.sub(r'[^A-Za-z]', '', w)) <= 1 for w in window):
                score -= 1

            if score > best_score:
                best_score = score
                best_candidate = " ".join(window)

    # If nothing found among 2-4 windows, allow a single-token candidate only if it's high-quality
    if best_score == 0 and len(tokens) == 1:
        t = tokens[0]
        if token_is_alpha(t) and not is_stopword(t):
            best_candidate = t
            best_score = 2

    # Only accept candidate if score meets threshold and the candidate is not just a
    # generic document label masquerading as a person name.
    if best_score >= 2:
        if _looks_like_generic_name_candidate(best_candidate):
            return None, None, id_number
        parts = best_candidate.split()
        first_name = parts[0]
        last_name = parts[-1]
        return first_name, last_name, id_number

    return None, None, id_number


# ── ID number extraction ───────────────────────────────────────────────────

# Characters Tesseract commonly returns instead of a digit on scanned documents.
OCR_EQUIVALENTS = {
    "O": "0", "Q": "0", "D": "0", "U": "0",
    "I": "1", "L": "1", "J": "1",
    "Z": "2", "E": "3", "A": "4", "S": "5",
    "G": "6", "T": "7", "B": "8", "Y": "4",
}

_ID_RUN_RE = re.compile(
    r'[0-9' + ''.join(OCR_EQUIVALENTS) + r'](?:[ \-./]{0,2}[0-9' + ''.join(OCR_EQUIVALENTS) + r']){11,24}',
    re.I,
)

_ID_LABEL_RE = re.compile(r'\b(?:id|ident\w*)\s*(?:number|no|nr|card)?\s*[:\-.]?', re.I)

# How much text after an "Identity Number" label can still belong to the number
_ID_LABEL_WINDOW = 80


def _normalize_ocr_id(raw: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9]', '', raw).upper()
    return ''.join(OCR_EQUIVALENTS.get(c, c) for c in cleaned)


def _luhn_ok(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _sa_id_date_ok(digits: str) -> bool:
    month, day = int(digits[2:4]), int(digits[4:6])
    return 1 <= month <= 12 and 1 <= day <= 31


def _is_valid_sa_id(s: str) -> bool:
    """13 digits with a plausible date of birth prefix."""
    return bool(re.fullmatch(r'\d{13}', s or '')) and _sa_id_date_ok(s)


def _find_id_candidates(text: str) -> list:
    """Return [(id_number, confidence)] found in text, best first.

    Handles three levels of OCR damage: a clean 13-digit run, digits broken up by
    spaces/dashes, and digits misread as letters (only accepted when the result
    passes the South African ID checksum).
    """
    results, seen = [], set()

    def add(value, confidence):
        if _is_valid_sa_id(value) and value not in seen:
            seen.add(value)
            results.append((value, confidence))

    def scan(segment):
        for m in re.finditer(r'(?<!\d)(\d{13})(?!\d)', segment):
            add(m.group(1), "CONFIRMED")
        joined = re.sub(r'(?<=\d)[ \-./]{1,3}(?=\d)', '', segment)
        for m in re.finditer(r'(?<!\d)(\d{13})(?!\d)', joined):
            add(m.group(1), "SPACED_DIGITS")
        for run in _ID_RUN_RE.finditer(segment):
            normalized = _normalize_ocr_id(run.group(0))
            if not normalized.isdigit():
                continue
            for i in range(len(normalized) - 12):
                window = normalized[i:i + 13]
                if _luhn_ok(window):
                    add(window, "OCR_CORRECTED")

    # Text right after an "Identity Number" label is the most reliable place to look
    for label in _ID_LABEL_RE.finditer(text):
        scan(text[label.end():label.end() + _ID_LABEL_WINDOW])
    scan(text)
    return results


def _find_id_number(text: str) -> tuple:
    """Return (id_number, confidence) or (None, None)."""
    candidates = _find_id_candidates(text)
    return candidates[0] if candidates else (None, None)


# ── Name extraction ────────────────────────────────────────────────────────

_NAME_STOPWORDS = {
    "identity", "identification", "id", "number", "no", "nr", "card", "date", "of", "birth",
    "sex", "male", "female", "nationality", "status", "country", "signature", "issue", "issued",
    "republic", "south", "africa", "african", "rsa", "national", "senior", "certificate",
    "certification", "affidavit", "declaration", "unemployment", "unemployed", "hereby",
    "confirm", "undersigned", "residential", "address", "surname", "sumame", "names", "name",
    "full", "fullnames", "forenames", "the", "and", "to", "am", "do", "is", "in", "at", "a",
    "programme", "program", "seta", "funded", "employed", "participated", "previously",
    "awarded", "this", "that", "with", "for", "department", "home", "affairs", "act", "bbbe",
    "bbbee", "curriculum", "vitae", "capaciti", "uvu", "npc", "division",
    "online", "wk", "week", "work", "working", "batch", "folder", "upload",
}

_NAME_CHUNK = r"([A-Za-z][A-Za-z'\-]*(?:[ \t]+[A-Za-z][A-Za-z'\-]*){0,5})"

_NAME_PATTERNS = [
    r'(?:awarded|issued|granted|presented)\s+to\s*[:\-]?\s*(?:i\s+)?' + _NAME_CHUNK,
    r'(?:full\s*names?|fullnames?|candidate\s*name|name\s+of\s+(?:the\s+)?(?:candidate|applicant|learner))\s*[:\-]?\s*' + _NAME_CHUNK,
    r'\bI\s*[,.]\s*(?:the\s+undersigned\s*[,:.]?\s*)?' + _NAME_CHUNK,
    # Pattern for "FullNames:" or similar labels followed by name (with OCR artifacts)
    r'(?:full\s*names?|fullnames?)\s*[:\-]?\s*["\']?\s*(?:\|)?\s*' + _NAME_CHUNK,
    # Pattern for names after various labels, possibly with OCR noise
    r'(?:names?|person|individual|applicant|candidate)\s*[:\-]?\s*["\']?\s*(?:\|)?\s*' + _NAME_CHUNK,
    # Pattern for surnames/family names
    r'(?:surname|family\s+name)\s*[:\-]?\s*["\']?\s*(?:\|)?\s*([A-Za-z][A-Za-z\'\-]*)',
]

_SURNAME_RE = re.compile(r'\b(?:sur\s*name|surname|sumame|sumame|surmame|sumname|family\s+name)\b\s*[:\-.]?\s*["\']?\s*(?:\|)?\s*' + _NAME_CHUNK, re.I)
_FORENAME_RE = re.compile(r'\b(?:names|first\s*names?|fore\s*names?|given\s*names?|full\s*names?|fullnames?)\b\s*[:\-.]?\s*["\']?\s*(?:\|)?\s*' + _NAME_CHUNK, re.I)


def _clean_name_tokens(raw: str) -> list:
    """Keep the leading run of plausible name words, dropping OCR specks and labels."""
    tokens = []
    for token in re.split(r'[\s,]+', (raw or "").strip()):
        letters = re.sub(r"[^A-Za-z'\-]", "", token)
        if len(letters) < 2:
            if tokens:
                break
            continue
        # A person-name token cannot be an OCR-concatenated page of text.
        if len(letters) > 20:
            break
        if letters.lower() in _NAME_STOPWORDS:
            break
        tokens.append(letters.capitalize())
        if len(tokens) == 4:
            break
    return tokens


def _person_name_score(first_name: str, last_name: str) -> float:
    """Score an OCR name while rejecting document text and obvious OCR noise."""
    if not first_name or not last_name:
        return -1
    if _looks_like_generic_name_candidate(f"{first_name} {last_name}"):
        return -1
    words = (first_name, last_name)
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z'\-]{2,19}", word) for word in words):
        return -1
    if any(len(set(word.lower())) <= 1 for word in words):
        return -1
    vowels = sum(bool(re.search(r'[aeiouy]', word, re.I)) for word in words)
    return len(first_name) + len(last_name) + vowels * 2


def _repair_labelled_name_fragments(raw: str) -> list:
    """Repair label-scoped OCR such as ``S NGITA H LUNGW ANE`` only."""
    parts = []
    for item in re.split(r'\s+', raw or ''):
        cleaned = re.sub(r'[^A-Za-z]', '', item)
        if not cleaned:
            continue
        if cleaned.lower() in _NAME_STOPWORDS:
            break
        parts.append(cleaned)
    if (len(parts) >= 5 and len(parts[0]) == 1
            and any(len(item) == 1 for item in parts[2:])):
        return [(parts[0] + parts[1]).capitalize(),
                ''.join(parts[2:]).capitalize()]
    if len(parts) >= 4 and any(len(item) == 1 for item in parts[1:]):
        return [parts[0].capitalize(), ''.join(parts[1:]).capitalize()]
    return _clean_name_tokens(raw)


def _extract_name_from_text(text: str) -> tuple:
    """Extract (first_name, last_name) from document text, or (None, None)."""
    if not text:
        return None, None

    candidates = []

    # OCR runs several passes. Compare every labelled surname/forename result
    # instead of trusting the first (often the noisiest) pass.
    surnames = []
    for match in _SURNAME_RE.finditer(text):
        values = _clean_name_tokens(match.group(1))
        if values:
            surnames.append(values[0])
    forenames = []
    for match in _FORENAME_RE.finditer(text):
        values = _clean_name_tokens(match.group(1))
        if values:
            forenames.append(values[0])
    for first_name in forenames:
        for last_name in surnames:
            score = _person_name_score(first_name, last_name)
            if score >= 0:
                candidates.append((score + 5, first_name, last_name))

    for pattern in _NAME_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            tokens = _repair_labelled_name_fragments(match.group(1))
            if len(tokens) >= 2:
                score = _person_name_score(tokens[0], tokens[-1])
                if score >= 0:
                    candidates.append((score, tokens[0], tokens[-1]))

    if candidates:
        _, first_name, last_name = max(candidates, key=lambda item: item[0])
        return first_name, last_name

    return None, None


def _extract_name_and_id(text: str, filename: str = "", doc_type: str = "", name_to_id: dict = None) -> tuple:
    """Extract (first_name, last_name, id_number, reason) — filename takes priority."""
    first_name, last_name, id_number = _extract_name_and_id_from_filename(filename)
 
    if first_name and last_name and not id_number and doc_type == "Completion Certificate":
        # Try to resolve ID from other files processed in the same batch
        id_number = (name_to_id or {}).get((first_name.lower(), last_name.lower()))

    if not id_number:
        id_number, _ = _find_id_number(text)

    if not first_name or not last_name:
        text_first, text_last = _extract_name_from_text(text)
        if text_first and text_last:
            first_name, last_name = text_first, text_last

    if first_name and last_name and id_number:
        return first_name, last_name, id_number, None
 
    missing = []
    if not first_name or not last_name:
        missing.append("name could not be extracted")
    if not id_number:
        missing.append("no 13-digit ID number found")
    return first_name, last_name, id_number, "; ".join(missing)


# ── Batch candidate resolution helpers ─────────────────────────────────────

def _compare_partial_id(ocr_value: str, known_id: str) -> float:
    """Similarity of an OCR-damaged ID fragment to a known ID (0-1)."""
    norm = _normalize_ocr_id(ocr_value)
    if not norm:
        return 0.0
    if len(norm) >= 6 and (norm in known_id or known_id in norm):
        return 1.0
    return SequenceMatcher(None, norm, known_id).ratio()


def _name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _extract_raw_id_candidates(text: str) -> list:
    """Return plausible ID-like strings, including partial/garbled ones."""
    exact = [value for value, _ in _find_id_candidates(text)]
    if exact:
        return exact
    return [run.group(0) for run in _ID_RUN_RE.finditer(text)]


def _candidate_key(first_name: str, last_name: str) -> str:
    return f"{first_name.lower().strip()}|{last_name.lower().strip()}"


def _names_match(first_a: str, last_a: str, first_b: str, last_b: str) -> float:
    """Score two OCR-derived names; ≥ NAME_MATCH_THRESHOLD means same person."""
    last_score = _name_similarity(last_a, last_b)
    first_score = _name_similarity(first_a, first_b)
    if last_score >= 0.75 and first_score >= 0.3:
        return max(0.75, 0.6 * last_score + 0.4 * first_score)
    return 0.6 * last_score + 0.4 * first_score


NAME_MATCH_THRESHOLD = 0.75


def _best_candidate_match(first_name: str, last_name: str, candidates: dict) -> tuple:
    best_key, best_score = None, 0.0
    for key, cand in candidates.items():
        score = _names_match(first_name, last_name, cand['first_name'], cand['last_name'])
        if score > best_score:
            best_score, best_key = score, key
    return best_key, best_score


MISSING_ID_PLACEHOLDER = "IDUNKNOWN"

# Sensitive document categories should never be renamed with a placeholder ID when
# the document itself does not provide a valid South African ID number.
_SENSITIVE_MISSING_ID_TYPES = {
    "ID",
    "Qualification",
    "Unemployment Affidavit",
    "Criminal Record Affidavit",
    "Declaration",
    "Cellphone Affidavit",
    "Social Media Form",
    "Attendance Register",
    "Completion Certificate",
}


def _folder_candidate_name(folder: str) -> tuple:
    """Read a person's name off the ZIP sub-folder a document came from."""
    leaf = os.path.basename(folder.rstrip("/\\")) if folder else ""
    if not leaf:
        return None, None
    if _looks_like_generic_name_candidate(leaf):
        return None, None
    first_name, last_name, _ = _extract_name_and_id_from_filename(leaf)
    return first_name, last_name


def process_sharepoint_docs(uploaded_files, allow_missing_id: bool = True, progress_callback=None):
    renamed, unprocessed_count, errors, logs, warnings = 0, 0, 0, [], []
    zip_buffer = io.BytesIO()
 
    # ── PASS 1: Extract everything, rename nothing ───────────────────────────
    docs = []
    for index, f in enumerate(uploaded_files):
        filename = f.name
        if progress_callback:
            progress_callback(index, len(uploaded_files), filename)
        try:
            f.seek(0)
            file_bytes = f.read()
            text, first_page_text = _extract_text_with_ocr(file_bytes, filename)
            ocr_error = text if text.startswith("[OCR ERROR:") else None
            usable_text = "" if (not text.strip() or ocr_error) else text
            doc_type, type_reason = _detect_doc_type(usable_text, filename, first_page_text)
            first_name, last_name, id_number, name_reason = _extract_name_and_id(
                usable_text, filename, doc_type or ""
            )
            folder = getattr(f, "folder", "") or ""
            folder_first, folder_last = _folder_candidate_name(folder)
            if not (first_name and last_name) and folder_first and folder_last:
                first_name, last_name = folder_first, folder_last
            confirmed_id = id_number if _is_valid_sa_id(id_number) else None
            _, _, fn_id = _extract_name_and_id_from_filename(filename)
            if _is_valid_sa_id(fn_id):
                confirmed_id = confirmed_id or fn_id
            docs.append({
                "filename": filename, "file_bytes": file_bytes,
                "text": usable_text, "ocr_error": ocr_error,
                "first_page_text": first_page_text,
                "folder": folder,
                "folder_first_name": folder_first, "folder_last_name": folder_last,
                "doc_type": doc_type, "type_reason": type_reason,
                "first_name": first_name, "last_name": last_name,
                "confirmed_id": confirmed_id,
                "raw_id_candidates": _extract_raw_id_candidates(usable_text),
                "name_reason": name_reason,
                "id_confidence": "CONFIRMED" if confirmed_id else "MISSING",
            })
        except Exception as e:
            warnings.append((filename, f"unexpected error: {e}"))
            errors += 1
 
    # ── PASS 2: Group documents by candidate ────────────────────────────────
    candidates = {}   # key -> {first_name, last_name, confirmed_id, doc_indices}
    nameless = []     # indices of docs with no extractable name

    def assign(index, key):
        docs[index]["candidate_key"] = key
        docs[index]["first_name"] = candidates[key]["first_name"]
        docs[index]["last_name"] = candidates[key]["last_name"]
        candidates[key]["doc_indices"].append(index)

    for i, doc in enumerate(docs):
        if not doc["first_name"] or not doc["last_name"]:
            doc["candidate_key"] = None
            nameless.append(i)
            continue
        key = _candidate_key(doc["first_name"], doc["last_name"])
        best_key, best_score = _best_candidate_match(doc["first_name"], doc["last_name"], candidates)
        if best_score >= NAME_MATCH_THRESHOLD:
            key = best_key
        elif key not in candidates:
            candidates[key] = {"first_name": doc["first_name"], "last_name": doc["last_name"],
                               "confirmed_id": None, "doc_indices": []}
        assign(i, key)

    # ── PASS 3: Resolve canonical ID per candidate ────────────────────────────
    for cand in candidates.values():
        for i in cand["doc_indices"]:
            if docs[i]["confirmed_id"]:
                cand["confirmed_id"] = docs[i]["confirmed_id"]
                break

    # A qualification/ID scan may contain a clean ID but no readable name.
    # When exactly one named candidate still lacks an ID, that document is the
    # only safe batch-level source for completing that candidate. Seed this
    # before partial-ID matching so earlier generic files can match on a second
    # pass regardless of upload order.
    seeded_nameless = []
    unresolved_keys = [key for key, cand in candidates.items()
                       if not cand.get("confirmed_id")]
    for i in nameless:
        doc = docs[i]
        if doc["confirmed_id"] and len(unresolved_keys) == 1:
            key = unresolved_keys[0]
            assign(i, key)
            candidates[key]["confirmed_id"] = doc["confirmed_id"]
            unresolved_keys = []
        else:
            seeded_nameless.append(i)
    nameless = seeded_nameless

    # Documents whose own name is unreadable join a candidate via their ZIP folder,
    # a partial ID match, or — when the whole batch is one person — that person.
    still_nameless = []
    for i in nameless:
        doc = docs[i]
        matched_key = None

        if doc["folder_first_name"] and doc["folder_last_name"]:
            key, score = _best_candidate_match(doc["folder_first_name"], doc["folder_last_name"], candidates)
            matched_key = key if score >= NAME_MATCH_THRESHOLD else None

        if not matched_key and doc["raw_id_candidates"]:
            matched = [key for key, cand in candidates.items()
                       if cand.get("confirmed_id") and any(
                           _compare_partial_id(r, cand["confirmed_id"]) >= 0.7
                           for r in doc["raw_id_candidates"])]
            if len(matched) == 1:
                matched_key = matched[0]

        if not matched_key and len(candidates) == 1:
            matched_key = next(iter(candidates))

        if matched_key:
            assign(i, matched_key)
        else:
            still_nameless.append(i)
    nameless = still_nameless

    # ── PASS 3b: Recover nameless docs via folder name + folder-extracted candidate ID ───────
    # If a document has no extractable name but is in a candidate's folder, use that candidate's
    # confirmed ID even if we couldn't build a full name candidate entry from the document itself.
    still_nameless = []
    for i in nameless:
        doc = docs[i]
        matched_key = None
        
        if doc["folder_first_name"] and doc["folder_last_name"]:
            # Check if any candidate matches the folder name closely enough
            for key, cand in candidates.items():
                similarity = _name_similarity(
                    f"{cand['first_name']} {cand['last_name']}",
                    f"{doc['folder_first_name']} {doc['folder_last_name']}"
                )
                if similarity >= NAME_MATCH_THRESHOLD:
                    # Assign this nameless doc to the folder's candidate, using folder as source of truth
                    matched_key = key
                    break
        
        if matched_key:
            assign(i, matched_key)
        else:
            still_nameless.append(i)
    
    nameless = still_nameless

    # ── PASS 4: Repair missing IDs using batch evidence ───────────────────────
    for doc in docs:
        key = doc.get("candidate_key")
        if doc["confirmed_id"] or not key:
            continue
        canon_id = candidates[key].get("confirmed_id")
        if not canon_id:
            # Vote across all partial OCR candidates in the group
            votes = {}
            for i in candidates[key]["doc_indices"]:
                for raw in docs[i]["raw_id_candidates"]:
                    norm = _normalize_ocr_id(raw)
                    if _is_valid_sa_id(norm) and _luhn_ok(norm):
                        votes[norm] = votes.get(norm, 0) + 1
            if votes:
                canon_id = max(votes, key=lambda k: votes[k])
                candidates[key]["confirmed_id"] = canon_id
        if canon_id:
            # Candidate grouping is the batch-level source of truth here. Once
            # one document has a confirmed ID, use it for every other document
            # assigned to that same candidate. A damaged OCR fragment in a BA,
            # affidavit, or certificate must not force that file to IDUNKNOWN.
            doc["confirmed_id"] = canon_id
            doc["id_confidence"] = "RECOVERED_FROM_CANDIDATE"

    # ── PASS 5: Rename ────────────────────────────────────────────────────
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            filename = doc["filename"]
            file_bytes = doc["file_bytes"]

            # Check if text extraction failed. Allow renaming only if file was assigned to a
            # candidate via folder matching (PASS 3b) AND has a confirmed ID to use.
            no_text = not doc["text"].strip()
            if no_text:
                # Check if file was recovered via folder-based candidate assignment
                has_candidate_assignment = (
                    doc.get("candidate_key") 
                    and doc.get("first_name") 
                    and doc.get("last_name")
                    and doc.get("confirmed_id")
                )
                if not has_candidate_assignment:
                    reason = doc["ocr_error"] or "text could not be extracted — file may be a non-readable scan or unsupported format"
                    zf.writestr(f"unprocessed/{filename}", file_bytes)
                    warnings.append((filename, reason))
                    unprocessed_count += 1
                    continue
                # else: proceed to rename using folder-based assignment + candidate ID

            if not no_text and doc["type_reason"]:
                zf.writestr(f"unprocessed/{filename}", file_bytes)
                warnings.append((filename, f"{doc['type_reason']} | text snippet: {doc['text'][:200].strip()}"))
                unprocessed_count += 1
                continue
 
            first_name = doc["first_name"]
            last_name = doc["last_name"]
            id_number = doc["confirmed_id"]
            doc_type = doc["doc_type"]
            has_name = bool(first_name and last_name)

            # If we have no text but were assigned via folder (no_text + has_candidate_assignment),
            # try to infer doc_type from the filename
            if no_text and not doc_type:
                # Try to detect doc type from filename using the same logic as normal path
                detected_type, _ = _detect_doc_type("", filename, "")
                doc_type = detected_type

            if not has_name and not id_number:
                reason = "name could not be extracted; no 13-digit ID found (batch recovery failed)"
                if doc["name_reason"]:
                    reason += f" | {doc['name_reason']}"
                reason += f" | doc type: {doc_type} | text snippet: {doc['text'][:200].strip()}"
                zf.writestr(f"unprocessed/{filename}", file_bytes)
                warnings.append((filename, reason))
                unprocessed_count += 1
                continue

            if not id_number and not allow_missing_id:
                reason = "no 13-digit ID found (batch recovery failed)"
                reason += f" | doc type: {doc_type} | text snippet: {doc['text'][:200].strip()}"
                zf.writestr(f"unprocessed/{filename}", file_bytes)
                warnings.append((filename, reason))
                unprocessed_count += 1
                continue

            if not id_number:
                if has_name:
                    # We have a name but no ID — rename without ID using just name + doc_type
                    # This handles sensitive docs that couldn't extract an ID
                    pass  # Proceed to renaming below without an ID
                elif allow_missing_id and doc_type not in _SENSITIVE_MISSING_ID_TYPES:
                    text_first, text_last = _extract_name_from_text(doc["text"])
                    if text_first and text_last and not _looks_like_generic_name_candidate(f"{text_first} {text_last}"):
                        id_number = MISSING_ID_PLACEHOLDER
                        doc["id_confidence"] = "MISSING"
                    else:
                        reason = "no 13-digit ID found and no reliable name was available for a placeholder rename"
                        zf.writestr(f"unprocessed/{filename}", file_bytes)
                        warnings.append((filename, reason))
                        unprocessed_count += 1
                        continue
                else:
                    reason = "no 13-digit ID found for a sensitive document type; file kept for manual review"
                    zf.writestr(f"unprocessed/{filename}", file_bytes)
                    warnings.append((filename, reason))
                    unprocessed_count += 1
                    continue

            if not has_name:
                reason = "name could not be extracted with enough confidence to rename safely"
                zf.writestr(f"unprocessed/{filename}", file_bytes)
                warnings.append((filename, reason))
                unprocessed_count += 1
                continue

            confidence_tag = f" [{doc['id_confidence']}]" if doc["id_confidence"] != "CONFIRMED" else ""
            extension = os.path.splitext(filename)[1].lower() or ".pdf"
            folder_name = _sanitize(f"{first_name} {last_name}")
            # Handle missing ID and/or missing doc_type
            id_part = f"_{id_number}" if id_number else ""
            doc_type_part = f"_{doc_type}" if doc_type else ""
            new_name = _sanitize(f"{first_name}_{last_name}{id_part}{doc_type_part}{extension}")
            zf.writestr(f"{folder_name}/{new_name}", file_bytes)
            logs.append(f"✓ Renamed: {filename} → {folder_name}/{new_name}{confidence_tag}")
            if doc["id_confidence"] == "MISSING":
                warnings.append((filename, f"renamed as {folder_name}/{new_name} but the ID number could not be read — please check it"))
            renamed += 1
 
    zip_buffer.seek(0)
    return logs, warnings, zip_buffer, renamed, unprocessed_count, errors
 
 
def page_sharepoint():
    st.header("SharePoint Document Renamer")
    st.write("Renames candidate documents by extracting name, ID number, and document type from each file.")
    st.caption("Supported types: BA, Cellphone Affidavit, Criminal Record Affidavit, Declaration, EEA1, ID, MIE, Social Media Form, Completion Certificate, Attendance Register, Qualification, Une[...]")

    upload_mode = st.radio("Upload mode:", ["Individual files", "Folder (ZIP)"], horizontal=True, key="mode_sharepoint")
    if upload_mode == "Individual files":
        uploaded_files = st.file_uploader(
            "Upload files", type=["pdf", "docx", "doc", "jpg", "jpeg", "png", "tiff"],
            accept_multiple_files=True, key="sharepoint_files"
        )
    else:
        zip_file = st.file_uploader("Upload a ZIP of your folder", type="zip", key="sharepoint_zip")
        uploaded_files = _extract_all_from_zip(zip_file) if zip_file else []

    allow_missing_id = st.checkbox(
        f"Rename files even when the ID number can't be read (uses {MISSING_ID_PLACEHOLDER})",
        value=False, key="sharepoint_allow_missing_id",
    )

    if st.button("Rename Files", key="btn_sharepoint"):
        if not uploaded_files:
            st.error("Please upload at least one file.")
        else:
            progress = st.progress(0.0, text="Reading files...")

            def report(index, total, filename):
                progress.progress(index / total, text=f"Reading {index + 1}/{total}: {filename}")

            with st.spinner("Processing..."):
                logs, warnings, zip_buffer, renamed, unprocessed_count, errors = process_sharepoint_docs(
                    uploaded_files, allow_missing_id=allow_missing_id, progress_callback=report
                )
            progress.empty()

            if logs:
                with st.expander("✅ Successfully renamed files"):
                    for log in logs:
                        st.write(log)
 
            if warnings:
                st.warning(f"⚠️ {len(warnings)} file(s) need attention:")
                for fname, reason in warnings:
                    st.write(f"- **{fname}**: {reason}")
 
            st.write("📊 Summary:")
            st.write(f"  Renamed: {renamed}")
            st.write(f"  Unprocessed: {unprocessed_count}")
            st.write(f"  Errors: {errors}")
            st.write(f"  Total: {renamed + unprocessed_count + errors}")
 
            if renamed + unprocessed_count > 0:
                st.download_button("⬇️ Download Renamed Files", data=zip_buffer, file_name="sharepoint_renamed.zip", mime="application/zip")


# ── App entry point ────────────────────────────────────────────────────────

def main():
    print(f"Bulk Rename App — Build {APP_VERSION}")
    st.set_page_config(page_title="PDF Certificate Renamer", page_icon="📄")
    st.set_option("client.toolbarMode", "minimal")
    st.sidebar.caption(f"Build {APP_VERSION}")

    page = st.sidebar.radio("Select certificate type:", ["Completion Certificates", "Coursera Certificates", "SharePoint Documents"])

    if page == "Completion Certificates":
        page_completion()
    elif page == "Coursera Certificates":
        page_coursera()
    else:
        page_sharepoint()


if __name__ == "__main__":
    main()
