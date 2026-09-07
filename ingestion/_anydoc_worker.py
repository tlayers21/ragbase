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
        # ocr="reject" is anydoc's default, but pin it: "hosted" uploads the PDF to
        # Firecrawl, and nothing in RAGbase may reach the network.
        markdown = anydoc.to_markdown(doc_path, ocr="reject")
    except anydoc.NeedsOcrError as e:
        # Not a failure - the signal to route around anydoc. `pages` lists every page
        # with no text layer, so the parent can tell a scan from one bad page in a book.
        print(
            json.dumps(
                {
                    "status": "ocr_required",
                    "detail": str(e),
                    "ocr_pages": len(e.pages),
                    "page_count": e.page_count,
                }
            )
        )
        return 0
    except anydoc.UnsupportedError as e:
        print(json.dumps({"status": "unsupported", "detail": str(e)}))
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
