"""
Rebuild the dense and lexical indexes (embed what is stale, then index).

    python scripts/build_indexes.py
    python scripts/build_indexes.py --force      # re-embed everything

Equivalent to: python scripts/run_pipeline.py --stages refresh,embed,index
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import runpy

if __name__ == '__main__':
    sys.argv = [sys.argv[0], '--stages', 'refresh,embed,index'] + sys.argv[1:]
    runpy.run_path(os.path.join(os.path.dirname(__file__), 'run_pipeline.py'), run_name='__main__')
