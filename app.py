import os
import re
import io
import zipfile
import pypdf
import streamlit as st

# ── Shared utilities ──────────────────────────────────────────────────────────

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
    "BA":                      ["beneficiary agreement", "beneficiary"],
    "Cellphone Affidavit":     ["cellphone affidavit", "cell phone affidavit", "mobile affidavit"],
    "Criminal Record Affidavit": ["criminal record", "criminal affidavit", "no criminal", "police clearance"],
    "Declaration":             ["declaration", "hereby declare", "i declare"],
    "EEA1":                    ["eea1", "eea 1", "employment equity"],
    "ID":                      ["identity document", "identity number", "south african id", "national identity"],
    "MIE":                     ["mie", "managed integrity evaluation", "background check", "verification report"],
    "Social Media Form":       ["social media", "social networking"],
    "Completion Certificate":  ["completion certificate", "certificate of completion", "has successfully completed", "issued to"],
    "Attendance Register":     ["attendance register", "attendance sheet", "attendance list"],
    "Qualification":           ["qualification", "certificate of achievement", "diploma", "degree", "transcript"],
    "Unemployment Affidavit":  ["unemployment affidavit", "unemployed", "not employed", "unemployment"],
}


def _extract_text_with_ocr(file_bytes: bytes, filename: str) -> str:
    """Extract text from PDF (digital then OCR fallback), Word doc, or image."""
    import pypdf
    from PIL import Image
    import pytesseract

    ext = os.path.splitext(filename)[1].lower()

    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        img = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(img)

    if ext in (".docx", ".doc"):
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)

    if ext == ".pdf":
        # Try digital text first
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        if text.strip():
            return text

        # OCR fallback for scanned PDFs
        try:
            from pdf2image import convert_from_bytes
            import pytesseract
            images = convert_from_bytes(file_bytes)
            return "\n".join(pytesseract.image_to_string(img) for img in images)
        except Exception:
            return ""

    return ""


def _detect_doc_type(text: str) -> tuple:
    """Return (doc_type, reason) — flags conflict if multiple types match."""
    text_lower = text.lower()
    matches = [dt for dt, keywords in DOC_TYPES.items() if any(kw in text_lower for kw in keywords)]

    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, f"multiple document types detected: {', '.join(matches)} — manual review required"
    return "Other", None


def _extract_name_and_id(text: str) -> tuple:
    """Extract (first_name, last_name, id_number, reason) from document text."""
    id_match = re.search(r'\b(\d{13})\b', text)
    id_number = id_match.group(1) if id_match else None

    first_name = last_name = None

    # Pattern 1: labelled fields — Name: / First Name: / Surname: / Last Name:
    fn_match = re.search(r'(?:first\s*name|name)\s*[:\-]\s*([A-Za-z]+)', text, re.I)
    ln_match = re.search(r'(?:last\s*name|surname)\s*[:\-]\s*([A-Za-z]+)', text, re.I)
    if fn_match:
        first_name = fn_match.group(1).strip()
    if ln_match:
        last_name = ln_match.group(1).strip()

    # Pattern 2: "I, [First Last]" or "I, [First Last],"
    if not first_name or not last_name:
        i_match = re.search(r'\bI,\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,3})', text)
        if i_match:
            parts = i_match.group(1).strip().split()
            first_name = parts[0]
            last_name = parts[-1]

    # Pattern 3: full name label
    if not first_name or not last_name:
        full_match = re.search(r'(?:full\s*name|candidate\s*name)\s*[:\-]\s*([A-Za-z]+(?:\s[A-Za-z]+){1,3})', text, re.I)
        if full_match:
            parts = full_match.group(1).strip().split()
            first_name = parts[0]
            last_name = parts[-1]

    if first_name and last_name and id_number:
        return first_name, last_name, id_number, None

    # Build specific reason
    missing = []
    if not first_name or not last_name:
        missing.append("name could not be extracted")
    if not id_number:
        missing.append("no 13-digit ID number found")
    return first_name, last_name, id_number, "; ".join(missing)


def process_sharepoint_docs(uploaded_files):
    renamed, unprocessed_count, errors, logs, warnings = 0, 0, 0, [], []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in uploaded_files:
            filename = f.name
            try:
                f.seek(0)
                file_bytes = f.read()
                text = _extract_text_with_ocr(file_bytes, filename)

                if not text.strip():
                    reason = "text could not be extracted — file may be a non-readable scan or unsupported format"
                    zf.writestr(f"unprocessed/{filename}", file_bytes)
                    warnings.append((filename, reason))
                    unprocessed_count += 1
                    continue

                doc_type, type_reason = _detect_doc_type(text)
                if type_reason:
                    zf.writestr(f"unprocessed/{filename}", file_bytes)
                    warnings.append((filename, f"{type_reason} | text snippet: {text[:200].strip()}"))
                    unprocessed_count += 1
                    continue

                first_name, last_name, id_number, name_reason = _extract_name_and_id(text)
                if name_reason:
                    zf.writestr(f"unprocessed/{filename}", file_bytes)
                    warnings.append((filename, f"{name_reason} | doc type detected: {doc_type} | text snippet: {text[:200].strip()}"))
                    unprocessed_count += 1
                    continue

                folder_name = _sanitize(f"{first_name} {last_name}")
                new_name = _sanitize(f"{first_name}_{last_name}_{id_number}_{doc_type}.pdf")
                zf.writestr(f"{folder_name}/{new_name}", file_bytes)
                logs.append(f"✓ Renamed: {filename} -> {folder_name}/{new_name}")
                renamed += 1

            except Exception as e:
                warnings.append((filename, f"unexpected error: {e}"))
                errors += 1

    zip_buffer.seek(0)
    return logs, warnings, zip_buffer, renamed, unprocessed_count, errors


def page_sharepoint():
    st.header("SharePoint Document Renamer")
    st.write("Renames candidate documents by extracting name, ID number, and document type from each file.")
    st.caption("Supported types: BA, Cellphone Affidavit, Criminal Record Affidavit, Declaration, EEA1, ID, MIE, Social Media Form, Completion Certificate, Attendance Register, Qualification, Unemployment Affidavit, Other")

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


# ── App entry point ───────────────────────────────────────────────────────────

st.set_page_config(page_title="PDF Certificate Renamer", page_icon="📄")
st.title("📄 PDF Certificate Renamer")

page = st.sidebar.radio("Select certificate type:", ["Completion Certificates", "Coursera Certificates", "SharePoint Documents"])

if page == "Completion Certificates":
    page_completion()
elif page == "Coursera Certificates":
    page_coursera()
else:
    page_sharepoint()
