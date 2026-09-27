from os import getenv
from pathlib import Path
from dotenv import load_dotenv

from src.utils.logger import get_logger

# Initialize central logger for config
logger = get_logger("Config")

# =====================================================================
# 2. PROJECT ROOT & ENVIRONMENT VARIABLES
# =====================================================================
# Resolves to the absolute root directory of the project (itcybx_live_bot)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
    logger.info(f"Loaded environment variables from: {ENV_FILE}")
else:
    logger.warning(f"No .env file found at {ENV_FILE}. Falling back to system environment variables.")

# =====================================================================
# 2. HELPER TO STRICTLY FETCH ENV VARIABLES
# =====================================================================
def get_env(key: str, required: bool = True, default: str = None) -> str:
    """
    Fetches an environment variable strictly.
    If required and missing/empty, logs an ERROR and immediately raises ValueError.
    """
    value = getenv(key)
    if value is not None and value.strip():
        return value.strip()

    if required:
        error_msg = f"Missing required environment variable '{key}' in .env! Execution stopped."
        logger.error(error_msg)
        raise ValueError(error_msg)
        

    return default if default is not None else ""


# =====================================================================
# 3. API KEYS & CREDENTIALS (Strict fail-fast, no silent fallbacks)
# =====================================================================
MISTRAL_API_KEY = get_env("MISTRAL_API_KEY", required=True)
PINECONE_API_KEY = get_env("PINECONE_API_KEY", required=True)
PINECONE_INDEX_NAME = get_env("PINECONE_INDEX_NAME", required=True)

# Optional Integrations (Redis for session memory)
REDIS_URL = get_env("REDIS_URL", required=False, default="")

# Deployment mode. "production" enforces stricter runtime requirements
# (e.g. a working Redis session store is mandatory, not an optional
# fallback) that would be unnecessary friction for local development.
ENV = get_env("ENV", required=False, default="development").lower()

# Admin key required to read/delete session transcripts via the API. Left
# unset by default so those endpoints stay LOCKED (fail-closed) until an
# operator explicitly configures it.
ADMIN_API_KEY = get_env("ADMIN_API_KEY", required=False, default="")

# =====================================================================
# 4. MISTRAL & VECTOR CONFIGURATION
# =====================================================================
EMBEDDING_MODEL = get_env("EMBEDDING_MODEL", required=False, default="mistral-embed")
EMBEDDING_DIMENSION = 1024
LLM_MODEL = get_env("LLM_MODEL", required=False, default="open-mistral-7b")

# =====================================================================
# 5. DATA DIRECTORIES & FILE PATHS (Path objects)
# =====================================================================
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
APPROVED_URLS_DIR = DATA_DIR / "approved"

# Subdirectories for raw and processed languages
RAW_EN_DIR = RAW_DATA_DIR / "en"
RAW_AR_DIR = RAW_DATA_DIR / "ar"
PROCESSED_EN_DIR = PROCESSED_DATA_DIR / "en"
PROCESSED_AR_DIR = PROCESSED_DATA_DIR / "ar"


if __name__ == "__main__":
    print("\n=======================================================")
    print("             IT CYBX BOT - SETTINGS CHECK              ")
    print("=======================================================")
    print(f"Base Directory       : {BASE_DIR}")
    print(f"Mistral API Key      : {'LOADED (OK)' if MISTRAL_API_KEY else 'MISSING!'}")
    print(f"Pinecone API Key     : {'LOADED (OK)' if PINECONE_API_KEY else 'MISSING!'}")
    print(f"Pinecone Index Name  : {PINECONE_INDEX_NAME}")
    print(f"Redis URL            : {'CONFIGURED' if REDIS_URL else 'NOT SET (In-memory session store)'}")
    print(f"Embedding Model      : {EMBEDDING_MODEL} (Dim: {EMBEDDING_DIMENSION})")
    print(f"LLM Model            : {LLM_MODEL}")
    print(f"Processed Data Dir   : {PROCESSED_DATA_DIR}")
    print("=======================================================\n")
    logger.info("All essential environment settings loaded and verified successfully.")


