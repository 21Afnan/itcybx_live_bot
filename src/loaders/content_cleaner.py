import re
from pathlib import Path

from src.config.settings import RAW_EN_DIR, RAW_AR_DIR, PROCESSED_EN_DIR, PROCESSED_AR_DIR
from src.utils.logger import get_logger

logger = get_logger("ContentCleaner")


class ItCybxContentCleaner:
    """
    Cleans raw scraped .txt files for both English and Arabic.
    - Strips navigation headers
    - Strips footer boilerplate (contact info, address, social links, back to top)
    - Strips placeholder Latin demo text and extra search snippets
    - Normalizes blank lines and whitespace
    - Saves clean files to data/processed/en/ and data/processed/ar/
    """

    # --- ENGLISH BOILERPLATE DEFINITIONS ---
    EN_NAV_BLOCK = """IT Cybx
The Growth Audit
What We Do
Our Work
About Us
Pricing
Contacts
العربية"""

    EN_HEADER_EXTRA = [
        "Call Us: +92 310 488 7999 \n\nSearch\n\n",
        "Call Us: +92 310 4887 999 \n\nSearch\n\n",
        "Call Us: +92 310 488 7999",
        "Call Us: +92 310 4887 999",
        "Search",
    ]

    EN_FOOTER_MARKERS = [
        "Testimonials \n\nWhat Our Client’s Say",
        "Testimonials",
        "Cum et essent similique",
        "+92 310 488 7999info@itcybx.co.uk",
        "+92 310 4887 999info@itcybx.co.uk",
        "Office #2, Friend Arcade",
        "Back to top",
    ]

    # --- ARABIC BOILERPLATE DEFINITIONS ---
    AR_NAV_BLOCK = """الرئيسية
تقييم النمو
ماذا نقدّم
أعمالنا
من نحن
التسعير
تواصل
English"""

    AR_HEADER_EXTRA = [
        "+92 310 4887 999 :اتصل بنا \n\n\n\n\n\n\n\nSearch",
        "+92 310 4887 999 :اتصل بنا",
        "+92 310 488 7999 :اتصل بنا",
        "Search",
    ]

    AR_FOOTER_MARKERS = [
        "Testimonials",
        "Cum et essent similique",
        "+92 310 4887 999info@itcybx.co.uk",
        "+92 310 488 7999info@itcybx.co.uk",
        "المكتب رقم ٢، فريند أركيد",
        "Back to top",
    ]

    def __init__(
        self,
        raw_en_dir: Path = RAW_EN_DIR,
        raw_ar_dir: Path = RAW_AR_DIR,
        processed_en_dir: Path = PROCESSED_EN_DIR,
        processed_ar_dir: Path = PROCESSED_AR_DIR,
    ):
        self.raw_en_dir = Path(raw_en_dir)
        self.raw_ar_dir = Path(raw_ar_dir)
        self.processed_en_dir = Path(processed_en_dir)
        self.processed_ar_dir = Path(processed_ar_dir)

    def clean_text_en(self, text: str) -> str:
        """Cleans a single English page."""
        # 1. Separate metadata header (SOURCE_URL / LANGUAGE) if present
        header = ""
        if text.startswith("SOURCE_URL:"):
            parts = text.split("\n\n", 1)
            if len(parts) == 2:
                header = parts[0] + "\n\n"
                text = parts[1]

        # 2. Remove nav menu
        text = text.replace(self.EN_NAV_BLOCK, "")

        # 3. Remove header extras
        for extra in self.EN_HEADER_EXTRA:
            text = text.replace(extra, "")

        # 4. Cut off footer from the earliest footer marker
        for marker in self.EN_FOOTER_MARKERS:
            pos = text.find(marker)
            if pos != -1:
                text = text[:pos]
                break

        # 5. Collapse 3+ newlines into 2
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        # 6. Collapse multiple spaces
        text = re.sub(r"[ \t]{2,}", " ", text)

        return (header + text.strip()).strip()

    def clean_text_ar(self, text: str) -> str:
        """Cleans a single Arabic page."""
        # 1. Separate metadata header (SOURCE_URL / LANGUAGE) if present
        header = ""
        if text.startswith("SOURCE_URL:"):
            parts = text.split("\n\n", 1)
            if len(parts) == 2:
                header = parts[0] + "\n\n"
                text = parts[1]

        # 2. Remove Arabic nav menu
        text = text.replace(self.AR_NAV_BLOCK, "")

        # 3. Remove header extras
        for extra in self.AR_HEADER_EXTRA:
            text = text.replace(extra, "")

        # 4. Cut off footer from the earliest footer marker
        for marker in self.AR_FOOTER_MARKERS:
            pos = text.find(marker)
            if pos != -1:
                text = text[:pos]
                break

        # 5. Collapse 3+ newlines into 2
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        # 6. Collapse multiple spaces
        text = re.sub(r"[ \t]{2,}", " ", text)

        return (header + text.strip()).strip()

    def clean_en_files(self):
        """Cleans all raw English files."""
        self.processed_en_dir.mkdir(parents=True, exist_ok=True)
        if not self.raw_en_dir.exists():
            logger.warning(f"'{self.raw_en_dir}' does not exist yet. Run sitemap_loader.py first.")
            return

        files = sorted(list(self.raw_en_dir.glob("*.txt")))
        logger.info(f"--- Cleaning English Files ({len(files)} files) ---")

        for file_path in files:
            raw_text = file_path.read_text(encoding="utf-8")
            cleaned = self.clean_text_en(raw_text)
            clean_path = self.processed_en_dir / file_path.name
            clean_path.write_text(cleaned, encoding="utf-8")
            logger.info(f"  • [EN] Cleaned {file_path.name} ({len(raw_text)} -> {len(cleaned)} chars)")

    def clean_ar_files(self):
        """Cleans all raw Arabic files."""
        self.processed_ar_dir.mkdir(parents=True, exist_ok=True)
        if not self.raw_ar_dir.exists():
            logger.warning(f"'{self.raw_ar_dir}' does not exist yet. Run sitemap_loader.py first.")
            return

        files = sorted(list(self.raw_ar_dir.glob("*.txt")))
        logger.info(f"--- Cleaning Arabic Files ({len(files)} files) ---")

        for file_path in files:
            raw_text = file_path.read_text(encoding="utf-8")
            cleaned = self.clean_text_ar(raw_text)
            clean_path = self.processed_ar_dir / file_path.name
            clean_path.write_text(cleaned, encoding="utf-8")
            logger.info(f"  • [AR] Cleaned {file_path.name} ({len(raw_text)} -> {len(cleaned)} chars)")

    def clean_all(self):
        """Cleans both English and Arabic files."""
        logger.info("Starting Content Cleaner for EN & AR...")
        self.clean_en_files()
        self.clean_ar_files()
        logger.info("All files successfully cleaned and saved to data/processed/en/ and data/processed/ar/!")


if __name__ == "__main__":
    cleaner = ItCybxContentCleaner()
    cleaner.clean_all()
