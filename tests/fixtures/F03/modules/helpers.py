"""AC-F03-38's planted module (06 §5.4). If it is ever imported, it leaves ZZMARK.txt in the
working directory and stops the process: ``module()`` must refuse it before that."""

from pathlib import Path

Path("ZZMARK.txt").write_text("imported", encoding="utf-8")
raise SystemExit("ZZMARK")
