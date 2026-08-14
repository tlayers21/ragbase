import re

from config.logging import setup_logging

logger = setup_logging(__name__)


def normalize_title(title: str) -> str:
    """
    Repair a short LLM-generated title that came back as a single run-together token.
    """
    stripped = title.strip()
    if not stripped or " " in stripped:
        return stripped

    # Separator-delimited first ("gradient-descent-explained"), then CamelCase.
    spaced = re.sub(r"[-_]+", " ", stripped)
    if " " not in spaced:
        # lower/digit -> upper, plus the tail of an acronym run ("PDFParser" -> "PDF Parser").
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
        spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)

    return spaced.strip()
