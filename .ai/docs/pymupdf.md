# PyMuPDF 1.27.2 — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: 1.27.2.3 (imported as `fitz`)
> Re-fetch when version changes or docs feel stale

## Import

```python
import pymupdf    # modern alias (1.24+)
# or
import fitz       # classic alias — still works
```

Both names refer to the same package; PyMuPDF's own docs now favor `import pymupdf`.

---

## Opening Documents

```python
import pymupdf

# From file path (str or pathlib.Path)
doc = pymupdf.open("some.pdf")

# Wrong/no extension — force a filetype
doc = pymupdf.open("some.file", filetype="xps")
doc = pymupdf.open("some.file", filetype="txt")   # treat as plain text

# From memory (in-memory bytes — used for UploadFile content)
doc = pymupdf.open(stream=mem_area, filetype="pdf")

# New empty PDF
doc = pymupdf.open()
doc = pymupdf.open(None)

# Context manager (auto-close)
with pymupdf.open("document.pdf") as doc:
    for page in doc:
        text = page.get_text()
```

### `open()` / `Document()` signature

```
open(filename=None, stream=None, filetype=None, archive=None,
     rect=None, width=0, height=0, fontsize=11)
```

| Param | Type | Notes |
|-------|------|-------|
| `filename` | str, pathlib.Path | file path; also accepts objects with a `.name` attribute |
| `stream` | bytes, bytearray, BytesIO | in-memory content. `bytes`/`memoryview` are borrowed (kept alive via `self.stream`); `bytearray`/`BytesIO` are copied to `bytes` internally. `mmap` and generic file objects are rejected. |
| `filetype` | str | explicit type when content inspection/extension is ambiguous; required in some cases with `stream` |
| `archive` | Archive | resource archive object |
| `rect` | rect_like | page size for reflowable documents |
| `width`, `height` | float | page size for reflowable documents |
| `fontsize` | float | default 11, for reflowable documents |

Raises `EmptyFileError` for a zero-length file/stream, `FileNotFoundError` for a missing path, `FileDataError` if the stream/file can't be parsed as the given type.

---

## Document Properties

```python
doc.page_count          # int — total pages
len(doc)                 # same as page_count
doc.metadata             # dict — title/author/subject/creator/producer/creationDate/modDate/format/encryption
doc.is_pdf                # bool
doc.is_encrypted          # bool
doc.name                  # file name (or "" for stream)
```

---

## Page Access

```python
page = doc[0]               # by index (0-based)
page = doc[-1]               # last page
page = doc.load_page(0)      # equivalent to doc[0]

for page in doc:              # iterate all pages
    print(page.number)        # 0-based

for page in doc.pages(0, 5):              # pages 0–4
    ...
for page in doc.pages(start=2, stop=10, step=2):
    ...
```

---

## `Page.get_text()`

```
get_text(option, *, clip=None, flags=None, textpage=None, sort=False, delimiters=None)
```

| Option | Returns |
|--------|---------|
| `"text"` (default) | plain text string |
| `"layout"` | text preserving whitespace/column layout |
| `"blocks"` | list of `(x0, y0, x1, y1, text, blockno, blocktype)` |
| `"words"` | list of `(x0, y0, x1, y1, word, blockno, lineno, wordno)` |
| `"html"` / `"xhtml"` / `"xml"` | markup with font/style info |
| `"dict"` / `"rawdict"` | structured dict of blocks/lines/spans (`rawdict` adds raw character data) |
| `"json"` / `"rawjson"` | JSON encoding of the dict/rawdict format |
| `"markdown"` | Markdown (1.24+) |

Extra kwargs:
- `clip` — restrict extraction to a rect
- `flags` — bitwise control, e.g. `pymupdf.TEXTFLAGS_BLOCKS | pymupdf.TEXT_PRESERVE_IMAGES` to include images in `"blocks"`, or `pymupdf.TEXT_INHIBIT_SPACES` to suppress inserted spaces
- `sort` — reorder output into reading order
- `textpage` — pass a pre-built `TextPage` to speed up repeated extraction on the same page

```python
# Text with font/size metadata
blocks = page.get_text("dict")["blocks"]
for block in blocks:
    if block["type"] == 0:   # text block
        for line in block["lines"]:
            for span in line["spans"]:
                print(f"{span['text']!r} font={span['font']} size={span['size']:.1f}")
```

Extraction mode guidance: `"text"` for simple extraction, `"blocks"` for paragraph identification, `"words"` for spatial analysis, `"dict"`/`"rawdict"` for character-level styling detail.

---

## Page Properties

```python
page.number         # int — 0-based page index
page.rect           # pymupdf.Rect — page bounding box in points
page.rotation       # int — rotation in degrees
```

---

## `Page.get_images()`

```python
image_list = page.get_images(full=True)
# (xref, smask, width, height, bpc, colorspace, alt_colorspace, name, filter, referencer)

for img_info in image_list:
    xref = img_info[0]
    pix = pymupdf.Pixmap(doc, xref)
    if pix.n > 4:                      # CMYK → convert to RGB
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    pix.save(f"image_{xref}.png")
    pix = None                          # free memory
```

---

## Closing

```python
doc.close()   # always close when done (or use a context manager)
```

---

## RAGbase-Specific Notes

- **Used in**: `api/query.py` for chat attachment PDF extraction only. **Not used for**: ingestion — that uses Docling instead.
- RAGbase uses `import fitz` throughout (the classic alias), not the newer `import pymupdf`.
- RAGbase uses `page.get_text()` (plain text, default `"text"` mode) for chat attachment extraction — fast, no structure needed.
- The `fitz` import is lazy (inside the function) to avoid slowing down server startup — same lazy-heavy-dep pattern used for docling/pdf2image/yt_dlp elsewhere in the codebase.

**RAGbase PDF extraction pattern** (`api/query.py`):

```python
def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 8000) -> str:
    import fitz   # lazy import — heavy dep, only when needed

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        pages = []
        for page in doc:
            text = page.get_text().strip()
            if text:
                pages.append(f"[Page {page.number + 1}]\n{text}")
        full_text = "\n\n".join(pages)
        return full_text[:max_chars]   # truncate to ATTACHMENT_TEXT_MAX_CHARS
```

**Two PDF paths in RAGbase** — never cross them:

| Use case | Library | Location | Why |
|----------|---------|----------|-----|
| Ingestion (indexing) | Docling | `ingestion/pdf.py` | Layout analysis, OCR, page-by-page chunking |
| Chat attachment (one-shot) | PyMuPDF | `api/query.py` | Fast text extraction, no indexing needed |
