from __future__ import annotations

import json
import time
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import Host


class LibvirtCacheStore:
    def __init__(self, ttl_s: int) -> None:
        self.ttl_s = ttl_s

    def ensure_table(self, db: Session) -> None:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS host_libvirt_cache (
                host_id VARCHAR(128) PRIMARY KEY,
                vms_json TEXT NOT NULL,
                networks_json TEXT NOT NULL,
                images_json TEXT NOT NULL,
                pools_json TEXT NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                last_error TEXT,
                last_success_at DOUBLE PRECISION
            )
        """))
        db.execute(text("ALTER TABLE host_libvirt_cache ADD COLUMN IF NOT EXISTS last_error TEXT"))
        db.execute(text("ALTER TABLE host_libvirt_cache ADD COLUMN IF NOT EXISTS last_success_at DOUBLE PRECISION"))
        db.commit()

    def refresh(self, db: Session, host: Host, fetcher: Callable[[Host, str], Any]) -> dict[str, Any]:
        vms = fetcher(host, "list_vms")
        networks = fetcher(host, "list_networks")
        images = fetcher(host, "list_images")
        pools = fetcher(host, "list_storage_pools")
        now = time.time()
        self.ensure_table(db)
        db.execute(
            text("""
                INSERT INTO host_libvirt_cache(host_id, vms_json, networks_json, images_json, pools_json, updated_at, last_error, last_success_at)
                VALUES (:host_id, :vms_json, :networks_json, :images_json, :pools_json, :updated_at, NULL, :updated_at)
                ON CONFLICT(host_id) DO UPDATE SET
                vms_json=excluded.vms_json,
                networks_json=excluded.networks_json,
                images_json=excluded.images_json,
                pools_json=excluded.pools_json,
                updated_at=excluded.updated_at,
                last_error=NULL,
                last_success_at=excluded.updated_at
            """),
            {
                "host_id": host.host_id,
                "vms_json": json.dumps(vms),
                "networks_json": json.dumps(networks),
                "images_json": json.dumps(images),
                "pools_json": json.dumps(pools),
                "updated_at": now,
            },
        )
        db.commit()
        return {"vms": vms, "networks": networks, "images": images, "pools": pools, "updated_at": now, "cache": "miss"}

    def get(self, db: Session, host: Host, fetcher: Callable[[Host, str], Any], *, force_refresh: bool = False) -> dict[str, Any]:
        self.ensure_table(db)
        row = db.execute(
            text("SELECT vms_json, networks_json, images_json, pools_json, updated_at, last_error, last_success_at FROM host_libvirt_cache WHERE host_id=:host_id"),
            {"host_id": host.host_id},
        ).first()

        if not force_refresh and row and (time.time() - float(row.updated_at) <= self.ttl_s):
            return {
                "vms": json.loads(row.vms_json),
                "networks": json.loads(row.networks_json),
                "images": json.loads(row.images_json),
                "pools": json.loads(row.pools_json),
                "updated_at": float(row.updated_at),
                "last_error": row.last_error,
                "last_success_at": float(row.last_success_at) if row.last_success_at else None,
                "cache": "hit",
            }

        try:
            return self.refresh(db, host, fetcher)
        except HTTPException as exc:
            if row:
                db.execute(
                    text("UPDATE host_libvirt_cache SET last_error=:last_error WHERE host_id=:host_id"),
                    {"host_id": host.host_id, "last_error": str(exc.detail)},
                )
                db.commit()
                return {
                    "vms": json.loads(row.vms_json),
                    "networks": json.loads(row.networks_json),
                    "images": json.loads(row.images_json),
                    "pools": json.loads(row.pools_json),
                    "updated_at": float(row.updated_at),
                    "last_error": str(exc.detail),
                    "last_success_at": float(row.last_success_at) if row.last_success_at else None,
                    "cache": "stale",
                }
            raise
