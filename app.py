"""PlaceMate - College Placement Management System.

Stdlib only: Python 3 + SQLite.

Run:   python app.py
Open:  http://localhost:8000
Needs placement.sql in the same folder (creates placement.db on first run).
"""
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "placement.db")
SCHEMA = os.path.join(HERE, "placement.sql")
PORT = 8000

# table -> (primary key, editable columns)
TABLES = {
    "student":     ("student_id", ["name", "email", "branch", "cgpa", "backlogs"]),
    "company":     ("company_id", ["name", "sector", "location"]),
    "drive":       ("drive_id",   ["company_id", "role", "package_lpa", "min_cgpa", "drive_date"]),
    "application": ("app_id",     ["student_id", "drive_id", "status"]),
    "offer":       ("offer_id",   ["app_id", "ctc_lpa", "joining_date"]),
}

# name -> (SQL, required query-string parameters)
QUERIES = {
    "eligible": (
        "SELECT d.* FROM drive d, student s "
        "WHERE s.student_id = ? AND s.cgpa >= d.min_cgpa",
        ["student_id"],
    ),
    "view_eligible": (
        "SELECT drive_id, role, min_cgpa FROM eligible_drives WHERE student_id = ?",
        ["student_id"],
    ),
    "packages": (
        "SELECT MAX(ctc_lpa) AS highest, ROUND(AVG(ctc_lpa), 2) AS average FROM offer",
        [],
    ),
    "no_applications": (
        "SELECT name FROM student "
        "WHERE student_id NOT IN (SELECT student_id FROM application)",
        [],
    ),
    "branch_placed": (
        "SELECT s.branch, COUNT(DISTINCT s.student_id) AS placed "
        "FROM student s JOIN application a USING (student_id) "
        "WHERE a.status = 'Selected' GROUP BY s.branch",
        [],
    ),
}


class ApiError(Exception):
    """An error that should be reported to the client with a status code."""

    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_db():
    """Create placement.db from placement.sql on first run."""
    if os.path.exists(DB):
        return
    if not os.path.exists(SCHEMA):
        raise SystemExit("placement.sql not found next to app.py")
    c = sqlite3.connect(DB)
    try:
        with open(SCHEMA, encoding="utf-8") as f:
            c.executescript(f.read())
        c.commit()
    except Exception:
        c.close()
        os.remove(DB)  # don't leave a half-built database behind
        raise
    c.close()


def fetch(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args).fetchall()]


class Handler(BaseHTTPRequestHandler):
    # ---------- helpers ----------
    def reply(self, code, body, ctype="application/json"):
        if isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) or b"{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError("request body is not valid JSON")
        if not isinstance(data, dict):
            raise ApiError("request body must be a JSON object")
        return data

    # ---------- API ----------
    def handle_api(self, method):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]  # ["api", table, id?]
        c = connect()
        try:
            if len(parts) < 2:
                raise ApiError("not found", 404)

            # Predefined queries: /api/query/<name>?student_id=1
            if parts[1] == "query":
                if method != "GET" or len(parts) < 3 or parts[2] not in QUERIES:
                    raise ApiError("unknown query", 404)
                sql, params = QUERIES[parts[2]]
                qs = parse_qs(url.query)
                missing = [p for p in params if p not in qs]
                if missing:
                    raise ApiError("missing parameter: " + ", ".join(missing))
                return self.reply(200, fetch(c, sql, [qs[p][0] for p in params]))

            # CRUD: /api/<table>[/<id>]
            table = parts[1]
            if table not in TABLES:
                raise ApiError("unknown table: " + table, 404)
            pk, cols = TABLES[table]

            if method == "GET":
                return self.reply(200, fetch(c, f"SELECT * FROM {table} ORDER BY {pk}"))

            if method == "POST":
                d = self.read_json()
                use = [k for k in cols if k in d and d[k] != ""]
                if use:
                    sql = (f"INSERT INTO {table} ({', '.join(use)}) "
                           f"VALUES ({', '.join('?' * len(use))})")
                else:
                    sql = f"INSERT INTO {table} DEFAULT VALUES"
                cur = c.execute(sql, [d[k] for k in use])
                c.commit()
                return self.reply(201, {"id": cur.lastrowid})

            if len(parts) < 3:
                raise ApiError("row id required")
            rid = parts[2]

            if method == "PUT":
                d = self.read_json()
                use = [k for k in cols if k in d]
                if not use:
                    raise ApiError("no editable fields supplied")
                sets = ", ".join(f"{k} = ?" for k in use)
                values = [None if d[k] == "" else d[k] for k in use]
                cur = c.execute(f"UPDATE {table} SET {sets} WHERE {pk} = ?", values + [rid])
                c.commit()
                if cur.rowcount == 0:
                    raise ApiError("row not found", 404)
                return self.reply(200, {"ok": True})

            if method == "DELETE":
                cur = c.execute(f"DELETE FROM {table} WHERE {pk} = ?", [rid])
                c.commit()
                if cur.rowcount == 0:
                    raise ApiError("row not found", 404)
                return self.reply(200, {"ok": True})

            raise ApiError("method not allowed", 405)

        except ApiError as e:
            c.rollback()
            self.reply(e.code, {"error": str(e)})
        except (sqlite3.Error, ValueError) as e:
            c.rollback()
            self.reply(400, {"error": f"{type(e).__name__}: {e}"})
        finally:
            c.close()

    # ---------- HTTP verbs ----------
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self.handle_api("GET")
        if path in ("/", "/index.html"):
            return self.reply(200, PAGE, "text/html; charset=utf-8")
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        self.handle_api("POST")

    def do_PUT(self):
        self.handle_api("PUT")

    def do_DELETE(self):
        self.handle_api("DELETE")

    def log_message(self, *args):
        pass  # keep the console quiet


PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlaceMate - Placement Management System</title>
<style>
  :root { --bg:#eaf2fb; --navy:#0b1f3a; --blue:#5aa9ff; --orange:#ff7a1a; --lime:#b6f04a; }
  body { margin:0; font-family:system-ui,Arial,sans-serif; background:var(--bg); color:var(--navy); }
  header { background:var(--navy); color:#fff; padding:14px 5vw; }
  header b { font-size:24px; font-style:italic; }
  header small { display:block; color:var(--lime); }
  main { padding:20px 5vw; }
  button, input, select {
    font:600 12px system-ui; border:2px solid var(--navy); border-radius:6px;
    padding:7px 10px; background:#fff; color:var(--navy);
  }
  button { cursor:pointer; }
  .on  { background:var(--navy); color:#fff; }
  .go  { background:var(--lime); }
  .del { background:#ffd9d9; }
  .card {
    background:#fff; border:2px solid var(--navy); border-radius:8px;
    box-shadow:5px 5px 0 var(--navy); padding:14px; margin:14px 0;
  }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th { background:var(--blue); text-align:left; }
  th, td { padding:7px 9px; border-bottom:1px solid #cfe3fa; white-space:nowrap; }
  .w { overflow-x:auto; }
  #msg { font-weight:700; margin:8px 0; }
  .ok  { color:#1a8f3c; }
  .err { color:#c0262d; }
  form { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
</style>
</head>
<body>
<header>
  <b>PLACEMATE</b>
  <small>College Placement Management System - Class CSAI1</small>
</header>
<main>
  <div id="tabs"></div>
  <div class="card">
    <form id="f"></form>
    <div id="msg"></div>
    <div class="w" id="t"></div>
  </div>
  <div class="card">
    <b>Queries</b> student id: <input id="sid" value="1" size="3">
    <button onclick="q('eligible')">Eligible drives</button>
    <button onclick="q('view_eligible')">View: eligible_drives</button>
    <button onclick="q('packages')">Highest/avg package</button>
    <button onclick="q('no_applications')">No applications</button>
    <button onclick="q('branch_placed')">Placed by branch</button>
    <div class="w" id="qr"></div>
  </div>
</main>
<script>
const T = {
  student:     ['name','email','branch','cgpa','backlogs'],
  company:     ['name','sector','location'],
  drive:       ['company_id','role','package_lpa','min_cgpa','drive_date'],
  application: ['student_id','drive_id','status'],
  offer:       ['app_id','ctc_lpa','joining_date']
};
const PK = {
  student:'student_id', company:'company_id', drive:'drive_id',
  application:'app_id', offer:'offer_id'
};
let cur = 'student', edit = null, data = [];
const $ = id => document.getElementById(id);

// escape values before putting them into HTML
const esc = v => String(v ?? '').replace(/[&<>"']/g,
  ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

const say = (m, ok) => {
  $('msg').className = ok ? 'ok' : 'err';
  $('msg').textContent = (ok ? 'OK: ' : 'Error: ') + m;
};

const api = async (method, url, body) => {
  const r = await fetch(url, {
    method,
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error);
  return j;
};

const tbl = rows => rows.length
  ? `<table><tr>${Object.keys(rows[0]).map(k => `<th>${esc(k)}</th>`).join('')}</tr>` +
    rows.map(x => `<tr>${Object.values(x).map(v => `<td>${esc(v)}</td>`).join('')}</tr>`).join('') +
    `</table>`
  : '0 rows';

async function load() {
  data = await api('GET', '/api/' + cur);

  $('tabs').innerHTML = Object.keys(T).map(k =>
    `<button class="${k === cur ? 'on' : ''}" onclick="cur='${k}';edit=null;load()">${k}</button> `
  ).join('');

  const row = edit !== null ? data.find(d => d[PK[cur]] == edit) : {};
  $('f').innerHTML =
    T[cur].map(c =>
      `<input id="f_${c}" placeholder="${c}" value="${esc(row && row[c])}">`).join('') +
    `<button class="go" type="submit">${edit !== null ? 'SAVE' : 'ADD'}</button>` +
    (edit !== null ? '<button type="button" onclick="edit=null;load()">CANCEL</button>' : '');

  const cols = Object.keys(data[0] || {[PK[cur]]: 1});
  $('t').innerHTML =
    `<table><tr>${cols.map(k => `<th>${esc(k)}</th>`).join('')}<th>actions</th></tr>` +
    data.map(d =>
      `<tr>${Object.values(d).map(v => `<td>${esc(v)}</td>`).join('')}` +
      `<td><button onclick="edit=${d[PK[cur]]};load()">Edit</button> ` +
      `<button class="del" onclick="del(${d[PK[cur]]})">Delete</button></td></tr>`
    ).join('') + `</table>`;
}

$('f').onsubmit = async e => {
  e.preventDefault();
  const body = {};
  T[cur].forEach(c => body[c] = $('f_' + c).value.trim());
  try {
    if (edit !== null) {
      await api('PUT', '/api/' + cur + '/' + edit, body);
      say('row updated', 1);
      edit = null;
    } else {
      const r = await api('POST', '/api/' + cur, body);
      say('row inserted (id ' + r.id + ')', 1);
    }
    await load();
  } catch (x) { say(x.message, 0); }
};

async function del(id) {
  if (!confirm('Delete row ' + id + '?')) return;
  try {
    await api('DELETE', '/api/' + cur + '/' + id);
    say('row deleted', 1);
    load();
  } catch (x) { say(x.message, 0); }
}

async function q(name) {
  try {
    const rows = await api('GET', '/api/query/' + name +
      '?student_id=' + encodeURIComponent($('sid').value));
    $('qr').innerHTML = tbl(rows);
  } catch (x) { say(x.message, 0); }
}

load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    init_db()
    print(f"PlaceMate running at http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
