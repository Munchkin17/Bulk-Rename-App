import os
import re
import io
import zipfile
from difflib import SequenceMatcher
 
import pypdf
import streamlit as st
 
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
    normalized = re.sub(r'[\r\n]+', ' ', text)
    normalized = re.sub(r'(?<=[A-Za-z]) (?=[A-Za-z])', '', normalized)
    return re.sub(r' {2,}', ' ', normalized)
 
 
def _match_coursera(normalized: str):
    """Try progressively looser patterns to extract name and course from Coursera cert text."""
    # Pass 1: name before course title, ending at 'an online course'
    match = re.search(
        r'([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})([A-Z].+?)(?:an online course|a non-?online)',
        normalized
    )
    if match:
        return match.group(1).strip(), match.group(2).strip(), None
 
    # Pass 2: specialization pattern
    match = re.search(
        r'([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})has successfully completed the online Specialization([A-Z][A-Za-z ]{2,50}?)(?:Those|Verify|\d|$)',
        normalized
    )
    if match:
        return match.group(1).strip(), match.group(2).strip(), None
 
    # Pass 3: looser — any 'has successfully completed' pattern
    match = re.search(
        r'([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})has successfully completed\s+([A-Z][A-Za-z :]{2,60}?)(?:Those|Verify|\d{4}|$)',
        normalized
    )
    if match:
        return match.group(1).strip(), match.group(2).strip(), None
 
    # Determine specific reason for failure
    has_name = bool(re.search(r'[A-Z][a-z]+(?: [A-Z][a-z]+){1,3}', normalized))
    has_completed = bool(re.search(r'successfully completed', normalized, re.I))
 
    if not has_name:
        reason = "no recognisable candidate name found in document"
    elif not has_completed:
        reason = "'successfully completed' phrase not found — may not be a Coursera certificate"
    else:
        reason = "name and course title found but could not be matched together using known patterns"
 
    return None, None, reason
 
 
def process_coursera_certs(uploaded_files):
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
 
                normalized = _normalize_coursera_text(text)
                full_name, course_name, reason = _match_coursera(normalized)
 
                if full_name and course_name:
                    parts = full_name.split()
                    first_name, last_name = parts[0], parts[-1]
                    course_name = re.sub(r'[\\/*?:"<>|]', '', course_name)
                    new_name = f"{first_name} {last_name} - {course_name}.pdf"
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
    from PIL import ImageOps
 
    prepared = ImageOps.autocontrast(img.convert("L"))
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
    "bbbee", "bbbe", "birth", "copy", "scan", "original", "statement", "application",
    "form", "notice", "receipt", "of", "the", "and", "to", "number", "identitydocument",
    "identitycard", "declarationofcriminalrecordstatus",
    "confirmation", "confirm", "consent", "proof", "residence", "address", "bank", "banking",
    "letter", "cv", "curriculum", "vitae", "qualification", "senior", "national", "school",
    "registration", "agreement", "beneficiary", "attendance", "register", "media", "social",
    "police", "clearance", "payslip", "results", "result", "transcript", "diploma", "degree",
    "report", "signed", "final", "updated", "completion", "training", "cellphone", "phone",
    "eea1", "mie", "ba", "capaciti", "coursera", "certificates", "docs", "files", "file",
}
 
 
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
 
    # Only accept candidate if score meets threshold
    if best_score >= 2:
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
}
 
_NAME_CHUNK = r"([A-Za-z][A-Za-z'\-]*(?:[ \t]+[A-Za-z][A-Za-z'\-]*){0,5})"
 
_NAME_PATTERNS = [
    r'(?:awarded|issued|granted|presented)\s+to\s*[:\-]?\s*(?:i\s+)?' + _NAME_CHUNK,
    r'(?:full\s*names?|fullnames?|candidate\s*name|name\s+of\s+(?:the\s+)?(?:candidate|applicant|learner))\s*[:\-]?\s*' + _NAME_CHUNK,
    r'\bI\s*[,.]\s*(?:the\s+undersigned\s*[,:.]?\s*)?' + _NAME_CHUNK,
]
 
_SURNAME_RE = re.compile(r'\b(?:sur\s*name|surname|sumame|sumame|surmame|sumname)\b\s*[:\-.]?\s*' + _NAME_CHUNK, re.I)
_FORENAME_RE = re.compile(r'\b(?:names|first\s*names?|fore\s*names?|given\s*names?)\b\s*[:\-.]?\s*' + _NAME_CHUNK, re.I)
 
 
def _clean_name_tokens(raw: str) -> list:
    """Keep the leading run of plausible name words, dropping OCR specks and labels."""
    tokens = []
    for token in re.split(r'[\s,]+', (raw or "").strip()):
        letters = re.sub(r"[^A-Za-z'\-]", "", token)
        if len(letters) < 2:
            if tokens:
                break
            continue
        if letters.lower() in _NAME_STOPWORDS:
            break
        tokens.append(letters.capitalize())
        if len(tokens) == 4:
            break
    return tokens
 
 
def _extract_name_from_text(text: str) -> tuple:
    """Extract (first_name, last_name) from document text, or (None, None)."""
    if not text:
        return None, None
 
    surname_match = _SURNAME_RE.search(text)
    if surname_match:
        surname = _clean_name_tokens(surname_match.group(1))
        forename_match = _FORENAME_RE.search(text)
        forenames = _clean_name_tokens(forename_match.group(1)) if forename_match else []
        if surname and forenames:
            return forenames[0], surname[0]
 
    for pattern in _NAME_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            tokens = _clean_name_tokens(match.group(1))
            if len(tokens) >= 2:
                return tokens[0], tokens[-1]
 
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
 
 
def _folder_candidate_name(folder: str) -> tuple:
    """Read a person's name off the ZIP sub-folder a document came from."""
    leaf = os.path.basename(folder.rstrip("/\\")) if folder else ""
    if not leaf:
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
 
            if not doc["text"].strip():
                reason = doc["ocr_error"] or "text could not be extracted — file may be a non-readable scan or unsupported format"
                zf.writestr(f"unprocessed/{filename}", file_bytes)
                warnings.append((filename, reason))
                unprocessed_count += 1
                continue
 
            if doc["type_reason"]:
                zf.writestr(f"unprocessed/{filename}", file_bytes)
                warnings.append((filename, f"{doc['type_reason']} | text snippet: {doc['text'][:200].strip()}"))
                unprocessed_count += 1
                continue
 
            first_name = doc["first_name"]
            last_name = doc["last_name"]
            id_number = doc["confirmed_id"]
            doc_type = doc["doc_type"]
            has_name = bool(first_name and last_name)
 
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
                id_number = MISSING_ID_PLACEHOLDER
                doc["id_confidence"] = "MISSING"
            if not has_name:
                first_name, last_name = "Unknown", id_number
 
            confidence_tag = f" [{doc['id_confidence']}]" if doc["id_confidence"] != "CONFIRMED" else ""
            extension = os.path.splitext(filename)[1].lower() or ".pdf"
            folder_name = _sanitize(f"{first_name} {last_name}")
            new_name = _sanitize(f"{first_name}_{last_name}_{id_number}_{doc_type}{extension}")
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
        value=True, key="sharepoint_allow_missing_id",
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
 
 
# ── App entry point ────────────────────────────────────────────────────────��[...]
 
def main():
    st.set_page_config(page_title="PDF Certificate Renamer", page_icon="📄")
    st.set_option("client.toolbarMode", "minimal")
 
    page = st.sidebar.radio("Select certificate type:", ["Completion Certificates", "Coursera Certificates", "SharePoint Documents"])
 
    if page == "Completion Certificates":
        page_completion()
    elif page == "Coursera Certificates":
        page_coursera()
    else:
        page_sharepoint()
 
 
if __name__ == "__main__":
    main()
