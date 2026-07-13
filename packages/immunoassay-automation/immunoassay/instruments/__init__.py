"""Instrument adapters: the plate washer, the liquid handler, and the spot imager.

Every stage speaks to instruments through an adapter, and every adapter records what it did
as an ActionRecord before doing it. In simulation the record is the whole story and the
adapter returns synthetic readings; in hardware the record carries the resolved Pi command.
See base.py for the shared bookkeeping.
"""
