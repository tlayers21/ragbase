# Docling — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: 2.x (check pyproject.toml — pinned `docling>=2.0.0`)
> Re-fetch when version changes or docs feel stale

---

## DocumentConverter

```python
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat

# Basic — auto-detect format from file extension, standard pipeline defaults
converter = DocumentConverter()

# Restrict to specific formats
converter = DocumentConverter(
    allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML]
)
```

### convert()

```python
# From file path or URL
result = converter.convert("path/to/document.pdf")
result = converter.convert("https://arxiv.org/pdf/2408.09869")

# From in-memory stream
from io import BytesIO
from docling.datamodel.base_models import DocumentStream

buf = BytesIO(pdf_bytes)
stream = DocumentStream(name="doc.pdf", stream=buf)
result = converter.convert(stream)
```

### convert_all()

```python
for result in converter.convert_all(["doc1.pdf", "doc2.docx"]):
    print(result.document.export_to_markdown())
```

---

## ConversionResult

```python
result.document       # DoclingDocument — the converted document
result.status         # ConversionStatus enum (.success, .failure, etc.)
result.errors         # list of errors encountered
result.timestamp      # conversion timestamp
result.timings        # processing duration data per stage
result.confidence     # ConfidenceReport with quality metrics

if result.status.success:
    doc = result.document
```

---

## DoclingDocument Structure

```python
doc = result.document

doc.texts       # list[TextItem] — all text elements in reading order
doc.pictures    # list[PictureItem] — embedded images
doc.tables      # list[TableItem] — detected tables
doc.pages       # dict[int, Page] — page metadata (dimensions etc.), NOT text content
```

Content is organized into content items (texts, tables, pictures, key-value items — all `DocItem` subclasses) plus content structure (`body`, `furniture`, `groups` as tree roots of `NodeItem`s).

**Preferred iteration API**: `doc.iterate_items()` walks the document in reading order with hierarchy depth, and is the documented way to distinguish item types:

```python
from docling_core.types.doc import TextItem, TableItem

for item, level in doc.iterate_items():
    if isinstance(item, TextItem):
        print(item.text)
    elif isinstance(item, TableItem):
        df = item.export_to_dataframe(doc=doc)   # pandas DataFrame
        print(df.to_markdown())
    elif hasattr(item, "label") and item.label.name == "SECTION_HEADER":
        print(f"{'#' * level} {item.text}")

for picture in doc.pictures:
    print(picture.caption_text(doc))   # caption if present
```

`doc.print_element_tree()` dumps the full structure for inspection/debugging.

---

## TextItem / ProvenanceItem

```python
for text_item in doc.texts:
    text_item.text     # str — text content
    text_item.label     # DocItemLabel: TEXT, TITLE, SECTION_HEADER, LIST_ITEM,
                         #   CAPTION, FOOTNOTE, TABLE, PICTURE, CODE, etc.
    text_item.prov      # list[ProvenanceItem] — may be empty
    text_item.orig      # str — original source text before normalization

prov = text_item.prov[0]   # always check: if not text_item.prov: continue
prov.page_no               # int — 1-indexed page number
prov.bbox                  # BoundingBox — position on page
prov.charspan              # tuple[int, int] — character span (if available)
```

**Grouping text by page** (documented pattern, `doc.pages.get(page_no)` for page metadata):

```python
from collections import defaultdict

pages: dict[int, list[str]] = defaultdict(list)
for item, _ in doc.iterate_items():
    if isinstance(item, TextItem) and item.prov:
        page_no = item.prov[0].page_no
        pages[page_no].append(item.text)

for page_no in sorted(pages):
    page_text = "\n".join(pages[page_no])
```

---

## Export Methods

```python
md = doc.export_to_markdown()          # full document as markdown
json_data = doc.export_to_dict()       # full document as dict (JSON-serializable)
tokens = doc.export_to_document_tokens()  # doc-tag token representation

# Round-trip via JSON
import json
from pathlib import Path
from docling_core.types.doc import DoclingDocument

Path("./doc.json").write_text(json.dumps(doc.export_to_dict()))
doc2 = DoclingDocument.model_validate(json.loads(Path("./doc.json").read_text()))
```

---

## Images in PDFs

```python
for picture in doc.pictures:
    if not picture.prov:
        continue
    page_no = picture.prov[0].page_no
    img = picture.get_image(doc)   # PIL Image
    if img:
        img.save(f"page{page_no}_img.png")
```

---

## Pipeline Options (OCR)

```python
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

opts = PdfPipelineOptions(
    do_ocr=True,               # False = skip OCR entirely
    do_table_structure=True,   # False = skip table detection (faster)
)

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=opts),   # key must be InputFormat.PDF, not "pdf"
    }
)
```

### OCR engine selection

`PdfPipelineOptions(do_ocr=True)` defaults to **EasyOCR** (no extra install needed). Other engines are opt-in via `ocr_options`:

```python
from docling.datamodel.pipeline_options import RapidOcrOptions, TesseractOcrOptions, OcrMacOptions

opts = PdfPipelineOptions(do_ocr=True, ocr_options=RapidOcrOptions())      # lightweight, no C deps
opts = PdfPipelineOptions(do_ocr=True, ocr_options=TesseractOcrOptions()) # requires system tesseract + tesserocr
opts = PdfPipelineOptions(do_ocr=True, ocr_options=OcrMacOptions())        # macOS native OCR

# Language selection (engine-dependent)
opts.ocr_options.lang = ["en"]

# RapidOCR GPU backend
opts.ocr_options = RapidOcrOptions(backend="torch")
```

---

## Lazy Import Pattern

Docling is heavy; import it inside the function that needs it rather than at module scope, to avoid slowing down server startup:

```python
def _convert_pdf(path: str):
    from docling.document_converter import DocumentConverter   # lazy
    return DocumentConverter().convert(path)
```

---
## RAGbase-Specific Notes

- **Critical gotcha**: `doc.pages` has NO text — it's page metadata only (dimensions etc.). Always iterate `doc.texts` with `.prov[0].page_no`, never iterate `doc.pages` looking for text.
- **Gotcha**: `doc.export_to_markdown(page_no=N)` is unreliable in Docling 2.x — often returns empty string. RAGbase always groups `doc.texts` by `prov[0].page_no` instead (core pattern in `ingestion/pdf.py::_extract_typed_pages()`).
- Items with an empty `prov` list are skipped (some items have no provenance).
- **Doc/code mismatch found in 2026-08-06 audit**: this file previously claimed RAGbase explicitly configures RapidOCR via `ocr_options=RapidOcrOptions()`. It does not — `ingestion/pdf.py::extract_text()` constructs a bare `DocumentConverter()` with no `ocr_options=` at all, and `rapidocr` isn't a declared dependency in `pyproject.toml`. Typed-PDF OCR actually runs on Docling's own default engine, **EasyOCR**. If RapidOCR was the intended engine, `ocr_options=RapidOcrOptions()` needs to be set explicitly on a `PdfFormatOption` — flagged for a human decision, not silently fixed.
- Docling import is lazy (inside the function) to avoid slowing down server startup, matching the same lazy-heavy-dep pattern used for `pdf2image`/`yt_dlp`/`fitz` elsewhere in the codebase.
- **Handwritten vs typed detection** (`ingestion/pdf.py::_is_handwritten()`):

```python
def _is_handwritten(self, doc) -> bool:
    total_images = len(doc.pictures)
    total_text_items = len(doc.texts)
    return (
        total_images >= HANDWRITTEN_IMAGE_THRESHOLD      # 5, from config/settings.py
        and total_text_items <= HANDWRITTEN_TEXT_THRESHOLD  # 200, from config/settings.py
    )
```

  If handwritten → Qwen2.5-VL page-by-page (no OCR). If typed → the `doc.texts` iteration path (Docling OCR via its default engine, EasyOCR — see the mismatch note above).
