"""Point all local storage at a throwaway directory before any module loads."""

import os
import tempfile

os.environ.setdefault("EVOSTRATEGY_DATA_DIR", tempfile.mkdtemp(prefix="evostrategy-tests-"))
os.environ.setdefault("LLM_PROVIDER", "rules")
os.environ.pop("GEMINI_API_KEY", None)
