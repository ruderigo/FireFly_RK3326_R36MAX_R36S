"""Faster proof-of-work stamps, bit-identical to LXMF's.

A stamp is valid when SHA-256(workblock + stamp) is under a target. LXMF's
workers hash the whole workblock (256 KB for a propagation-node stamp) again
for every 32-byte candidate. SHA-256 reads its input front to back, so the
workblock's part of the state can be computed once and copied for each
attempt: 32 bytes hashed per attempt instead of 256 KB, with exactly the same
digests and therefore exactly the same valid stamps. The technique is the one
FireFly for Android uses (FireFly client quickstart, Oct 2026).

install() swaps this search into LXMF's stamper. Nothing else changes: the
same workblock, the same target, the same validation on the receiving side.
"""
import hashlib
import os

import LXMF.LXStamper as S

_original_cancel = S.cancel_work


def fast_job(stamp_cost, workblock, message_id):
    """Drop-in for LXMF's job_* functions: returns (stamp or None, rounds)."""
    S.active_jobs[message_id] = False              # True = cancelled (see cancel_work)
    base = hashlib.sha256(workblock)               # the 256 KB part, hashed once
    target = 1 << (256 - stamp_cost)
    urandom, from_bytes = os.urandom, int.from_bytes
    rounds, stamp = 0, None
    jobs = S.active_jobs
    while not jobs.get(message_id):
        candidate = urandom(32)
        h = base.copy()
        h.update(candidate)
        rounds += 1
        if from_bytes(h.digest(), "big") <= target:
            stamp = candidate
            break
        if rounds & 0x3FF == 0 and jobs.get(message_id) is None:
            break                                  # job record removed: treat as cancelled
    if jobs.get(message_id) is True:
        stamp = None
    jobs.pop(message_id, None)
    return stamp, rounds


def _cancel_work(message_id):
    if isinstance(S.active_jobs.get(message_id), bool):
        S.active_jobs[message_id] = True
    else:
        _original_cancel(message_id)


def install():
    S.job_linux = fast_job
    S.job_linux_managed = fast_job
    S.job_simple = fast_job
    S.cancel_work = _cancel_work
