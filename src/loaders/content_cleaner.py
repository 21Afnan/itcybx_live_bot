# src/loaders/content_cleaner.py

import os
import re


class ItCybxContentCleaner:
    """
    Cleans raw scraped .txt files by removing the repeated
    navigation/footer boilerplate and excess blank lines,
    then saves clean versions into data/processed/en/.
    """

    # Exact text blocks that repeat on EVERY page - safe to remove everywhere.
    # Taken directly from your raw files.
    NAV_BLOCK = """IT Cybx
The Growth Audit
What We Do
Our Work
About Us
Pricing
Contacts
العربية"""

    FOOTER_MARKERS = [
        "+92 310 488 7999info@itcybx.co.uk",   # footer contact info starts here
        "Back to top",                          # footer always ends here
    ]

    def __init__(self, raw_dir="data/raw", processed_dir="data/processed/en"):
        self.raw_dir = raw_dir
        self.processed_dir = processed_dir

    def clean_text(self, text):
        """Applies all cleaning steps to one page's text."""

        # 1. Remove the repeated nav block
        text = text.replace(self.NAV_BLOCK, "")

        # 2. Remove everything from the footer's start marker onward
        #    (contact info, About blurb, social links, policies, copyright, Back to top)
        footer_start = text.find(self.FOOTER_MARKERS[0])
        if footer_start != -1:
            text = text[:footer_start]

        # 3. Collapse 3+ blank lines into just 1 blank line
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

        # 4. Collapse repeated spaces
        text = re.sub(r"[ \t]{2,}", " ", text)

        # 5. Trim leading/trailing whitespace
        return text.strip()

    def clean_all(self):
        """Reads every raw .txt file, cleans it, saves to processed/en/."""
        os.makedirs(self.processed_dir, exist_ok=True)
        raw_files = [f for f in os.listdir(self.raw_dir) if f.endswith(".txt")]

        print(f"Found {len(raw_files)} raw files to clean.\n")

        for filename in raw_files:
            raw_path = os.path.join(self.raw_dir, filename)
            with open(raw_path, "r", encoding="utf-8") as f:
                raw_text = f.read()

            cleaned = self.clean_text(raw_text)

            clean_path = os.path.join(self.processed_dir, filename)
            with open(clean_path, "w", encoding="utf-8") as f:
                f.write(cleaned)

            print(f"  • Cleaned [{filename}] "
                  f"({len(raw_text)} chars -> {len(cleaned)} chars)")

        print(f"\nDone! Cleaned files saved to '{self.processed_dir}/'")


if __name__ == "__main__":
    cleaner = ItCybxContentCleaner()
    cleaner.clean_all()
