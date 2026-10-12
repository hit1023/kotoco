"""置換ルールと履歴の保存 (SQLite) と、置換の適用。"""
import os
import re
import sqlite3
import threading
import time

DB_PATH = os.environ.get("KOTOCO_DB", "/data/kotoco.db")
_lock = threading.Lock()
_compiled = None


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS replacements (src TEXT PRIMARY KEY, dst TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS pronunciations (word TEXT NOT NULL, lang TEXT NOT NULL, ps TEXT NOT NULL, PRIMARY KEY(word, lang))")
        c.execute(
            "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, applied TEXT,"
            " lang TEXT, voice TEXT, speed REAL, format TEXT, ms INTEGER, created_at REAL)"
        )


# ---- 置換ルール ----
def list_rules():
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT src, dst FROM replacements ORDER BY src")]


def upsert_rules(pairs):
    global _compiled
    with _lock, _conn() as c:
        c.executemany(
            "INSERT INTO replacements(src, dst) VALUES(?, ?) ON CONFLICT(src) DO UPDATE SET dst=excluded.dst",
            [(s, d) for s, d in pairs if s],
        )
    _compiled = None


def delete_rule(src):
    global _compiled
    with _lock, _conn() as c:
        n = c.execute("DELETE FROM replacements WHERE src=?", (src,)).rowcount
    _compiled = None
    return n


def _pattern():
    global _compiled
    if _compiled is None:
        rules = {r["src"].lower(): r["dst"] for r in list_rules()}
        keys = sorted(rules, key=len, reverse=True)  # 長い語を優先
        pat = re.compile("|".join(re.escape(k) for k in keys), re.I) if keys else None
        _compiled = (pat, rules)
    return _compiled


def apply_rules(text):
    """1パスで置換する(置換結果が再度置換されない)。大文字小文字は区別しない。"""
    pat, rules = _pattern()
    if not pat:
        return text
    return pat.sub(lambda m: rules.get(m.group(0).lower(), m.group(0)), text)


# ---- 履歴 ----
def add_history(text, applied, lang, voice, speed, fmt, ms):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO history(text, applied, lang, voice, speed, format, ms, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (text, applied, lang, voice, speed, fmt, ms, time.time()),
        )
        c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 1000)")


def list_history(limit, offset):
    with _lock, _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        rows = [dict(r) for r in c.execute("SELECT * FROM history ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))]
    return total, rows


def clear_history():
    with _lock, _conn() as c:
        c.execute("DELETE FROM history")


# ---- 発音辞書 (単語 -> 音素列) ----
_pron = {}


def list_prons(lang=None):
    with _lock, _conn() as c:
        q, a = "SELECT word, lang, ps FROM pronunciations", ()
        if lang:
            q, a = q + " WHERE lang=?", (lang,)
        return [dict(r) for r in c.execute(q + " ORDER BY word", a)]


def upsert_pron(word, lang, ps):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO pronunciations(word, lang, ps) VALUES(?,?,?) ON CONFLICT(word, lang) DO UPDATE SET ps=excluded.ps",
            (word, lang, ps),
        )
    _pron.clear()


def delete_pron(word, lang):
    with _lock, _conn() as c:
        n = c.execute("DELETE FROM pronunciations WHERE word=? AND lang=?", (word, lang)).rowcount
    _pron.clear()
    return n


def pron_pattern(lang):
    """(正規表現, {小文字の単語: 音素列})。辞書が空なら (None, {})。"""
    if lang not in _pron:
        m = {r["word"].lower(): r["ps"] for r in list_prons(lang)}
        keys = sorted(m, key=len, reverse=True)
        _pron[lang] = (re.compile("|".join(re.escape(k) for k in keys), re.I) if keys else None, m)
    return _pron[lang]
