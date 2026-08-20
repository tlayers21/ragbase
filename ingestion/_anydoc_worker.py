import json
import sys


def main() -> int:
    """Convert one document and report the outcome as a single JSON line on stdout.

    Uses print() rather than the project logger because stdout is this script's
    only return channel to the parent process.
    """
    doc_path, out_path = sys.argv[1], sys.argv[2]

    try:
        import anydoc
    except ImportError as e:
        print(json.dumps({"status": "error", "detail": f"anydoc not installed: {e}"}))
        return 1

    try:
        markdown = anydoc.to_markdown(doc_path)
    except anydoc.UnsupportedError as e:
        # "OCR is required" is the signal to use the VLM path, not a failure
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
