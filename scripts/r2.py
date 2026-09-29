"""
Cloudflare R2 helpers: upload the raw archive / Parquet files, and verify them.

  python scripts/r2.py upload data/raw_archive raw_archive   # local dir -> bucket prefix
  python scripts/r2.py upload data/parquet parquet
  python scripts/r2.py verify                                # R2 vs local archive

upload skips files already in R2 with the same size, so it is safe to re-run.
verify checks every raw archive file is in R2 with the same size, and that
the Parquet rows per day in R2 match each day's manifest total.

Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY.
"""

import gzip
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config

BUCKET = "pf-pipeline"
ARCHIVE = Path("data/raw_archive")
MIN_ROWS = 20_000  # same threshold as export_parquet.py: partial days are not exported


def client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"),
    )


def remote_sizes(s3, prefix):
    sizes = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            sizes[obj["Key"]] = obj["Size"]
    return sizes


def upload(local_dir, prefix):
    s3, root = client(), Path(local_dir)
    have = remote_sizes(s3, prefix)
    sent = skipped = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        key = f"{prefix}/{path.relative_to(root).as_posix()}"
        if have.get(key) == path.stat().st_size:
            skipped += 1
            continue
        s3.upload_file(str(path), BUCKET, key)
        sent += 1
    print(f"{local_dir} -> r2://{BUCKET}/{prefix}: {sent} uploaded, {skipped} already there")


def verify():
    import duckdb

    s3, ok = client(), True

    have = remote_sizes(s3, "raw_archive")
    local = {f"raw_archive/{p.relative_to(ARCHIVE).as_posix()}": p.stat().st_size
             for p in ARCHIVE.rglob("*") if p.is_file()}
    bad = [k for k, size in local.items() if have.get(k) != size]
    print(f"raw archive: {len(local)} local files, {len(have)} in R2, {len(bad)} missing or different")
    ok &= not bad

    con = duckdb.connect()
    con.execute(f"""CREATE SECRET (TYPE r2, KEY_ID '{os.environ["R2_ACCESS_KEY_ID"]}',
                    SECRET '{os.environ["R2_SECRET_ACCESS_KEY"]}', ACCOUNT_ID '{os.environ["R2_ACCOUNT_ID"]}')""")
    rows = dict(con.execute(f"""
        SELECT strftime(snapshot_date, '%Y-%m-%d'), count(*)
        FROM read_parquet('r2://{BUCKET}/parquet/*/*.parquet', union_by_name=true)
        GROUP BY 1""").fetchall())
    for day in sorted(p.name for p in ARCHIVE.iterdir() if p.is_dir()):
        manifest = ARCHIVE / day / "manifest.json.gz"
        expected = json.load(gzip.open(manifest))["total"] if manifest.exists() else None
        got = rows.get(day, 0)
        if expected is not None and expected < MIN_ROWS:
            continue  # partial scrape, not exported
        if got != expected:
            print(f"  MISMATCH {day}: parquet {got} rows, manifest {expected}")
            ok = False
    print(f"parquet: {len(rows)} days in R2, {sum(rows.values())} rows")
    print("VERIFY OK" if ok else "VERIFY FAILED")
    return ok


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["upload"] and len(sys.argv) == 4:
        upload(sys.argv[2], sys.argv[3])
    elif cmd == ["verify"]:
        sys.exit(0 if verify() else 1)
    else:
        sys.exit(__doc__)
