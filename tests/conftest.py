"""Point all local storage at a throwaway directory before any module loads.

Always overrides EVOSTRATEGY_DATA_DIR (never ``setdefault``): several tests
reset the registry, and they must never touch a real workspace even when the
developer's shell has EVOSTRATEGY_DATA_DIR set.
"""

import os
import tempfile

os.environ["EVOSTRATEGY_DATA_DIR"] = tempfile.mkdtemp(prefix="evostrategy-tests-")
os.environ["LLM_PROVIDER"] = "rules"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OCR_SECOND_ENGINE", None)
