from pathlib import Path
import subprocess
import sys


MAX_DOCS = 5
MAX_IMAGE_BYTES = 1_048_576  # 1 MB per immagine
MAX_UPLOAD_BYTES = 50 * 1_048_576  # 50 MB per file caricato

DEPTH_LIMITS = {
    "low": {"chars_per_doc": 2_000, "total_chars": 6_000, "max_tokens": 512},
    "medium": {"chars_per_doc": 6_000, "total_chars": 24_000, "max_tokens": 1024},
    "high": {"chars_per_doc": 15_000, "total_chars": 50_000, "max_tokens": 2048},
}


def open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "linux":
        subprocess.Popen(["xdg-open", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])


def smart_truncate(text: str, limit: int) -> str:
    """Prendi inizio e fine del testo per non perdere le conclusioni."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n[…]\n\n" + text[-half:]


def extract_text(fp: Path, mime: str | None, chars_limit: int = 6_000) -> tuple[str, str]:
    """Return (text, mode) where mode is 'text' or 'image'."""
    mime = mime or ""
    suffix = fp.suffix.lower()

    if mime.startswith("image/") or suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return ("", "image")

    if mime == "application/pdf" or suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(fp))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
            return (smart_truncate(text, chars_limit), "text")
        except Exception as e:
            return (f"[Errore lettura PDF: {e}]", "text")

    if suffix in (".docx",) or "wordprocessingml" in mime:
        try:
            from docx import Document as DocxDoc
            doc = DocxDoc(str(fp))
            text = "\n".join(p.text for p in doc.paragraphs)
            return (smart_truncate(text, chars_limit), "text")
        except Exception as e:
            return (f"[Errore lettura DOCX: {e}]", "text")

    try:
        return (smart_truncate(fp.read_text(errors="replace"), chars_limit), "text")
    except Exception:
        return ("[Formato non supportato]", "text")
