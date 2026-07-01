import os
import re
import argparse
import zipfile
import io
import pypdf

DEFAULT_TEMPLATE = "{first_name}_{last_name}_{id}_Completionoftrainingcertificate.pdf"
# Default folder used for CLI
folder = r"C:\Users\TARRYN\Downloads\ASA 6 Certs"


def _extract_text_from_pdf(source) -> str:
    reader = pypdf.PdfReader(source)
    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"
    return text


def process_uploaded_files(uploaded_files, template: str = DEFAULT_TEMPLATE):
    """Process uploaded PDF file objects and return (logs, zip_buffer, renamed, skipped, errors)."""
    renamed_count = 0
    skipped_count = 0
    error_count = 0
    logs = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for uploaded_file in uploaded_files:
            filename = uploaded_file.name
            try:
                text = _extract_text_from_pdf(uploaded_file)
                match = re.search(
                    r'issued to\s+([A-Za-z]+(?:\s[A-Za-z]+){1,2})\s+(\d{13})',
                    text,
                    re.I,
                )
                if match:
                    full_name = match.group(1).strip().split()
                    first_name = full_name[0]
                    last_name = full_name[-1]
                    id_number = match.group(2)
                    try:
                        new_filename = build_target_filename(
                            template,
                            {
                                "first_name": first_name,
                                "last_name": last_name,
                                "id": id_number,
                                "original_name": filename,
                                "original_basename": os.path.splitext(filename)[0],
                            },
                        )
                    except ValueError as exc:
                        logs.append(f"✗ Invalid template: {exc}")
                        error_count += 1
                        continue
                    uploaded_file.seek(0)
                    zf.writestr(new_filename, uploaded_file.read())
                    logs.append(f"✓ Renamed: {filename} -> {new_filename}")
                    renamed_count += 1
                else:
                    logs.append(f"⊘ Skipped: {filename} (could not extract name or ID)")
                    snippet = text[:300].replace("\n", " ")
                    logs.append(f"  DEBUG - Raw snippet: {snippet}")
                    skipped_count += 1
            except Exception as e:
                logs.append(f"✗ Error processing {filename}: {e}")
                error_count += 1

    zip_buffer.seek(0)
    return logs, zip_buffer, renamed_count, skipped_count, error_count


def _sanitize_filename(filename: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]+", "_", filename).strip()


def build_target_filename(template: str, values: dict[str, str]) -> str:
    try:
        result = template.format_map(values)
    except Exception as exc:
        raise ValueError(f"Template formatting error: {exc}") from exc
    result = _sanitize_filename(result)
    if not result.lower().endswith(".pdf"):
        result += ".pdf"
    return result



def main():
    import streamlit as st

    st.title("PDF Renamer")
    st.write("Upload PDF certificate files to rename them based on extracted names and ID numbers.")

    uploaded_files = st.file_uploader("Upload PDF files", type="pdf", accept_multiple_files=True)
    template_input = st.text_input(
        "Naming convention template:",
        DEFAULT_TEMPLATE,
        help="Use {first_name}, {last_name}, {id}, {original_name}, {original_basename}",
    )
    st.caption("Supported placeholders: {first_name}, {last_name}, {id}, {original_name}, {original_basename}")

    if st.button("Rename PDFs"):
        if not uploaded_files:
            st.error("Please upload at least one PDF file.")
        else:
            with st.spinner("Processing PDFs..."):
                logs, zip_buffer, renamed_count, skipped_count, error_count = process_uploaded_files(uploaded_files, template_input)

            st.text_area("Processing log", "\n".join(logs) if logs else "No PDFs found.", height=400)

            st.write("📊 Summary:")
            st.write(f"  Renamed: {renamed_count}")
            st.write(f"  Skipped: {skipped_count}")
            st.write(f"  Errors:  {error_count}")
            st.write(f"  Total:   {renamed_count + skipped_count + error_count}")

            if renamed_count > 0:
                st.download_button(
                    label="⬇️ Download Renamed PDFs",
                    data=zip_buffer,
                    file_name="renamed_pdfs.zip",
                    mime="application/zip",
                )


def _is_streamlit_run() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if __name__ == "__main__":
    if _is_streamlit_run():
        main()
    else:
        parser = argparse.ArgumentParser(description="Bulk rename PDF files using extracted text values.")
        parser.add_argument(
            "--folder",
            default=folder,
            help="Folder containing PDF files to process.",
        )
        parser.add_argument(
            "--template",
            default=DEFAULT_TEMPLATE,
            help="Filename template. Supported placeholders: {first_name}, {last_name}, {id}, {original_name}, {original_basename}.",
        )
        args = parser.parse_args()

        if not os.path.isdir(args.folder):
            print(f"Error: Folder does not exist: {args.folder}")
            raise SystemExit(1)

        logs, renamed_count, skipped_count, error_count = process_folder(args.folder, args.template)

        print(f"Processing PDFs in: {args.folder}\n")
        for line in logs:
            print(line)

        print(f"\n{'='*60}")
        print("SUMMARY:")
        print(f"  Renamed: {renamed_count}")
        print(f"  Skipped: {skipped_count}")
        print(f"  Errors:  {error_count}")
        print(f"  Total:   {renamed_count + skipped_count + error_count}")