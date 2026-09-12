"""
Extract entities for documents whose text changed and rebuild the canonical
entity index.

    python scripts/extract_entities.py
    python scripts/extract_entities.py --force    # redo every document

Equivalent to: python scripts/run_pipeline.py --stages refresh,entities
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import runpy

if __name__ == '__main__':
    sys.argv = [sys.argv[0], '--stages', 'refresh,entities'] + sys.argv[1:]
    runpy.run_path(os.path.join(os.path.dirname(__file__), 'run_pipeline.py'), run_name='__main__')
