"""
Child process entry point for anydoc conversion. Not imported — spawned by
ingestion/anydoc_convert.py, which explains why the isolation exists.

Reads a document path, writes the converted Markdown to an output path, and
reports the outcome as a single JSON line on stdout. Uses print() rather than
the project logger on purpose: stdout is this script's return channel to the
parent, and nothing else may be written to it.
"""

import json
import sys


def main() -> int:
    doc_path, out_path = sys.argv[1], sys.argv[2]

    try:
        import anydoc
    except ImportError as e:
        print(json.dumps({"status": "error", "detail": f"anydoc not installed: {e}"}))
        return 1

    try:
        markdown = anydoc.to_markdown(doc_path)
    except anydoc.UnsupportedError as e:
        # A scanned or image-only PDF reports "OCR is required". That is not a
        # failure — it is the signal to hand the file to the VLM path instead.
        status = "ocr_required" if "OCR is required" in str(e) else "unsupported"
        print(json.dumps({"status": status, "detail": str(e)}))
        return 0
    except anydoc.EncryptedError as e:
        print(json.dumps({"status": "encrypted", "detail": str(e)}))
        return 0
    except (anydoc.MalformedError, anydoc.MissingPartError) as e:
        print(json.dumps({"status": "malformed", "detail": str(e)}))
        return 0
    except (anydoc.ResourceLimitError, anydoc.ConvertError, OSError, ValueError) as e:
        print(json.dumps({"status": "error", "detail": f"{type(e).__name__}: {e}"}))
        return 0

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(json.dumps({"status": "ok", "chars": len(markdown)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
