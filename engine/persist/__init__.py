"""Persistent data on disk (F12): where the file lives (``location``), its format, reading,
merging, and encoding (``fileformat``), with the file limits in ``limits``, the one file
writer thread shared by every owner (``writer``), the frame-loop sync that decides when to
write and merges another copy's file (``sync``), and the warning texts (``texts``). F16's
player settings file (``settings_file``) lives in its own folder and uses the same
``safefile`` routines.

Imports ``core``, ``script``, and ``runtime`` only; never pygame (ADR-0002). Everything read
from the persistent folder is untrusted (F12 ``05-security.md``).
"""
