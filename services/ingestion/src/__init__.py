# Python package init files

# The NLP pipeline lives in nlp_sts/ at the repository root (/app/nlp_sts in
# Docker); put its parent folder on the import path so `import nlp_sts` works
import sys
from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "nlp_sts").is_dir():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break
