"""SQLite snapshots and conservative, persistent USD reservations (Decimal, not float)."""
from __future__ import annotations

import json
import sqlite3
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path


class BudgetExceeded(Exception):
    pass


def money(value) -> Decimal:
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("예산은 유효한 달러 금액이어야 합니다.") from None
    if not n.is_finite() or n < 0:
        raise ValueError("예산은 0 이상의 유한한 금액이어야 합니다.")
    return n


class Store:
    def __init__(self, path: Path, total: str = "8.00"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.total = money(total)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, updated TEXT, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS charges (
          id TEXT PRIMARY KEY, game_id TEXT NOT NULL, status TEXT NOT NULL,
          amount TEXT NOT NULL, model TEXT NOT NULL, result TEXT,
          input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
          cached_tokens INTEGER DEFAULT 0
        );
        """)

    def close(self):
        self.db.close()

    def save(self, game: dict):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO games VALUES (?, datetime('now'), ?)",
                            (game["id"], json.dumps(game, ensure_ascii=False)))

    def load(self, gid: str | None = None) -> dict | None:
        with self.lock:
            row = (self.db.execute("SELECT state FROM games WHERE id=?", (gid,)).fetchone() if gid
                   else self.db.execute("SELECT state FROM games ORDER BY rowid DESC LIMIT 1").fetchone())
            return json.loads(row[0]) if row else None

    def history(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT state FROM games ORDER BY rowid DESC LIMIT 30").fetchall()
        return [{k: g[k] for k in ("id", "created", "day", "mode", "winner", "turn")}
                for g in (json.loads(r[0]) for r in rows)]

    def summary(self, gid: str | None = None) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT game_id, status, amount, input_tokens, output_tokens FROM charges").fetchall()
        total = sum((Decimal(r[2]) for r in rows), Decimal(0))
        own = [r for r in rows if r[0] == gid]
        uncertain = sum((Decimal(r[2]) for r in rows if r[1] in ("pending", "uncertain")), Decimal(0))
        return dict(total_usd=str(total), limit_usd=str(self.total),
                    remaining_usd=str(max(Decimal(0), self.total - total)),
                    game_usd=str(sum((Decimal(r[2]) for r in own), Decimal(0))),
                    reserved_usd=str(uncertain), calls=sum(r[1] != "rejected" for r in own),
                    input_tokens=sum(r[3] for r in own), output_tokens=sum(r[4] for r in own))

    def reserve(self, tid: str, gid: str, model: str, amount: Decimal, cap: str) -> dict | None:
        """An existing receipt prevents replaying a paid request after a crash."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                existing = self.db.execute("SELECT status,result FROM charges WHERE id=?", (tid,)).fetchone()
                if existing and existing[0] != "rejected":
                    self.db.execute("COMMIT")
                    return json.loads(existing[1]) if existing[1] else {
                        "fallback": True, "warning": "중단된 요청을 다시 과금하지 않고 안전한 기본 행동으로 넘깁니다."}
                rows = self.db.execute("SELECT game_id,amount FROM charges").fetchall()
                total = sum((Decimal(r[1]) for r in rows), Decimal(0))
                own = sum((Decimal(r[1]) for r in rows if r[0] == gid), Decimal(0))
                if total + amount > self.total or own + amount > money(cap):
                    raise BudgetExceeded("예산 보호: 다음 요청의 최대 추정 비용을 확보할 수 없어 일시정지했습니다.")
                self.db.execute("INSERT OR REPLACE INTO charges (id,game_id,status,amount,model) VALUES (?,?,?,?,?)",
                                (tid, gid, "pending", str(amount), model))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return None

    def settle(self, tid: str, result: dict, amount: Decimal | None = None,
               usage: tuple[int, int, int] = (0, 0, 0), rejected: bool = False):
        with self.lock:
            if rejected:
                self.db.execute("UPDATE charges SET status='rejected',amount='0',result=NULL WHERE id=?", (tid,))
            elif amount is None:
                self.db.execute("UPDATE charges SET status='uncertain',result=? WHERE id=?", (json.dumps(result), tid))
            else:
                self.db.execute("UPDATE charges SET status='settled',amount=?,result=?,input_tokens=?,output_tokens=?,cached_tokens=? WHERE id=?",
                                (str(amount), json.dumps(result), *usage, tid))
