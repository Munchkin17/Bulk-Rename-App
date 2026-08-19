import os
import re
import io
_FILENAME_STOPWORDS = {
    "certified", "cert", "id", "identity", "document", "doc", "declaration", "affidavit",
    "criminal", "record", "status", "matric", "certificate", "certification", "unemployment",
    "bbbe", "bbbe", "birth", "copy", "scan", "original", "statement", "application",
    "bbbe", "bbbee", "birth", "copy", "scan", "original", "statement", "application",
    "form", "notice", "receipt", "of", "the", "and", "to", "number", "identitydocument",
    "identitycard", "declarationofcriminalrecordstatus",
    "confirmation", "confirm", "consent", "proof", "residence", "address", "bank", "banking",
    "report", "signed", "final", "updated", "completion", "training", "cellphone", "phone",
    "eea1", "mie", "ba", "capaciti", "coursera", "certificates", "docs", "files", "file",
    "online", "wk", "week", "batch", "folder", "candidate", "submission", "upload",
    "umalusi", "matric", "confirmation",
    "umalusi", "matric", "confirmation", "diens", "polisiediens", "sertifikaat", "nasionale",
}

_GENERIC_NAME_TOKENS = {
    "online", "wk", "week", "batch", "folder", "documents", "document", "files", "file",
    "bbbe", "certification", "certificate", "affidavit", "declaration", "criminal",
    "record", "status", "unemployment", "id", "identity", "umalusi", "matric",
    "confirmation",
    "confirmation", "diens", "polisiediens", "sertifikaat", "nasionale", "uitslae",
}


}

_ID_RUN_RE = re.compile(
    r'[0-9' + ''.join(OCR_EQUIVALENTS) + r'](?:[ \-./]{0,2}[0-9' + ''.join(OCR_EQUIVALENTS) + r']){11,24}',
    r'[0-9' + ''.join(OCR_EQUIVALENTS) + r'](?:[ \-./|]{0,3}[0-9' + ''.join(OCR_EQUIVALENTS) + r']){11,24}',
    re.I,
)

