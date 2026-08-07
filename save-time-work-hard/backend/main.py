import re
import secrets
from io import BytesIO
from contextlib import asynccontextmanager
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from docx import Document
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import UPLOAD_DIR, get_conn, hash_password, init_db, now_iso, verify_password
from jd_parser import parse_jd
from resume_builder import ResumeBuildError, build_resume

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_UPLOAD = 20 * 1024 * 1024

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Save time, Work hard", lifespan=lifespan)


# --------------------------------------------------------------------------- helpers


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def public_user(row) -> dict:
    d = dict(row)
    d.pop("password_hash", None)
    return d


def current_user(authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Not logged in")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?", (token,)
        ).fetchone()
    if row is None or row["disabled"]:
        raise HTTPException(401, "Session expired, please log in again")
    user = public_user(row)
    user["token"] = token
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return user


def clean_path(raw: str) -> str:
    return raw.strip().strip('"').strip("'").strip()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "").strip().rstrip(". ")
    if name.lower().endswith(".docx"):
        name = name[:-5].rstrip(". ")
    if not name:
        raise HTTPException(400, "Filename is empty")
    return name[:150] + ".docx"


def get_resume_for(conn, resume_id: int, user: dict) -> dict:
    row = conn.execute("SELECT * FROM default_resumes WHERE id = ?", (resume_id,)).fetchone()
    if row is None or (row["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "Default resume not found")
    return dict(row)


def get_bid_for(conn, bid_id: int, user: dict) -> dict:
    row = conn.execute("SELECT * FROM bids WHERE id = ?", (bid_id,)).fetchone()
    if row is None or (row["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "Bid not found")
    return dict(row)


# --------------------------------------------------------------------------- auth


class LoginIn(BaseModel):
    identifier: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn):
    ident = body.identifier.strip()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? OR username = ?", (ident, ident)
        ).fetchone()
        if row is None or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "Wrong e-mail or password")
        if row["disabled"]:
            raise HTTPException(403, "This account is disabled")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                     (token, row["id"], now_iso()))
    return {"token": token, "user": public_user(row)}


@app.post("/api/auth/logout")
def logout(user: dict = Depends(current_user)):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (user["token"],))
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    user.pop("token", None)
    return user


class MeUpdate(BaseModel):
    display_name: str


@app.put("/api/me")
def update_me(body: MeUpdate, user: dict = Depends(current_user)):
    name = body.display_name.strip()
    if not name:
        raise HTTPException(400, "Name cannot be empty")
    with get_conn() as conn:
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, user["id"]))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return public_user(row)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@app.put("/api/me/password")
def change_password(body: PasswordChange, user: dict = Depends(current_user)):
    if len(body.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    with get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(body.old_password, row["password_hash"]):
            raise HTTPException(400, "Current password is wrong")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (hash_password(body.new_password), user["id"]))
    return {"ok": True}


# --------------------------------------------------------------------------- default resumes


class ResumeIn(BaseModel):
    label: str = ""
    path: str


@app.get("/api/resumes")
def list_resumes(user: dict = Depends(current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, (SELECT COUNT(*) FROM bids b WHERE b.default_resume_id = r.id) AS bid_count"
            " FROM default_resumes r WHERE r.user_id = ? ORDER BY r.id", (user["id"],)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["exists"] = Path(d["path"]).is_file()
        d["uploaded"] = is_uploaded(d["path"])
        out.append(d)
    return out


def is_uploaded(path: str) -> bool:
    try:
        return Path(path).resolve().is_relative_to(UPLOAD_DIR.resolve())
    except OSError:
        return False


@app.post("/api/resumes/upload")
async def upload_resume(request: Request, filename: str, label: str = "", resume_id: int | None = None,
                        user: dict = Depends(current_user)):
    """Stores a default resume sent from the browser (raw .docx body) in the user's server folder.

    With resume_id, replaces the file of an uploaded default resume in place.
    """
    data = await request.body()
    if not data:
        raise HTTPException(400, "The file is empty")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 20 MB")
    try:
        Document(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - python-docx raises several types
        raise HTTPException(400, "That is not a valid .docx file") from exc

    with get_conn() as conn:
        if resume_id is not None:
            existing = get_resume_for(conn, resume_id, user)
            if not is_uploaded(existing["path"]):
                raise HTTPException(400, "Only uploaded resumes can be replaced; edit the path instead")
            target = Path(existing["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_bytes(data)
            except PermissionError as exc:
                raise HTTPException(423, "The file is open on the server; close it and try again") from exc
            if label.strip():
                conn.execute("UPDATE default_resumes SET label = ? WHERE id = ?", (label.strip(), resume_id))
            return dict(conn.execute("SELECT * FROM default_resumes WHERE id = ?", (resume_id,)).fetchone())

        folder = UPLOAD_DIR / re.sub(r"[^A-Za-z0-9_.\-]", "_", f"{user['id']}_{user['username']}")
        folder.mkdir(parents=True, exist_ok=True)
        name = sanitize_filename(Path(filename).name)
        target = folder / name
        n = 2
        while target.exists():
            target = folder / f"{Path(name).stem} ({n}).docx"
            n += 1
        target.write_bytes(data)
        cur = conn.execute(
            "INSERT INTO default_resumes (user_id, label, path, created_at) VALUES (?, ?, ?, ?)",
            (user["id"], label.strip() or target.stem, str(target.resolve()), now_iso()),
        )
        if user["active_resume_id"] is None:
            conn.execute("UPDATE users SET active_resume_id = ? WHERE id = ?", (cur.lastrowid, user["id"]))
        return dict(conn.execute("SELECT * FROM default_resumes WHERE id = ?", (cur.lastrowid,)).fetchone())


@app.post("/api/resumes")
def add_resume(body: ResumeIn, user: dict = Depends(current_user)):
    path = clean_path(body.path)
    p = Path(path)
    if p.suffix.lower() != ".docx":
        raise HTTPException(400, "The default resume must be a .docx file")
    if not p.is_file():
        raise HTTPException(400, f"File not found on this computer: {path}")
    label = body.label.strip() or p.stem
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO default_resumes (user_id, label, path, created_at) VALUES (?, ?, ?, ?)",
            (user["id"], label, str(p.resolve()), now_iso()),
        )
        if user["active_resume_id"] is None:
            conn.execute("UPDATE users SET active_resume_id = ? WHERE id = ?", (cur.lastrowid, user["id"]))
        row = conn.execute("SELECT * FROM default_resumes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/resumes/{resume_id}")
def update_resume(resume_id: int, body: ResumeIn, user: dict = Depends(current_user)):
    path = clean_path(body.path)
    p = Path(path)
    if p.suffix.lower() != ".docx" or not p.is_file():
        raise HTTPException(400, f"A .docx file was not found at: {path}")
    with get_conn() as conn:
        get_resume_for(conn, resume_id, user)
        conn.execute("UPDATE default_resumes SET label = ?, path = ? WHERE id = ?",
                     (body.label.strip() or p.stem, str(p.resolve()), resume_id))
        row = conn.execute("SELECT * FROM default_resumes WHERE id = ?", (resume_id,)).fetchone()
    return dict(row)


@app.put("/api/resumes/{resume_id}/activate")
def activate_resume(resume_id: int, user: dict = Depends(current_user)):
    with get_conn() as conn:
        get_resume_for(conn, resume_id, user)
        conn.execute("UPDATE users SET active_resume_id = ? WHERE id = ?", (resume_id, user["id"]))
    return {"ok": True}


@app.delete("/api/resumes/{resume_id}")
def delete_resume(resume_id: int, user: dict = Depends(current_user)):
    with get_conn() as conn:
        get_resume_for(conn, resume_id, user)
        conn.execute("DELETE FROM default_resumes WHERE id = ?", (resume_id,))
        conn.execute("UPDATE users SET active_resume_id = NULL WHERE active_resume_id = ?", (resume_id,))
    return {"ok": True}


@app.get("/api/resumes/{resume_id}/file")
def resume_file(resume_id: int, user: dict = Depends(current_user)):
    with get_conn() as conn:
        r = get_resume_for(conn, resume_id, user)
    if not Path(r["path"]).is_file():
        raise HTTPException(404, "The default resume file no longer exists")
    return FileResponse(r["path"], media_type=DOCX_MIME, filename=Path(r["path"]).name)


# --------------------------------------------------------------------------- bids


class JdIn(BaseModel):
    jd_text: str = ""
    job_url: str = ""


@app.post("/api/jd/parse")
def jd_parse(body: JdIn, user: dict = Depends(current_user)):
    return parse_jd(body.jd_text, body.job_url)


class BuildIn(BaseModel):
    default_resume_id: int
    resume_html: str = ""
    resume_text: str = ""


class BidCreate(BuildIn):
    jd_text: str = ""
    job_url: str = ""
    job_title: str = ""
    company_name: str = ""
    jobsite_name: str = ""
    bid_date: str
    bid_time: str
    filename: str
    overwrite: bool = False


def _build(resume: dict, html: str, text: str) -> bytes:
    if not Path(resume["path"]).is_file():
        raise HTTPException(400, f"Default resume file not found: {resume['path']}")
    try:
        return build_resume(resume["path"], html, text)
    except ResumeBuildError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/bids/preview")
def preview_bid(body: BuildIn, user: dict = Depends(current_user)):
    with get_conn() as conn:
        resume = get_resume_for(conn, body.default_resume_id, user)
    return Response(_build(resume, body.resume_html, body.resume_text), media_type=DOCX_MIME)


@app.post("/api/bids")
def create_bid(body: BidCreate, user: dict = Depends(current_user)):
    filename = sanitize_filename(body.filename)
    with get_conn() as conn:
        resume = get_resume_for(conn, body.default_resume_id, user)
    default_path = Path(resume["path"])
    target = default_path.parent / filename
    if target.resolve() == default_path.resolve():
        raise HTTPException(400, "That filename is the default resume itself; choose another name")
    if target.exists() and not body.overwrite:
        raise HTTPException(409, f"{filename} already exists in {target.parent}")

    data = _build(resume, body.resume_html, body.resume_text)
    try:
        target.write_bytes(data)
    except PermissionError as exc:
        raise HTTPException(423, f"Cannot write {filename}. Is it open in Word? Close it and try again.") from exc

    now = now_iso()
    values = (resume["id"], resume["label"], resume["path"], body.bid_date, body.bid_time,
              body.job_title.strip(), body.company_name.strip(), body.jobsite_name.strip(), body.job_url.strip(),
              body.jd_text, body.resume_html, body.resume_text, filename, str(target))
    with get_conn() as conn:
        # An overwritten file keeps a single history entry: update the one that pointed at it.
        existing = conn.execute("SELECT id FROM bids WHERE user_id = ? AND file_path = ? ORDER BY id DESC",
                                (user["id"], str(target))).fetchone()
        if existing is not None:
            conn.execute(
                """UPDATE bids SET default_resume_id = ?, default_resume_label = ?, default_resume_path = ?,
                       bid_date = ?, bid_time = ?, job_title = ?, company_name = ?, jobsite_name = ?, job_url = ?,
                       jd_text = ?, resume_html = ?, resume_text = ?, filename = ?, file_path = ?, updated_at = ?
                   WHERE id = ?""",
                (*values, now, existing["id"]),
            )
            bid_id = existing["id"]
        else:
            bid_id = conn.execute(
                """INSERT INTO bids (default_resume_id, default_resume_label, default_resume_path,
                       bid_date, bid_time, job_title, company_name, jobsite_name, job_url, jd_text,
                       resume_html, resume_text, filename, file_path, user_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, user["id"], now, now),
            ).lastrowid
        row = conn.execute("SELECT * FROM bids WHERE id = ?", (bid_id,)).fetchone()
    return dict(row)


LIST_COLUMNS = (
    "b.id, b.user_id, b.default_resume_id, b.default_resume_label, b.bid_date, b.bid_time, b.job_title,"
    " b.company_name, b.jobsite_name, b.job_url, b.filename, b.file_path, b.created_at, b.updated_at,"
    " u.username, u.email, u.display_name"
)


def query_bids(conn, *, user_id=None, resume_id=None, q="", date_from="", date_to="", jobsite="", period=""):
    sql = f"SELECT {LIST_COLUMNS} FROM bids b JOIN users u ON u.id = b.user_id WHERE 1=1"
    args: list = []
    if user_id:
        sql += " AND b.user_id = ?"
        args.append(user_id)
    if resume_id:
        sql += " AND b.default_resume_id = ?"
        args.append(resume_id)
    if date_from:
        sql += " AND b.bid_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND b.bid_date <= ?"
        args.append(date_to)
    if period:  # YYYY-MM or YYYY-MM-DD
        sql += " AND b.bid_date LIKE ?"
        args.append(period + "%")
    if jobsite:
        sql += " AND b.jobsite_name = ?"
        args.append(jobsite)
    for term in q.split():
        like = f"%{term}%"
        sql += (" AND (b.job_title LIKE ? OR b.company_name LIKE ? OR b.jobsite_name LIKE ? OR b.filename LIKE ?"
                " OR b.job_url LIKE ? OR b.jd_text LIKE ? OR b.bid_date LIKE ? OR b.default_resume_label LIKE ?)")
        args.extend([like] * 8)
    sql += " ORDER BY b.bid_date DESC, b.bid_time DESC, b.id DESC LIMIT 2000"
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["file_exists"] = Path(d["file_path"]).is_file()
        out.append(d)
    return out


@app.get("/api/bids")
def list_bids(q: str = "", date_from: str = "", date_to: str = "", jobsite: str = "",
              resume_id: int | None = None, user: dict = Depends(current_user)):
    with get_conn() as conn:
        return query_bids(conn, user_id=user["id"], resume_id=resume_id, q=q,
                          date_from=date_from, date_to=date_to, jobsite=jobsite)


@app.get("/api/bids/suggestions")
def bid_suggestions(user: dict = Depends(current_user)):
    with get_conn() as conn:
        sites = [r[0] for r in conn.execute(
            "SELECT DISTINCT jobsite_name FROM bids WHERE user_id = ? AND jobsite_name != '' ORDER BY 1",
            (user["id"],))]
        companies = [r[0] for r in conn.execute(
            "SELECT DISTINCT company_name FROM bids WHERE user_id = ? AND company_name != '' ORDER BY 1",
            (user["id"],))]
    return {"jobsites": sites, "companies": companies}


@app.get("/api/bids/{bid_id}")
def get_bid(bid_id: int, user: dict = Depends(current_user)):
    with get_conn() as conn:
        bid = get_bid_for(conn, bid_id, user)
    bid["file_exists"] = Path(bid["file_path"]).is_file()
    return bid


class BidUpdate(BaseModel):
    bid_date: str
    bid_time: str
    job_title: str = ""
    company_name: str = ""
    jobsite_name: str = ""
    job_url: str = ""
    jd_text: str = ""
    filename: str


@app.put("/api/bids/{bid_id}")
def update_bid(bid_id: int, body: BidUpdate, user: dict = Depends(current_user)):
    with get_conn() as conn:
        bid = get_bid_for(conn, bid_id, user)
        filename = sanitize_filename(body.filename)
        file_path = bid["file_path"]
        if filename != bid["filename"]:
            old = Path(bid["file_path"])
            new = old.parent / filename
            if new.exists():
                raise HTTPException(409, f"{filename} already exists in {new.parent}")
            if old.is_file():
                try:
                    old.rename(new)
                except OSError as exc:
                    raise HTTPException(423, f"Could not rename the file (is it open in Word?): {exc}") from exc
            file_path = str(new)
        conn.execute(
            """UPDATE bids SET bid_date = ?, bid_time = ?, job_title = ?, company_name = ?, jobsite_name = ?,
                   job_url = ?, jd_text = ?, filename = ?, file_path = ?, updated_at = ? WHERE id = ?""",
            (body.bid_date, body.bid_time, body.job_title.strip(), body.company_name.strip(),
             body.jobsite_name.strip(), body.job_url.strip(), body.jd_text, filename, file_path, now_iso(), bid_id),
        )
        row = conn.execute("SELECT * FROM bids WHERE id = ?", (bid_id,)).fetchone()
    return dict(row)


@app.delete("/api/bids/{bid_id}")
def delete_bid(bid_id: int, delete_file: bool = False, user: dict = Depends(current_user)):
    with get_conn() as conn:
        bid = get_bid_for(conn, bid_id, user)
        conn.execute("DELETE FROM bids WHERE id = ?", (bid_id,))
    if delete_file:
        Path(bid["file_path"]).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/bids/{bid_id}/file")
def bid_file(bid_id: int, user: dict = Depends(current_user)):
    with get_conn() as conn:
        bid = get_bid_for(conn, bid_id, user)
    path = Path(bid["file_path"])
    if path.is_file():
        return FileResponse(path, media_type=DOCX_MIME, filename=bid["filename"])
    # The saved file was moved or deleted: rebuild it from the stored input when possible.
    if bid["default_resume_path"] and Path(bid["default_resume_path"]).is_file():
        data = _build({"path": bid["default_resume_path"]}, bid["resume_html"], bid["resume_text"])
        return Response(data, media_type=DOCX_MIME,
                        headers={"Content-Disposition": f'attachment; filename="{bid["filename"]}"'})
    raise HTTPException(404, "The saved file and its default resume are both missing")


# --------------------------------------------------------------------------- admin


class UserCreate(BaseModel):
    username: str
    email: str
    display_name: str = ""
    password: str


class UserUpdate(BaseModel):
    username: str
    email: str
    display_name: str = ""
    password: str = ""
    disabled: bool = False


def _validate_user(username: str, email: str):
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,40}", username):
        raise HTTPException(400, "Username: 3-40 letters, digits, dot, dash or underscore")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid e-mail address")


@app.get("/api/admin/users")
def admin_users(admin: dict = Depends(admin_user)):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.*, (SELECT COUNT(*) FROM bids b WHERE b.user_id = u.id) AS bid_count,
                      (SELECT COUNT(*) FROM default_resumes r WHERE r.user_id = u.id) AS resume_count,
                      (SELECT MAX(b.bid_date || ' ' || b.bid_time) FROM bids b WHERE b.user_id = u.id) AS last_bid
               FROM users u ORDER BY u.role = 'admin' DESC, u.username"""
        ).fetchall()
    return [public_user(r) for r in rows]


@app.post("/api/admin/users")
def admin_create_user(body: UserCreate, admin: dict = Depends(admin_user)):
    username, email = body.username.strip(), body.email.strip().lower()
    _validate_user(username, email)
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, email, display_name, password_hash, role, created_at)"
                " VALUES (?, ?, ?, ?, 'user', ?)",
                (username, email, body.display_name.strip() or username, hash_password(body.password), now_iso()),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "That username or e-mail is already used") from exc
    return public_user(row)


@app.put("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, body: UserUpdate, admin: dict = Depends(admin_user)):
    username, email = body.username.strip(), body.email.strip().lower()
    with get_conn() as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "User not found")
        if target["role"] == "admin":
            email = email or None
            if body.disabled:
                raise HTTPException(400, "The admin account cannot be disabled")
        else:
            _validate_user(username, email)
        try:
            conn.execute(
                "UPDATE users SET username = ?, email = ?, display_name = ?, disabled = ? WHERE id = ?",
                (username, email, body.display_name.strip() or username, int(body.disabled), user_id),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "That username or e-mail is already used") from exc
        if body.password:
            if len(body.password) < 6:
                raise HTTPException(400, "Password must be at least 6 characters")
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.password), user_id))
        if body.disabled:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return public_user(row)


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: dict = Depends(admin_user)):
    with get_conn() as conn:
        target = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "User not found")
        if target["role"] == "admin":
            raise HTTPException(400, "The admin account cannot be deleted")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True}


@app.get("/api/admin/resumes")
def admin_resumes(user_id: int | None = None, admin: dict = Depends(admin_user)):
    sql = ("SELECT r.*, u.username, u.email, (SELECT COUNT(*) FROM bids b WHERE b.default_resume_id = r.id)"
           " AS bid_count FROM default_resumes r JOIN users u ON u.id = r.user_id")
    args = []
    if user_id:
        sql += " WHERE r.user_id = ?"
        args.append(user_id)
    with get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY u.username, r.label", args).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/admin/bids")
def admin_bids(user_id: int | None = None, resume_id: int | None = None, q: str = "", date_from: str = "",
               date_to: str = "", period: str = "", admin: dict = Depends(admin_user)):
    with get_conn() as conn:
        return query_bids(conn, user_id=user_id, resume_id=resume_id, q=q, date_from=date_from,
                          date_to=date_to, period=period)


@app.get("/api/admin/stats")
def admin_stats(period: str = Query("day", pattern="^(day|month)$"), user_id: int | None = None,
                resume_id: int | None = None, date_from: str = "", date_to: str = "",
                admin: dict = Depends(admin_user)):
    key = "b.bid_date" if period == "day" else "substr(b.bid_date, 1, 7)"
    sql = (f"SELECT {key} AS period, u.id AS user_id, u.username, u.email, COUNT(*) AS count"
           " FROM bids b JOIN users u ON u.id = b.user_id WHERE 1=1")
    args: list = []
    if user_id:
        sql += " AND b.user_id = ?"
        args.append(user_id)
    if resume_id:
        sql += " AND b.default_resume_id = ?"
        args.append(resume_id)
    if date_from:
        sql += " AND b.bid_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND b.bid_date <= ?"
        args.append(date_to)
    sql += " GROUP BY period, u.id ORDER BY period DESC, count DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- frontend

if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        candidate = (DIST / full_path).resolve()
        if full_path and candidate.is_file() and DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
