import os
import re
import io
import zipfile
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
        return match.group(1).strip(), match.group(3).strip(), None

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


def _extract_text_with_ocr(file_bytes: bytes, filename: str) -> tuple:
    """Extract (full_text, first_page_text) from PDF, Word doc, or image."""
    import pypdf
    from PIL import Image
    import pytesseract

    if os.path.isfile(_TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_PATH

    ext = os.path.splitext(filename)[1].lower()

    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        text = pytesseract.image_to_string(Image.open(io.BytesIO(file_bytes)))
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
        if full_text.strip():
            return full_text, pages_text[0] if pages_text else ""

        # OCR fallback for scanned PDFs
        try:
            from pdf2image import convert_from_bytes
            kwargs = {"poppler_path": _POPPLER_PATH} if _POPPLER_PATH else {}
            images = convert_from_bytes(file_bytes, **kwargs)
            ocr_pages = [pytesseract.image_to_string(img) for img in images]
            full_text = "\n".join(ocr_pages)
            return full_text, ocr_pages[0] if ocr_pages else ""
        except Exception as e:
            return "", f"[OCR ERROR: {e}]"

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

    STOPWORDS = {
        "certified", "cert", "id", "identity", "document", "doc", "declaration", "affidavit",
        "criminal", "record", "status", "matric", "certificate", "certification", "unemployment",
        "bbbee", "bbbe", "birth", "copy", "scan", "original", "statement", "application",
        "form", "notice", "receipt", "of", "the", "and", "to", "number", "identitydocument",
        "identitycard", "declarationofcriminalrecordstatus"
    }

    def is_stopword(token: str) -> bool:
        return token.lower() in STOPWORDS

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


def _extract_name_and_id(text: str, filename: str = "", doc_type: str = "", name_to_id: dict = None) -> tuple:
    """Extract (first_name, last_name, id_number, reason) — filename takes priority."""
    first_name, last_name, id_number = _extract_name_and_id_from_filename(filename)

    if first_name and last_name and not id_number and doc_type == "Completion Certificate":
        # Try to resolve ID from other files processed in the same batch
        id_number = (name_to_id or {}).get((first_name.lower(), last_name.lower()), "unknown_ID")

    if first_name and last_name and id_number:
        return first_name, last_name, id_number, None

    # Fallback: extract from text
    if not id_number:
        id_match = re.search(r'\b(\d{13})\b', text)
        id_number = id_match.group(1) if id_match else None

    if not first_name or not last_name:
        fn_match = re.search(r'(?:first\s*name|name)\s*[:\-]\s*([A-Za-z]+)', text, re.I)
        ln_match = re.search(r'(?:last\s*name|surname)\s*[:\-]\s*([A-Za-z]+)', text, re.I)
        if fn_match:
            first_name = fn_match.group(1).strip()
        if ln_match:
            last_name = ln_match.group(1).strip()

    if not first_name or not last_name:
        i_match = re.search(r'\bI[,.]\s+([A-Za-z]+(?:\s[A-Za-z]+){1,3})', text)
        if i_match:
            parts = i_match.group(1).strip().split()
            if len(parts) >= 2 and parts[0].lower() not in ("the", "am", "do", "hereby"):
                first_name, last_name = parts[0], parts[-1]

    if not first_name or not last_name:
        full_match = re.search(r'(?:full\s*names?|candidate\s*name)\s*[:\-]?\s*([A-Za-z]+(?:[\s]+[A-Za-z]+){1,3})', text, re.I)
        if full_match:
            parts = full_match.group(1).strip().split()
            if len(parts) >= 2:
                first_name, last_name = parts[0], parts[-1]

    # Last resort: name from filename
    if not first_name or not last_name:
        fn, ln, _ = _extract_name_and_id_from_filename(filename)
        if fn and ln:
            first_name, last_name = fn, ln

    if first_name and last_name and id_number:
        return first_name, last_name, id_number, None

    missing = []
    if not first_name or not last_name:
        missing.append("name could not be extracted")
    if not id_number:
        missing.append("no 13-digit ID number found")
    return first_name, last_name, id_number, "; ".join(missing)


# ── Batch candidate resolution helpers ─────────────────────────────────────

OCR_EQUIVALENTS = {"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "G": "6", "B": "8"}


def _normalize_ocr_id(raw: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9]', '', raw).upper()
    return ''.join(OCR_EQUIVALENTS.get(c, c) for c in cleaned)


def _is_valid_sa_id(s: str) -> bool:
    return bool(re.fullmatch(r'\d{13}', s or ''))


def _compare_partial_id(ocr_value: str, known_id: str) -> float:
    norm = _normalize_ocr_id(ocr_value)
    length = max(len(norm), len(known_id), 1)
    matches = sum(a == b for a, b in zip(norm.ljust(13, '?'), known_id))
    return matches / 13


def _name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
    return sum(c in longer for c in shorter) / len(longer)


def _extract_raw_id_candidates(text: str) -> list:
    """Return plausible ID-like strings, collapsing OCR-split tokens first."""
    exact = re.findall(r'\b(\d{13})\b', text)
    if exact:
        return exact
    # Collapse spaces/dashes between digit-like chars: "O40 06 01-18 OSU" -> "O4006011805"
    collapsed = re.sub(r'(?<=[0-9OQILSGBo])[ \-./]+(?=[0-9OQILSGBo])', '', text, flags=re.I)
    return re.findall(r'[0-9OQILSGBo]{10,15}', collapsed, flags=re.I)


def _candidate_key(first_name: str, last_name: str) -> str:
    return f"{first_name.lower().strip()}|{last_name.lower().strip()}"


def _best_candidate_match(first_name: str, last_name: str, candidates: dict) -> tuple:
    best_key, best_score = None, 0.0
    for key, cand in candidates.items():
        score = (_name_similarity(last_name, cand['last_name']) * 0.5
                 + _name_similarity(first_name, cand['first_name']) * 0.5)
        if score > best_score:
            best_score, best_key = score, key
    return best_key, best_score


def process_sharepoint_docs(uploaded_files):
    renamed, unprocessed_count, errors, logs, warnings = 0, 0, 0, [], []
    zip_buffer = io.BytesIO()

    # ── PASS 1: Extract everything, rename nothing ───────────────────────────
    docs = []
    for f in uploaded_files:
        filename = f.name
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
            confirmed_id = id_number if _is_valid_sa_id(id_number) else None
            _, _, fn_id = _extract_name_and_id_from_filename(filename)
            if _is_valid_sa_id(fn_id):
                confirmed_id = confirmed_id or fn_id
            docs.append({
                "filename": filename, "file_bytes": file_bytes,
                "text": usable_text, "ocr_error": ocr_error,
                "first_page_text": first_page_text,
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
    for i, doc in enumerate(docs):
        if not doc["first_name"] or not doc["last_name"]:
            doc["candidate_key"] = None
            nameless.append(i)
            continue
        key = _candidate_key(doc["first_name"], doc["last_name"])
        best_key, best_score = _best_candidate_match(doc["first_name"], doc["last_name"], candidates)
        if best_score >= 0.75:
            key = best_key
        else:
            candidates[key] = {"first_name": doc["first_name"], "last_name": doc["last_name"],
                               "confirmed_id": None, "doc_indices": []}
        candidates[key]["doc_indices"].append(i)
        doc["candidate_key"] = key

    # ── PASS 3: Resolve canonical ID per candidate ────────────────────────────
    for cand in candidates.values():
        for i in cand["doc_indices"]:
            if docs[i]["confirmed_id"]:
                cand["confirmed_id"] = docs[i]["confirmed_id"]
                break

    # Assign nameless docs to a candidate if their partial ID matches exactly one
    for i in nameless:
        doc = docs[i]
        if not doc["raw_id_candidates"]:
            continue
        matched = [key for key, cand in candidates.items()
                   if cand.get("confirmed_id") and any(
                       _compare_partial_id(r, cand["confirmed_id"]) >= 0.7
                       for r in doc["raw_id_candidates"])]
        if len(matched) == 1:
            key = matched[0]
            doc["candidate_key"] = key
            doc["first_name"] = candidates[key]["first_name"]
            doc["last_name"] = candidates[key]["last_name"]
            candidates[key]["doc_indices"].append(i)

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
                    if len(norm) == 13 and _is_valid_sa_id(norm):
                        votes[norm] = votes.get(norm, 0) + 1
            if votes:
                canon_id = max(votes, key=lambda k: votes[k])
                candidates[key]["confirmed_id"] = canon_id
        if canon_id:
            compatible = (not doc["raw_id_candidates"] or any(
                _compare_partial_id(r, canon_id) >= 0.75
                for r in doc["raw_id_candidates"]))
            if compatible:
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

            if not first_name or not last_name or not id_number:
                parts = []
                if not first_name or not last_name:
                    parts.append("name could not be extracted")
                if not id_number:
                    parts.append("no 13-digit ID found (batch recovery failed)")
                reason = "; ".join(parts)
                if doc["name_reason"]:
                    reason += f" | {doc['name_reason']}"
                reason += f" | doc type: {doc_type} | text snippet: {doc['text'][:200].strip()}"
                zf.writestr(f"unprocessed/{filename}", file_bytes)
                warnings.append((filename, reason))
                unprocessed_count += 1
                continue

            confidence_tag = f" [{doc['id_confidence']}]" if doc["id_confidence"] != "CONFIRMED" else ""
            folder_name = _sanitize(f"{first_name} {last_name}")
            new_name = _sanitize(f"{first_name}_{last_name}_{id_number}_{doc_type}.pdf")
            zf.writestr(f"{folder_name}/{new_name}", file_bytes)
            logs.append(f"✓ Renamed: {filename} → {folder_name}/{new_name}{confidence_tag}")
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

    if st.button("Rename Files", key="btn_sharepoint"):
        if not uploaded_files:
            st.error("Please upload at least one file.")
        else:
            with st.spinner("Processing..."):
                logs, warnings, zip_buffer, renamed, unprocessed_count, errors = process_sharepoint_docs(uploaded_files)

            if logs:
                with st.expander("✅ Successfully renamed files"):
                    for log in logs:
                        st.write(log)

            if warnings:
                st.warning(f"⚠️ {len(warnings)} file(s) moved to unprocessed/:")
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

st.set_page_config(page_title="PDF Certificate Renamer", page_icon="📄")
st.set_option("client.toolbarMode", "minimal")

page = st.sidebar.radio("Select certificate type:", ["Completion Certificates", "Coursera Certificates", "SharePoint Documents"])

if page == "Completion Certificates":
    page_completion()
elif page == "Coursera Certificates":
    page_coursera()
else:
    page_sharepoint()
