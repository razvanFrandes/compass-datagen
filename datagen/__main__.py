"""Generate the dataset.

    python -m datagen --preview        a small sample: about 10 reservations per hotel, with their details
    python -m datagen                  the full window
"""
import argparse
import time
from datetime import date, timedelta

import numpy as np

from . import bookings, config as C, finance, market, ops, write
from .world import World


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preview", action="store_true", help="write a small sample instead of everything")
    p.add_argument("--start", type=date.fromisoformat, default=None)
    p.add_argument("--end", type=date.fromisoformat, default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    if args.preview:
        start = args.start or C.BUSINESS_DATE - timedelta(days=75)
        end = args.end or C.BUSINESS_DATE + timedelta(days=60)
    else:
        start = args.start or date(2025, 1, 1)
        end = args.end or date(2027, 5, 31)
    out = args.out or ("out/preview" if args.preview else "out/full")

    t = time.time()
    seeds = np.random.SeedSequence(C.SEED).spawn(5)  # one stream per mechanism
    w = World(start, end, np.random.default_rng(seeds[0]))
    market_tables, comp_ref = market.build(w, np.random.default_rng(seeds[1]))
    core, web_rows = bookings.simulate(w, comp_ref, np.random.default_rng(seeds[2]))
    print(f"bookings simulated in {time.time() - t:.1f}s: {len(core['reservations']):,} reservations")
    op = ops.build(w, comp_ref, core, web_rows, np.random.default_rng(seeds[3]))
    fin = finance.build(w, core, op, np.random.default_rng(seeds[4]))
    tables = {**write.reference(w), **market_tables, **core, **op, **fin}
    counts = write.save(tables, out, preview=args.preview)
    print(f"done in {time.time() - t:.1f}s -> {out}")
    for name, k in counts.items():
        print(f"  {name:24s} {k:>10,}")


if __name__ == "__main__":
    main()
