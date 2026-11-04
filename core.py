"""Persistent event ledger. All amounts are integer gold seeds (100 = one battery)."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from config import Settings

BV = re.compile(r"(?<![A-Za-z0-9])BV[1-9A-HJ-NP-Za-km-z]{10}(?![A-Za-z0-9])")


def coins(value, factor=1):
    return int(Decimal(str(value or 0)) * factor)


def batteries(value):
    return format(Decimal(value) / 100, "f").rstrip("0").rstrip(".") if value % 100 else str(value // 100)


def language(value="system", system=None):
    if value in ("zh", "ja"):
        return value
    return "ja" if (system or "").lower().startswith("ja") else "zh"


def grouped_sc(rows, enabled=False):
    """Preserve timestamp order within each group; None is a non-event divider."""
    rows = sorted(rows, key=lambda row: (row['ts'], row['id']))
    if not enabled:
        return rows
    pending = [row for row in rows if not row['sunk'] or row['mark'] != 'circle']
    processed = [row for row in rows if row['sunk'] and row['mark'] == 'circle']
    return pending + ([None] if pending and processed else []) + processed


def normalize(source, kind, payload, room):
    """Normalize dataclass dictionaries from blivedm; no nickname-based user merging."""
    p = payload
    official = source in ("blivechat", "open")
    nested = p.get("user_info", {}) if kind == "guard" and official else p
    uid = nested.get("open_id") if official else p.get("uid")
    namespace = "open" if official else "uid"
    name = nested.get("uname") or p.get("uname") or p.get("username") or "?"
    ts = int(p.get("timestamp") or p.get("start_time") or time.time())
    msg_id = p.get("msg_id") or p.get("tid") or p.get("rnd")
    note = ""
    if kind == "sc":
        msg_id = p.get("message_id") if official else p.get("id")
        amount = coins(p.get("rmb") if official else p.get("price"), 1000)
        text = p.get("message", "")
    elif kind == "gift":
        if official:
            amount = coins(p.get("r_price", p.get("price", 0))) * int(p.get("gift_num", 1)) if p.get("paid") else 0
            if p.get("blind_gift", {}).get("status"):
                note = "blind_value"
        else:
            amount = coins(p.get("total_coin")) if p.get("coin_type") == "gold" else 0
        text = f"{p.get('gift_name', '')} × {p.get('gift_num', p.get('num', 1))}"
    elif kind == "guard":
        if not official and p.get("source") == 2:
            return None  # Duplicate courtesy announcement, not another purchase.
        qty = int(p.get("guard_num", p.get("num", 1)))
        unit = p.get("guard_unit", p.get("unit", "月"))
        # Non-month packages carry their duration in unit, not in qty.
        amount = coins(p.get("price")) * (qty if unit in ("月", "个月", "") else 1)
        text = f"Guard {p.get('guard_level', 0)} × {qty} {unit}"
        # GUARD_BUY and USER_TOAST_MSG_V2 describe the same transaction.
        msg_id = f"{uid}:{ts}:{p.get('guard_level')}:{amount}"
    else:
        raise ValueError(kind)
    if not msg_id:
        # Retain deterministic fallback for replay deduplication; mark the weaker identity.
        msg_id = hashlib.sha256(json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        note = note or "fallback_id"
    event_id = f"{room}:{source}:{kind}:{msg_id}"
    user = f"{namespace}:{uid}" if uid and str(uid) != "0" else f"unknown:{event_id}"
    return dict(id=event_id, external_id=str(msg_id), room=str(room), source=source,
                kind=kind, user=user, name=name, ts=ts, amount=max(0, amount),
                text=text, note=note)


class Ledger:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "scdesk.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(
              id TEXT PRIMARY KEY, room TEXT, source TEXT, started INTEGER,
              start_known INTEGER DEFAULT 0, ended INTEGER);
            CREATE TABLE IF NOT EXISTS events(
              id TEXT PRIMARY KEY, external_id TEXT, session TEXT, room TEXT, source TEXT,
              kind TEXT, user TEXT, name TEXT, ts INTEGER, amount INTEGER, text TEXT,
              note TEXT, mark TEXT DEFAULT '', automatic INTEGER DEFAULT 0,
              deleted INTEGER DEFAULT 0, batch TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS archives(
              id TEXT PRIMARY KEY, session TEXT, created INTEGER, reason TEXT, restored INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS tombstones(
              room TEXT, source TEXT, external_id TEXT, PRIMARY KEY(room,source,external_id));
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE INDEX IF NOT EXISTS events_scope_time ON events(room,source,ts);
            CREATE INDEX IF NOT EXISTS events_session_kind ON events(session,kind);
        """)
        self.session = None
        if 'sunk' not in [r['name'] for r in self.db.execute('PRAGMA table_info(events)')]:
            self.db.execute('ALTER TABLE events ADD COLUMN sunk INTEGER NOT NULL DEFAULT 0')
            self.db.commit()
        legacy = {r['key']: json.loads(r['value']) for r in self.db.execute('SELECT * FROM settings')}
        self.config = Settings(self.directory / 'config.json', legacy)

    def get(self, key, default=None):
        return self.config.data.get(key, default)

    def set(self, key, value):
        self.save_settings({key: value})

    def save_settings(self, values):
        self.config.update(values)
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", [(key, json.dumps(value)) for key, value in values.items()])

    def attach(self, room, source, started=None, fresh=False):
        previous_row = None
        row = self.db.execute("SELECT * FROM sessions WHERE room=? AND source=? AND ended IS NULL ORDER BY started DESC LIMIT 1",
                              (str(room), source)).fetchone()
        if row and started:
            earliest = self.db.execute('SELECT MIN(ts) FROM events WHERE session=?', (row['id'],)).fetchone()[0]
            different = (row['start_known'] and row['started'] != started) or (not row['start_known'] and earliest and earliest < started)
            fresh = fresh or different
        if row and fresh:
            previous_row = row
            previous = self.session
            self.session = row['id']
            self.export()
            self.session = previous
            with self.db:
                self.db.execute('UPDATE sessions SET ended=? WHERE id=?', (int(started or time.time()), row['id']))
            row = None
        if row:
            self.session = row["id"]
            if started and not row['start_known']:
                with self.db:
                    self.db.execute('UPDATE sessions SET started=?,start_known=1 WHERE id=?', (int(started), self.session))
        else:
            self.session = uuid.uuid4().hex
            with self.db:
                self.db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,NULL)",
                                (self.session, str(room), source, int(started or time.time()), int(bool(started))))
            if previous_row and started:
                with self.db:
                    self.db.execute('UPDATE events SET session=? WHERE session=? AND ts>=?',
                                    (self.session, previous_row['id'], started))
                new_id = self.session
                self.session = previous_row['id']
                self.export()
                self.session = new_id
        return self.session

    def end(self):
        if self.session:
            with self.db:
                self.db.execute('UPDATE sessions SET ended=? WHERE id=? AND ended IS NULL', (int(time.time()), self.session))

    def current(self):
        return self.db.execute("SELECT * FROM sessions WHERE id=?", (self.session,)).fetchone()

    def ingest(self, event, video=False):
        if event is None:
            return False
        if not self.session:
            self.attach(event["room"], event["source"])
        current = self.current()
        if (current["room"], current["source"]) != (event["room"], event["source"]):
            raise ValueError("Event scope does not match the active session")
        if current['start_known'] and event['ts'] < current['started']:
            return False  # Previous broadcast replay must never enter the new list/rank.
        auto = event["kind"] == "sc" and video and not BV.search(event["text"])
        deleted = bool(self.db.execute("SELECT 1 FROM tombstones WHERE room=? AND source=? AND external_id=?",
                                      (event["room"], event["source"], event["external_id"])).fetchone())
        with self.db:
            result = self.db.execute("""INSERT OR IGNORE INTO events
              (id,external_id,session,room,source,kind,user,name,ts,amount,text,note,mark,automatic,deleted)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              tuple(event[k] for k in ("id", "external_id")) + (self.session,) +
              tuple(event[k] for k in ("room", "source", "kind", "user", "name", "ts", "amount", "text", "note")) +
              ("square" if auto else "", int(auto), int(deleted)))
        return result.rowcount > 0

    def sc_rows(self, historical=False):
        return self.db.execute("SELECT * FROM events WHERE session=? AND kind='sc'" +
                               ("" if historical else " AND batch=''") + " ORDER BY ts,id", (self.session,)).fetchall()

    def pending(self):
        return sum(r["mark"] != "circle" and not r["deleted"] for r in self.sc_rows())

    def mark(self, event_id, mark):
        if mark not in ("", "circle", "triangle", "square"):
            raise ValueError(mark)
        with self.db:
            self.db.execute("UPDATE events SET mark=?,automatic=0,sunk=CASE WHEN ?='circle' THEN sunk ELSE 0 END WHERE id=? AND session=?",
                            (mark, mark, event_id, self.session))

    def sink_processed(self):
        with self.db:
            self.db.execute("UPDATE events SET sunk=1 WHERE session=? AND kind='sc' AND batch='' AND mark='circle'", (self.session,))

    def classify_video_sc(self):
        """Classify current unmarked SC without overwriting manual decisions."""
        ids = [row['id'] for row in self.sc_rows() if not row['mark'] and not row['deleted'] and not BV.search(row['text'])]
        with self.db:
            self.db.executemany("UPDATE events SET mark='square',automatic=1,sunk=0 WHERE id=? AND session=?", [(mid, self.session) for mid in ids])
        return len(ids)

    def confirm_squares(self):
        with self.db:
            return self.db.execute("UPDATE events SET mark='circle',automatic=0 WHERE session=? AND kind='sc' AND batch='' AND deleted=0 AND mark='square'", (self.session,)).rowcount

    def delete_sc(self, room, source, ids):
        with self.db:
            for mid in ids:
                self.db.execute("INSERT OR IGNORE INTO tombstones VALUES (?,?,?)", (str(room), source, str(mid)))
                self.db.execute("UPDATE events SET deleted=1 WHERE room=? AND source=? AND kind='sc' AND external_id=?",
                                (str(room), source, str(mid)))

    def archive(self, reason="manual", end=False):
        if not self.session:
            return
        aid = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO archives VALUES (?,?,?,?,0)", (aid, self.session, int(time.time()), reason))
            self.db.execute("UPDATE events SET batch=? WHERE session=? AND kind='sc' AND batch=''", (aid, self.session))
            if end:
                self.db.execute("UPDATE sessions SET ended=? WHERE id=?", (int(time.time()), self.session))
        return aid

    def restore(self, archive_id):
        row = self.db.execute("SELECT * FROM archives WHERE id=?", (archive_id,)).fetchone()
        if row is None or row["session"] != self.session:
            raise ValueError("Select the archive's session before restoring")
        with self.db:
            self.db.execute("UPDATE events SET batch='' WHERE session=? AND batch=?", (self.session, archive_id))
            self.db.execute("UPDATE archives SET restored=1 WHERE id=?", (archive_id,))

    def rankings(self, room, source, daily=True, now=None):
        now = now or datetime.now()
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Compute the next LOCAL midnight (DST-aware via timestamp), not a fixed 86400 seconds.
        from datetime import timedelta
        args = [str(room), source]
        where = "room=? AND source=?"
        if daily:
            where += " AND ts>=? AND ts<?"
            args += [int(day.timestamp()), int((day + timedelta(days=1)).timestamp())]
        else:
            where += " AND session=?"
            args.append(self.session)
        return self.db.execute(f"""SELECT user,MAX(name) AS name,SUM(amount) AS total,COUNT(*) AS count,
          SUM(CASE WHEN kind='sc' THEN amount ELSE 0 END) AS sc,
          SUM(CASE WHEN kind='gift' THEN amount ELSE 0 END) AS gift,
          SUM(CASE WHEN kind='guard' THEN amount ELSE 0 END) AS guard
          FROM events WHERE {where} GROUP BY user ORDER BY total DESC,user""", args).fetchall()

    @property
    def export_directory(self):
        return self.directory / 'exports'

    def export(self):
        current = self.current()
        if current is None:
            return None
        folder = self.export_directory
        folder.mkdir(parents=True,exist_ok=True)
        date = datetime.fromtimestamp(current["started"]).strftime("%Y-%m-%d_%H-%M-%S")
        path = folder / f"{date}_{current['room']}_{current['source']}_{self.session[:6]}_SC.txt"
        lines = ["SCMaru / SC archive", f"Room: {current['room']} | Source: {current['source']}",
                 f"Start: {date} ({'broadcast' if current['start_known'] else 'capture start; broadcast start unknown'})",
                 f"Timezone: {datetime.now().astimezone().tzname()}", ""]
        for r in self.sc_rows(historical=True):
            stamp = datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S")
            symbol = {"circle": "○", "triangle": "△", "square": "□", "": "未处理 / 未確認"}[r["mark"]]
            state = " [AUTO]" if r["automatic"] else ""
            state += " [REMOVED BY PLATFORM]" if r["deleted"] else ""
            state += " [ARCHIVED]" if r["batch"] else ""
            lines += [f"[{stamp}] {symbol}{state} | {r['name']} | {batteries(r['amount'])} 电池 / 電池",
                      f"ID: {r['external_id']} | User: {r['user']}", r["text"], ""]
        temp = path.with_suffix(".tmp")
        temp.write_text("\n".join(lines), encoding="utf-8-sig")
        temp.replace(path)
        return path
