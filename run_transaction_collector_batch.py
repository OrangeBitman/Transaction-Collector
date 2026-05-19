#!/usr/bin/env python3
"""
Batch-Runner für transaction_collector.py

Aufruf pro TX-ID:
python3 transaction_collector.py--csv-out <N_pad>_<TXID[:15]>.csv TX-ID

Nutzung:
    python3 run_transaction_collector_batch.py transactions.txt
Optionen:
    --digits 3         -> führende Nullen mit fester Breite (z.B. 001_…)
    --auto-digits      -> Breite automatisch aus Anzahl TX-IDs
    --overwrite        -> vorhandene CSV-Dateien überschreiben
    --pause 0.2        -> Pause zwischen Aufrufen (Sek.)
    --script PATH      -> Pfad zu transaction_collector.py
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from time import sleep

TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")

def iter_txids(path: Path):
    """Liest TX-IDs, validiert, de-dupliziert (Reihenfolge bleibt erhalten)."""
    seen = set()
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            txid = raw.strip()
            if not txid or txid.startswith("#"):
                continue
            if not TXID_RE.fullmatch(txid):
                print(f"[WARN] Zeile {lineno}: Ungültige TX-ID übersprungen: {txid}", file=sys.stderr)
                continue
            if txid in seen:
                print(f"[INFO] Zeile {lineno}: Duplikat übersprungen: {txid}", file=sys.stderr)
                continue
            seen.add(txid)
            yield txid

def main():
    p = argparse.ArgumentParser(description="Batch-Aufruf für transaction_collector.py")
    p.add_argument("txlist", help="Pfad zur Textdatei mit TX-IDs (eine pro Zeile).")
    p.add_argument("--script", default="transaction_collector.py",
                   help="Pfad zu transaction_collector.py (Default: im aktuellen Verzeichnis).")

    g = p.add_mutually_exclusive_group()
    g.add_argument("--digits", type=int,
                   help="Anzahl Stellen für führende Nullen (z.B. 3 -> 001_...).")
    g.add_argument("--auto-digits", action="store_true",
                   help="Stellenzahl automatisch anhand der Anzahl gültiger TX-IDs.")
    p.add_argument("--pause", type=float, default=0.0, help="Pause in Sekunden zwischen Aufrufen.")

    args = p.parse_args()

    txfile = Path(args.txlist)
    if not txfile.exists():
        print(f"[FEHLER] Datei nicht gefunden: {txfile}", file=sys.stderr)
        sys.exit(1)

    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[FEHLER] Skript nicht gefunden: {script_path}", file=sys.stderr)
        sys.exit(1)

    txids = list(iter_txids(txfile))
    if not txids:
        print("[INFO] Keine gültigen TX-IDs gefunden. Nichts zu tun.")
        return

    # Breite für führende Nullen bestimmen
    if args.digits is not None:
        if args.digits <= 0:
            print("[FEHLER] --digits muss > 0 sein.", file=sys.stderr)
            sys.exit(1)
        width = args.digits
    elif args.auto_digits:
        width = max(1, len(str(len(txids))))
    else:
        width = 0  # keine führenden Nullen

    any_errors = False
    for idx, txid in enumerate(txids, start=1):
        idx_str = str(idx).zfill(width) if width else str(idx)
        out_csv = Path(f"resources/{idx_str}_{txid[:15]}.csv")

        if out_csv.exists() and not args.overwrite:
            print(f"[INFO] Überspringe {txid} (Ausgabe existiert bereits: {out_csv})")
            continue

        cmd = [
            sys.executable, str(script_path),
            "--csv-out", str(out_csv),
            txid,
        ]

        print(f"[RUN] {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            any_errors = True
            print(f"[FEHLER] Aufruf für {txid} schlug fehl (Exit {e.returncode}).", file=sys.stderr)

        if args.pause > 0:
            sleep(args.pause)

    if any_errors:
        sys.exit(2)

if __name__ == "__main__":
    main()