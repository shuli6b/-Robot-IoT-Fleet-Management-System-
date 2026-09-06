"""Compatibility entry point using the single verified production driver."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from huashu_real_bridge import main

if __name__=='__main__':
    main()
