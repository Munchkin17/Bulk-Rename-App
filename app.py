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


# ── App entry point ───────────────────────────────────────────────────────────

st.set_page_config(page_title="PDF Certificate Renamer", page_icon="📄")
st.title("📄 PDF Certificate Renamer")

page = st.sidebar.radio("Select certificate type:", ["Completion Certificates", "Coursera Certificates"])

if page == "Completion Certificates":
    page_completion()
else:
    page_coursera()
