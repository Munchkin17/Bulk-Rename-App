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


def _render_results(logs, zip_buffer, renamed, skipped, errors, zip_name):
    st.text_area("Processing log", "\n".join(logs) if logs else "No PDFs found.", height=400)
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


def process_completion_certs(uploaded_files, template: str):
    renamed, skipped, errors, logs = 0, 0, 0, []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in uploaded_files:
            filename = f.name
            try:
                text = _extract_text(f)
                match = re.search(r'issued to\s+([A-Za-z]+(?:\s[A-Za-z]+){1,2})\s+(\d{13})', text, re.I)
                if match:
                    parts = match.group(1).strip().split()
                    first_name, last_name = parts[0], parts[-1]
                    try:
                        new_name = _build_filename(template, {
                            "first_name": first_name, "last_name": last_name,
                            "id": match.group(2), "original_name": filename,
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
                    logs.append(f"⊘ Skipped: {filename} (could not extract name or ID)")
                    logs.append(f"  DEBUG: {text[:300].replace(chr(10), ' ')}")
                    skipped += 1
            except Exception as e:
                logs.append(f"✗ Error: {filename}: {e}")
                errors += 1

    zip_buffer.seek(0)
    return logs, zip_buffer, renamed, skipped, errors


def page_completion():
    st.header("Completion Certificate Renamer")
    st.write("Renames certificates by extracting the name and 13-digit ID number.")

    uploaded_files = st.file_uploader("Upload PDF files", type="pdf", accept_multiple_files=True, key="completion")
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

def process_coursera_certs(uploaded_files):
    renamed, skipped, errors, logs = 0, 0, 0, []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in uploaded_files:
            filename = f.name
            try:
                text = _extract_text(f)

                # Collapse character-spaced text e.g. "A m a h l e" -> "Amahle"
                normalized = re.sub(r'[\r\n]+', ' ', text)
                normalized = re.sub(r'(?<=[A-Za-z]) (?=[A-Za-z])', '', normalized)
                normalized = re.sub(r' {2,}', ' ', normalized)

                match = re.search(
                    r'([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})([A-Z].+?)(?:an online course|a non-?online)',
                    normalized
                )
                if not match:
                    match = re.search(
                        r'([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})has successfully completed the online Specialization([A-Z][A-Za-z ]{2,50}?)(?:Those|Verify|\d|$)',
                        normalized
                    )

                if match:
                    parts = match.group(1).strip().split()
                    first_name, last_name = parts[0], parts[-1]
                    course_name = re.sub(r'[\\/*?:"<>|]', '', match.group(2).strip())
                    new_name = f"{first_name} {last_name} - {course_name}.pdf"
                    folder_name = _sanitize(f"{first_name} {last_name}")
                    f.seek(0)
                    zf.writestr(f"{folder_name}/{new_name}", f.read())
                    logs.append(f"✓ Renamed: {filename} -> {folder_name}/{new_name}")
                    renamed += 1
                else:
                    logs.append(f"⊘ Skipped: {filename} (could not extract name or course)")
                    logs.append(f"  DEBUG: {normalized[:300]}")
                    skipped += 1
            except Exception as e:
                logs.append(f"✗ Error: {filename}: {e}")
                errors += 1

    zip_buffer.seek(0)
    return logs, zip_buffer, renamed, skipped, errors


def page_coursera():
    st.header("Coursera Certificate Renamer")
    st.write("Renames Coursera certificates by extracting the name and course title.")

    uploaded_files = st.file_uploader("Upload PDF files", type="pdf", accept_multiple_files=True, key="coursera")

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
