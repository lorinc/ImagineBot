#!/usr/bin/env python3
# Shim — build_index.py moved to src/ingestion/build_index.py
import runpy, sys
from pathlib import Path
sys.argv[0] = str(Path(__file__).parent.parent / "src" / "ingestion" / "build_index.py")
runpy.run_path(sys.argv[0], run_name="__main__")
