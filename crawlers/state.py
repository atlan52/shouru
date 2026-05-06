"""Per-platform checkpoint state.

Each crawler keeps a `data/state/{platform}.json` with:
  - seen_ids: list[str]   IDs ever attempted (success or skip)
  - queue: list[str]      pending items for BFS-style crawlers
  - cursor: dict          per-keyword pagination cursor (e.g. {kw: page_num})
  - kw_done: list[str]    keywords fully exhausted
  - extra: dict           free-form per-crawler scratch
  - updated_at: iso str
"""
import json
import time
from datetime import datetime
from config import STATE_DIR


class State:
    def __init__(self, platform: str):
        self.platform = platform
        self.path = STATE_DIR / f"{platform}.json"
        self.data = {
            "seen_ids": [],
            "queue": [],
            "cursor": {},
            "kw_done": [],
            "extra": {},
            "updated_at": "",
        }
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception as e:
                print(f"[state] {platform} load err: {e} — starting fresh")
        self._seen_set = set(self.data["seen_ids"])
        self._kw_done_set = set(self.data["kw_done"])
        self._queue_set = set(self.data["queue"])
        self._dirty = False
        self._last_save = time.time()

    @property
    def seen(self):
        return self._seen_set

    def is_seen(self, id_: str) -> bool:
        return id_ in self._seen_set

    def mark_seen(self, *ids):
        for i in ids:
            if i and i not in self._seen_set:
                self._seen_set.add(i)
                self.data["seen_ids"].append(i)
                self._dirty = True

    @property
    def queue(self):
        return self.data["queue"]

    def queue_push(self, *ids):
        for i in ids:
            if i and i not in self._seen_set and i not in self._queue_set:
                self.data["queue"].append(i)
                self._queue_set.add(i)
                self._dirty = True

    def queue_pop(self):
        if self.data["queue"]:
            self._dirty = True
            v = self.data["queue"].pop(0)
            self._queue_set.discard(v)
            return v
        return None

    def queue_len(self):
        return len(self.data["queue"])

    def get_cursor(self, kw: str, default=0):
        return self.data["cursor"].get(kw, default)

    def set_cursor(self, kw: str, value):
        self.data["cursor"][kw] = value
        self._dirty = True

    def is_kw_done(self, kw: str) -> bool:
        return kw in self._kw_done_set

    def mark_kw_done(self, kw: str):
        if kw not in self._kw_done_set:
            self._kw_done_set.add(kw)
            self.data["kw_done"].append(kw)
            self._dirty = True

    def get(self, k, default=None):
        return self.data["extra"].get(k, default)

    def set(self, k, v):
        self.data["extra"][k] = v
        self._dirty = True

    def save(self, force=False):
        if not (self._dirty or force):
            return
        self.data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = False
        self._last_save = time.time()

    def maybe_save(self, every: float = 10.0):
        if self._dirty and (time.time() - self._last_save) >= every:
            self.save()

    def reset(self):
        self.path.unlink(missing_ok=True)
        self.__init__(self.platform)
