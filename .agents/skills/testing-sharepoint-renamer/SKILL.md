---
name: testing-sharepoint-renamer
description: How to run and end-to-end test the Bulk-Rename-App Streamlit renamer, especially the OCR-based "SharePoint Documents" page.
---

# Testing the Bulk-Rename-App Streamlit renamer

## Running the app
- `.venv/bin/streamlit run app.py --server.headless true --server.port 8501`, then open `http://localhost:8501`.
- System deps needed for OCR: `tesseract-ocr` and `poppler-utils` (blueprint `initialize` installs these).
  Python deps: `requirements.txt` (pypdf, streamlit, pytesseract, Pillow, pdf2image, python-docx).
- The three pages are chosen from the sidebar radio "Select certificate type:" —
  Completion Certificates / Coursera Certificates / SharePoint Documents.

## Test fixtures
- `tests/make_scanned_samples.py` renders image-only (no text layer) PDFs into `tests/samples/`, which is what
  forces the OCR path. Adapt it to add more people, `.jpg` images, or a ZIP with one sub-folder per candidate
  (`Candidate Name/doc.pdf`) — the ZIP sub-folder name is what groups documents for a candidate.
- Filenames matter: `app._FILENAME_DOC_TYPE_MAP` maps filename fragments to a doc type, and
  `app._FILENAME_STOPWORDS` prevents document words in a filename from being mistaken for a person's name.
  Keep fixture filenames generic (e.g. `Qualification.pdf`) if you want to prove text/OCR extraction rather
  than filename extraction.
- Useful adversarial fixture: two byte-identical documents containing no name and no ID, placed in two different
  candidate sub-folders — only correct folder grouping can route them to different people.

## Precompute expectations before touching the UI
OCR in the UI is slow (roughly 30-60 s per page at 300 DPI with multiple Tesseract passes; a 4-file batch takes
~3 minutes). Call `app.process_sharepoint_docs(files, allow_missing_id=...)` directly from a short script first
to learn the exact expected output filenames/counts, then assert those exact strings in the browser. Build
file-like inputs as `io.BytesIO` with a `.name` attribute (and a `.folder` attribute for ZIP entries, or use
`app._extract_all_from_zip`).

## UI gotchas
- Clicking "⬇️ Download Renamed Files" triggers a Streamlit rerun that clears the results block, so capture
  screenshots of the renamed list and Summary *before* downloading. Downloads land in `~/Downloads`; verify the
  archive with `unzip -l`.
- Stray clicks near the results area can hit the "Upload mode" radio or the checkbox and silently restart a run.
  Re-screenshot after every click before asserting.
- The warning block header always reads "N file(s) moved to unprocessed/" even for files that were renamed with
  the `IDUNKNOWN` placeholder — check the per-file text and the Summary counts, not the header, to decide whether
  a file was actually renamed or moved to `unprocessed/`.

## Devin Secrets Needed
None — the app runs entirely locally with no credentials.
