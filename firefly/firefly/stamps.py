"""Faster proof-of-work stamps for LXMF messages, bit-identical to Reticulum's.

A stamp is valid when SHA-256(workblock + stamp) is under a target. The
stamp workers hash the whole workblock (768 KB for a message stamp, 256 KB
for a propagation-node one) again for every candidate. SHA-256 reads its
input front to back, so the workblock's part of the state can be computed
once and copied for each attempt: only the candidate is hashed per attempt
instead of the whole block, with exactly the same digests and therefore
exactly the same valid stamps. The technique is the one FireFly for Android
uses (FireFly client quickstart, Oct 2026).

Since LXMF 1.3.1 the stamp workers live in Reticulum (RNS.Stamps, 1.6.1):
LXMF's stamper hands them the workblock, the cost as Reticulum's fixed-point
value (fractional costs) and the stamp size. install() puts this search in
front of them for large workblocks only. Small ones (Reticulum 1.6.1's
announce and path-request stamps, a 90-byte block) gain nothing from it and
keep Reticulum's own workers, which use every core. Nothing else changes:
the same workblock, the same target, the same validation on the receiving
side, and Reticulum's own cancel_work stops it (a job marked True).
"""
import hashlib
import os

import RNS.Stamps as S

BIG_WORKBLOCK = 4096      # bytes: below this, Reticulum's multi-core workers are faster

_originals = {}


def fast_job(stamp_cost, workblock, message_id, size):
    """One core, the workblock hashed once: returns (stamp or None, rounds).
    stamp_cost is Reticulum's fixed-point cost (RNS.Stamps.cost_to_fp)."""
    jobs = S.active_jobs
    jobs[message_id] = False                       # True = cancelled (RNS.Stamps.cancel_work)
    base = hashlib.sha256(workblock)               # the big part, hashed once
    target = S.target_from_fp(stamp_cost)
    urandom, from_bytes = os.urandom, int.from_bytes
    rounds, stamp = 0, None
    while not jobs.get(message_id):
        candidate = urandom(size)
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


def _in_front_of(name):
    original = _originals.setdefault(name, getattr(S, name))

    def job(stamp_cost, workblock, message_id, size, mode=S.MODE_STAMP):
        if mode == S.MODE_STAMP and workblock and len(workblock) >= BIG_WORKBLOCK:
            return fast_job(stamp_cost, workblock, message_id, size)
        return original(stamp_cost, workblock, message_id, size, mode)
    job.firefly_fast = True
    return job


def install():
    for name in ("job_linux", "job_linux_managed", "job_simple"):
        if not getattr(getattr(S, name), "firefly_fast", False):
            setattr(S, name, _in_front_of(name))
