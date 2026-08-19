"""Extraction tests built from real OCR output of scanned SharePoint documents."""

import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app


class FakeUpload(io.BytesIO):
    def __init__(self, name, folder=""):
        super().__init__(b"%PDF-1.4 fake")
        self.name = name
        self.folder = folder


ID_CARD_TEXT = """—
REPUBLIC OF SOUTH AFRICA 4 Le CARD
Sumame-
HLUNGWANE Names t SINGITA Sex:
F Nationality: R
Identity Number- 0308121234089 Date of Birth:
12 AUG 2003
"""

MATRIC_TEXT = """REPUBLIC OF SOUTH AFRICA
National Senior Certificate
| Awarded to i SINGITA HLUNGWANE Identity number 030812 1234 08 9
"""

CRIMINAL_RECORD_TEXT = """AFFIDAVIT: DECLARATION OF CRIMINAL RECORD STATUS
I, the undersigned:
Full Names: Vunene Kubayi
identity Number: O4O6O1 1234 O8 4 Residential Address: Nkowankowa
"""


class TestIdExtraction(unittest.TestCase):
    def test_clean_id(self):
        self.assertEqual(app._find_id_number("Identity Number: 0308121234089")[0], "0308121234089")

    def test_id_split_by_spaces(self):
        self.assertEqual(app._find_id_number(MATRIC_TEXT)[0], "0308121234089")

    def test_id_with_letters_misread_as_digits(self):
        # Only accepted because the corrected digits satisfy the SA ID checksum
        self.assertEqual(app._find_id_number(CRIMINAL_RECORD_TEXT)[0], "0406011234084")

    def test_rejects_thirteen_digits_with_impossible_birth_date(self):
        self.assertFalse(app._is_valid_sa_id("0399991234083"))

    def test_no_id_present(self):
        self.assertEqual(app._find_id_number("no numbers here at all"), (None, None))


class TestNameExtraction(unittest.TestCase):
    def test_id_card_surname_and_names_labels(self):
        self.assertEqual(app._extract_name_from_text(ID_CARD_TEXT), ("Singita", "Hlungwane"))

    def test_awarded_to_on_qualification(self):
        self.assertEqual(app._extract_name_from_text(MATRIC_TEXT), ("Singita", "Hlungwane"))

    def test_full_names_label(self):
        self.assertEqual(app._extract_name_from_text(CRIMINAL_RECORD_TEXT), ("Vunene", "Kubayi"))

    def test_i_the_undersigned(self):
        text = "I, YANGA KOYINA hereby confirm that I am unemployed"
        self.assertEqual(app._extract_name_from_text(text), ("Yanga", "Koyina"))

    def test_no_name_in_boilerplate(self):
        text = ("BBBE Certification: Affidavit to Confirm Unemployment hereby confirm that "
                "| am unemployed and have not previously participated in any funded Programme")
        self.assertEqual(app._extract_name_from_text(text), (None, None))


class TestNameMatching(unittest.TestCase):
    def test_ocr_damaged_surname_matches_same_person(self):
        self.assertGreaterEqual(
            app._names_match("Singita", "Iungqwane", "Singita", "Hlungwane"),
            app.NAME_MATCH_THRESHOLD,
        )

    def test_different_people_do_not_match(self):
        self.assertLess(
            app._names_match("Vunene", "Kubayi", "Yanga", "Koyina"),
            app.NAME_MATCH_THRESHOLD,
        )


class TestBatchProcessing(unittest.TestCase):
    def _run(self, docs, **kwargs):
        """docs: list of (filename, folder, extracted_text)."""
        texts = {name: text for name, _, text in docs}
        original = app._extract_text_with_ocr
        app._extract_text_with_ocr = lambda file_bytes, filename: (texts[filename], texts[filename])
        try:
            uploads = [FakeUpload(name, folder) for name, folder, _ in docs]
            return app.process_sharepoint_docs(uploads, **kwargs)
        finally:
            app._extract_text_with_ocr = original

    def test_id_recovered_across_a_candidates_documents(self):
        logs, _, _, renamed, unprocessed, errors = self._run([
            ("Certified ID.pdf", "", ID_CARD_TEXT),
            ("BBBE certification .pdf", "",
             "BBBE Certification: Affidavit to Confirm Unemployment hereby confirm that | am unemployed"),
        ])
        self.assertEqual((renamed, unprocessed, errors), (2, 0, 0))
        self.assertTrue(any("Singita_Hlungwane_0308121234089_ID.pdf" in log for log in logs), logs)
        self.assertTrue(any("Singita_Hlungwane_0308121234089_Unemployment Affidavit.pdf" in log for log in logs), logs)

    def test_zip_folder_groups_documents_without_readable_names(self):
        logs, _, _, renamed, unprocessed, _ = self._run([
            ("Certified ID.pdf", "Singita Hlungwane", ID_CARD_TEXT),
            ("BBBE certification .pdf", "Singita Hlungwane", "BBBE Certification: Affidavit to Confirm Unemployment"),
            ("Criminal Record Affidavit.pdf", "Vunene Kubayi", CRIMINAL_RECORD_TEXT),
        ])
        self.assertEqual((renamed, unprocessed), (3, 0))
        self.assertTrue(any("Vunene Kubayi/Vunene_Kubayi_0406011234084_Criminal Record Affidavit.pdf" in log
                            for log in logs), logs)

    def test_renames_with_placeholder_when_id_unreadable(self):
        logs, warnings, zip_buffer, renamed, unprocessed, _ = self._run([
            ("Yanga Koyina Confirmation of Unemployment.pdf", "",
             "BBBE Certification: Affidavit to Confirm Unemployment 1, YAWGA kota ID: 4g OF 16 SEI4ORE"),
        ])
        self.assertEqual((renamed, unprocessed), (1, 0))
        self.assertTrue(any("[UNCONFIRMED_ID]" in log or "[MISSING]" in log for log in logs), logs)
        self.assertTrue(warnings)
        with zipfile.ZipFile(zip_buffer) as zf:
            self.assertEqual(zf.namelist(),
                             ["Yanga Koyina/Yanga_Koyina_Unemployment Affidavit.pdf"])

    def test_missing_id_can_still_be_treated_as_unprocessed(self):
        _, warnings, _, renamed, unprocessed, _ = self._run([
            ("Yanga Koyina Confirmation of Unemployment.pdf", "",
             "BBBE Certification: Affidavit to Confirm Unemployment"),
        ], allow_missing_id=False)
        self.assertEqual((renamed, unprocessed), (0, 1))
        self.assertTrue(warnings)

    def test_original_extension_is_preserved(self):
        logs, _, _, renamed, _, _ = self._run([
            ("Certified ID.jpg", "", ID_CARD_TEXT),
        ])
        self.assertEqual(renamed, 1)
        self.assertTrue(logs[0].endswith("_ID.jpg"), logs)

    def test_rejects_long_unspaced_ocr_text_as_name(self):
        long_ocr_blob = "Diensvicecentreclientserydoparkfaeldoracbepublicofsouthafricaliceserviieeeeericanposouthafeeadnationaiseniorcertificate"
        dense_text = f"REPUBLIC OF SOUTH AFRICA NATIONAL SENIOR CERTIFICATE AWARDED TO {long_ocr_blob} Identity Number: 0308121234089"
        first, last = app._extract_name_from_text(dense_text)
        # Long unspaced blob must NOT be accepted as a person name
        self.assertNotEqual(first, long_ocr_blob)
        self.assertNotEqual(last, long_ocr_blob)

    def test_fuzzy_candidate_matching_unifies_ocr_variants(self):
        logs, _, zip_buffer, renamed, unprocessed, errors = self._run([
            ("Certified ID.pdf", "", ID_CARD_TEXT),
            ("BBBE certification .pdf", "",
             "BBBE Certification: Affidavit to Confirm Unemployment hereby confirm Sinqita Hiunaawane am unemployed"),
            ("Declaration of criminal record status.pdf", "",
             "AFFIDAVIT: DECLARATION OF CRIMINAL RECORD STATUS I Coingita Hiunqnane declare no record"),
        ])
        self.assertEqual((renamed, unprocessed, errors), (3, 0, 0))
        with zipfile.ZipFile(zip_buffer) as zf:
            names = zf.namelist()
            self.assertTrue(all(name.startswith("Singita Hlungwane/") or name.startswith("Sinqita Hlungwane/") for name in names), names)
            self.assertTrue(all("0308121234089" in name for name in names), names)

    def test_user_exact_batch_unification_with_swapped_names(self):
        logs, warnings, zip_buffer, renamed, unprocessed, errors = self._run([
            ("Certified ID.pdf", "", "Republic of South Africa ID Card Surname: Ae Names: Singita Identity Number: 0308121302084"),
            ("BBBE certification .pdf", "", "BBBE Certification: Affidavit to Confirm Unemployment Sinqita Hiunaawane"),
            ("Declaration of criminal record status.pdf", "", "DECLARATION OF CRIMINAL RECORD STATUS Sinqita Hiunaawane"),
            ("Certified Matric.pdf", "", "REPUBLIC OF SOUTH AFRICA NATIONAL SENIOR CERTIFICATE Identity Number: 0308121302084"),
        ])
        self.assertEqual((renamed, unprocessed, errors), (4, 0, 0))
        with zipfile.ZipFile(zip_buffer) as zf:
            names = zf.namelist()
            self.assertEqual(len(names), 4)
            # All 4 files should belong to the same candidate and carry confirmed ID 0308121302084!
            self.assertTrue(all("0308121302084" in name for name in names), names)


if __name__ == "__main__":
    unittest.main()
