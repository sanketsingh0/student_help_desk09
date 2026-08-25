import os
import sqlite3
import smtplib
from email.message import EmailMessage
from datetime import datetime
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row
import psycopg
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deploying")
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(app.root_path) / "data"))
DATABASE = DATA_DIR / "studyspace.db"
DATABASE_URL = os.environ.get("DATABASE_URL")
DEFAULT_DRIVE_URL = os.environ.get("DRIVE_FOLDER_URL", "https://drive.google.com/")
ADMIN_CONTACT_EMAIL = os.environ.get("ADMIN_EMAIL", "sanketsingh9186@gmail.com").strip().lower()

@app.context_processor
def inject_admin_contact():
    return {"admin_contact_email": ADMIN_CONTACT_EMAIL}

class DatabaseConnection:
    """Small compatibility layer for SQLite locally and PostgreSQL on Render."""
    def __init__(self, connection, postgres=False):
        self.connection = connection
        self.postgres = postgres

    def execute(self, query, params=None):
        if self.postgres:
            query = query.replace("?", "%s")
        return self.connection.execute(query, params or ())

    def executemany(self, query, params):
        if self.postgres:
            query = query.replace("?", "%s")
            cursor = self.connection.cursor()
            cursor.executemany(query, params)
            return cursor
        return self.connection.executemany(query, params)

    def executescript(self, script):
        return self.connection.executescript(script)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()

    def rollback(self):
        self.connection.rollback()

def get_db():
    if "db" not in g:
        if DATABASE_URL:
            g.db = DatabaseConnection(psycopg.connect(DATABASE_URL, row_factory=dict_row), postgres=True)
        else:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(DATABASE)
            connection.row_factory = sqlite3.Row
            g.db = DatabaseConnection(connection)
    return g.db

@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db: db.close()

def init_database():
    db = get_db()
    if DATABASE_URL:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            is_teacher BOOLEAN NOT NULL DEFAULT FALSE,
            student_id TEXT)""")
        db.execute("CREATE TABLE IF NOT EXISTS materials (id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL, drive_url TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '📚')")
        db.execute("""CREATE TABLE IF NOT EXISTS student_tasks (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            subject_code TEXT NOT NULL,
            subject_name TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'Assignment',
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            work_details TEXT NOT NULL DEFAULT '',
            work_link TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            progress INTEGER NOT NULL DEFAULT 0,
            teacher_remark TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '')""")
    else:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, is_teacher INTEGER NOT NULL DEFAULT 0, student_id TEXT);
        CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL, drive_url TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '📚');
        CREATE TABLE IF NOT EXISTS student_tasks (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, subject_code TEXT NOT NULL, subject_name TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Assignment', title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', work_details TEXT NOT NULL DEFAULT '', work_link TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', progress INTEGER NOT NULL DEFAULT 0, teacher_remark TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
        """)
    # Migrate databases created before the teacher/student-id columns existed.
    try:
        if DATABASE_URL:
            db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_teacher BOOLEAN NOT NULL DEFAULT FALSE")
            db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS student_id TEXT")
            db.execute("ALTER TABLE student_tasks ADD COLUMN IF NOT EXISTS work_link TEXT NOT NULL DEFAULT ''")
        else:
            user_columns = [row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()]
            if "is_teacher" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN is_teacher INTEGER NOT NULL DEFAULT 0")
            if "student_id" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN student_id TEXT")
            task_columns = [row["name"] for row in db.execute("PRAGMA table_info(student_tasks)").fetchall()]
            if "work_link" not in task_columns:
                db.execute("ALTER TABLE student_tasks ADD COLUMN work_link TEXT NOT NULL DEFAULT ''")
        db.commit()
    except Exception as error:
        app.logger.warning("Optional column migration skipped: %s", error)
    admin_email = ADMIN_CONTACT_EMAIL
    admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not admin_email or not admin_password:
        app.logger.warning("ADMIN_EMAIL / ADMIN_PASSWORD are not configured in the environment: the admin account was not created or updated. Add both to your .env file.")
    else:
        admin = db.execute("SELECT id FROM users WHERE email=?", (admin_email,)).fetchone()
        if admin:
            db.execute("UPDATE users SET name=?, password=?, is_admin=? WHERE id=?", ("Administrator", generate_password_hash(admin_password), True, admin["id"]))
        else:
            db.execute("INSERT INTO users (name,email,password,is_admin) VALUES (?,?,?,?)", ("Administrator", admin_email, generate_password_hash(admin_password), True))
        db.commit()
    if not db.execute("SELECT id FROM materials").fetchone():
        db.executemany("INSERT INTO materials (title,description,category,drive_url,icon) VALUES (?,?,?,?,?)", [
          ("Class Notes", "Chapter-wise notes and explanations.", "Notes", DEFAULT_DRIVE_URL, "📝"),
          ("Previous-Year Papers", "Practice papers for examinations.", "Practice", DEFAULT_DRIVE_URL, "📄"),
          ("Assignments & Projects", "Guides and submission resources.", "Resources", DEFAULT_DRIVE_URL, "📁"),
          ("Video Lectures", "Recorded classes and learning videos.", "Videos", DEFAULT_DRIVE_URL, "🎥")])
    db.commit()

def send_email(recipient, subject, body):
    """Send via Brevo's HTTP API when BREVO_API_KEY is set. Required on Render's
    free tier, since outbound SMTP (ports 25/465/587) has been blocked there
    since Sept 2025 - smtplib will always time out on a free instance.
    Falls back to Gmail SMTP only for local development."""
    brevo_key = os.environ.get("BREVO_API_KEY", "").strip()
    if brevo_key:
        return _send_via_brevo(brevo_key, recipient, subject, body)
    return _send_via_smtp(recipient, subject, body)

def _send_via_brevo(api_key, recipient, subject, body):
    sender_email = os.environ.get("EMAIL", "").strip()
    if not sender_email:
        app.logger.warning("Email was not sent: EMAIL is not configured for the Brevo sender.")
        return False
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
            json={
                "sender": {"name": "StudySpace", "email": sender_email},
                "to": [{"email": recipient}],
                "subject": subject,
                "textContent": body,
            },
            timeout=15,
        )
        if response.status_code >= 400:
            app.logger.error("Brevo delivery failed: %s %s", response.status_code, response.text)
            return False
        return True
    except requests.RequestException as error:
        app.logger.error("Brevo delivery failed: %s", error)
        return False

def _send_via_smtp(recipient, subject, body):
    sender = os.environ.get("EMAIL", "").strip()
    app_password = os.environ.get("APP_PASSWORD", "").replace(" ", "")
    if not sender or not app_password:
        app.logger.warning("Email was not sent: no BREVO_API_KEY, and EMAIL/APP_PASSWORD is not configured.")
        return False
    message = EmailMessage()
    message["From"] = f"StudySpace <{sender}>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(sender, app_password)
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as error:
        app.logger.error("SMTP delivery failed: %s", error)
        return False

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access study materials.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Administrator access is required.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

def teacher_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not (session.get("is_admin") or session.get("is_teacher")):
            flash("Teacher access is required. Ask an administrator to mark your account as a teacher.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

@app.route("/")
def home():
    return render_template("index.html", materials=get_db().execute("SELECT * FROM materials ORDER BY id DESC").fetchall())

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email, password = request.form.get("name", "").strip(), request.form.get("email", "").strip().lower(), request.form.get("password", "")
        student_id = request.form.get("student_id", "").strip().upper()
        if not name or not email or len(password) < 8: flash("Enter your name, email, and a password of at least 8 characters.", "error")
        else:
            try:
                db = get_db(); db.execute("INSERT INTO users (name,email,password,student_id) VALUES (?,?,?,?)", (name, email, generate_password_hash(password), student_id or None)); db.commit()
                greeting_sent = send_email(email, "Welcome to StudySpace", f"Hi {name},\n\nWelcome to StudySpace! Your account is ready. You can now log in and access study materials.\n\nRegards,\nStudySpace")
                flash("Registration successful. A welcome email has been sent." if greeting_sent else "Registration successful. Please log in.", "success"); return redirect(url_for("login"))
            except (sqlite3.IntegrityError, psycopg_errors.UniqueViolation):
                flash("An account with this email already exists.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_id = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=? OR student_id=? OR student_id=?", (login_id, login_id, login_id.upper())).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session.update(user_id=user["id"], user_name=user["name"], is_admin=bool(user["is_admin"]), is_teacher=bool(user["is_teacher"]), student_id=user["student_id"] or "")
            if user["is_admin"]:
                return redirect(url_for("admin_dashboard"))
            if user["is_teacher"]:
                return redirect(url_for("teacher_panel"))
            return redirect(url_for("home"))
        flash("Incorrect login id or password.", "error")
    return render_template("auth.html", mode="login")

@app.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")

@app.route("/logout")
def logout():
    session.clear(); flash("You have been logged out.", "success"); return redirect(url_for("home"))

@app.route("/materials/<int:material_id>")
@login_required
def open_material(material_id):
    item = get_db().execute("SELECT drive_url FROM materials WHERE id=?", (material_id,)).fetchone()
    if not item: flash("That material no longer exists.", "error"); return redirect(url_for("home"))
    return redirect(item["drive_url"])

def values(): return tuple(request.form.get(k, "").strip() for k in ("title", "description", "category", "drive_url", "icon"))

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    return render_template(
        "admin.html",
        materials=get_db().execute("SELECT * FROM materials ORDER BY id DESC").fetchall(),
        edit_item=None,
    )

@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    search = request.args.get("q", "").strip()
    db = get_db()
    if search:
        users = db.execute("SELECT id, name, email, is_admin, is_teacher FROM users WHERE name LIKE ? OR email LIKE ? ORDER BY name", (f"%{search}%", f"%{search}%")).fetchall()
    else:
        users = db.execute("SELECT id, name, email, is_admin, is_teacher FROM users ORDER BY name").fetchall()
    return render_template("admin_users.html", users=users, search=search, edit_user=None)

@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    db = get_db()
    user = db.execute("SELECT id, name, email, is_admin, is_teacher FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin_users"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        is_admin = bool(request.form.get("is_admin"))
        is_teacher = bool(request.form.get("is_teacher"))
        new_password = request.form.get("new_password", "")
        if not name or not email:
            flash("Name and email are required.", "error")
        else:
            try:
                db.execute("UPDATE users SET name=?, email=?, is_admin=?, is_teacher=? WHERE id=?", (name, email, is_admin, is_teacher, user_id))
                if new_password:
                    if len(new_password) < 8:
                        flash("Password must be at least 8 characters.", "error")
                        return render_template("admin_users.html", users=db.execute("SELECT id, name, email, is_admin, is_teacher FROM users ORDER BY name").fetchall(), search="", edit_user=user)
                    db.execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(new_password), user_id))
                db.commit()
                flash(f"User {name} updated.", "success")
                return redirect(url_for("admin_users"))
            except (sqlite3.IntegrityError, psycopg_errors.UniqueViolation):
                flash("An account with this email already exists.", "error")
    return render_template("admin_users.html", users=db.execute("SELECT id, name, email, is_admin, is_teacher FROM users ORDER BY name").fetchall(), search="", edit_user=user)

@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    db = get_db()
    user = db.execute("SELECT id, name, is_admin FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        flash("User not found.", "error")
    elif user["is_admin"]:
        flash("Cannot delete an administrator account.", "error")
    elif user_id == session.get("user_id"):
        flash("You cannot delete your own account.", "error")
    else:
        db.execute("DELETE FROM users WHERE id=?", (user_id,))
        db.commit()
        flash(f"User {user['name']} deleted.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/materials/add", methods=["POST"])
@login_required
@admin_required
def add_material():
    data = values()
    if all(data):
        db=get_db(); db.execute("INSERT INTO materials (title,description,category,drive_url,icon) VALUES (?,?,?,?,?)", data); db.commit(); flash("Study material added.", "success")
    else: flash("Complete every material field.", "error")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/materials/<int:material_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_material(material_id):
    db=get_db(); item=db.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    if not item: flash("Material not found.", "error"); return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        data=values()
        if all(data): db.execute("UPDATE materials SET title=?,description=?,category=?,drive_url=?,icon=? WHERE id=?", (*data, material_id)); db.commit(); flash("Study material updated.", "success"); return redirect(url_for("admin_dashboard"))
        flash("Complete every material field.", "error")
    return render_template("admin.html", materials=db.execute("SELECT * FROM materials ORDER BY id DESC").fetchall(), edit_item=item)

@app.route("/admin/materials/<int:material_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_material(material_id):
    db=get_db(); db.execute("DELETE FROM materials WHERE id=?", (material_id,)); db.commit(); flash("Study material removed.", "success")
    return redirect(url_for("admin_dashboard"))

# ---------------------------------------------------------------- students
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@app.route("/my-tasks")
@login_required
def student_tasks():
    db = get_db()
    subject_code = request.args.get("subject_code", "").strip().upper()
    if subject_code:
        tasks = db.execute("SELECT * FROM student_tasks WHERE student_id=? AND subject_code=? ORDER BY id DESC", (session["user_id"], subject_code)).fetchall()
    else:
        tasks = db.execute("SELECT * FROM student_tasks WHERE student_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    codes = db.execute("SELECT DISTINCT subject_code FROM student_tasks WHERE student_id=? ORDER BY subject_code", (session["user_id"],)).fetchall()
    return render_template("student_tasks.html", tasks=tasks, edit_task=None, subject_code=subject_code, subject_codes=codes)

@app.route("/tasks/add", methods=["POST"])
@login_required
def add_task():
    subject_code = request.form.get("subject_code", "").strip().upper()
    subject_name = request.form.get("subject_name", "").strip()
    category = request.form.get("category", "").strip()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    work_details = request.form.get("work_details", "").strip()
    work_link = request.form.get("work_link", "").strip()
    if not subject_code or not category:
        flash("Subject code and category are required.", "error")
    else:
        now = _now()
        db = get_db()
        db.execute("INSERT INTO student_tasks (student_id, subject_code, subject_name, category, title, description, work_details, work_link, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (session["user_id"], subject_code, subject_name, category, title or "Untitled task", description, work_details, work_link, now, now))
        db.commit()
        flash("Task added to your panel.", "success")
    return redirect(url_for("student_tasks"))

@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    db = get_db()
    task = db.execute("SELECT * FROM student_tasks WHERE id=? AND student_id=?", (task_id, session["user_id"])).fetchone()
    if not task:
        flash("Task not found.", "error")
        return redirect(url_for("student_tasks"))
    if request.method == "POST":
        subject_code = request.form.get("subject_code", "").strip().upper()
        subject_name = request.form.get("subject_name", "").strip()
        category = request.form.get("category", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        work_details = request.form.get("work_details", "").strip()
        work_link = request.form.get("work_link", "").strip()
        if not subject_code or not category:
            flash("Subject code and category are required.", "error")
        else:
            db.execute("UPDATE student_tasks SET subject_code=?, subject_name=?, category=?, title=?, description=?, work_details=?, work_link=?, updated_at=? WHERE id=? AND student_id=?",
                (subject_code, subject_name, category, title or "Untitled task", description, work_details, work_link, _now(), task_id, session["user_id"]))
            db.commit()
            flash("Task updated.", "success")
            return redirect(url_for("student_tasks"))
    tasks = db.execute("SELECT * FROM student_tasks WHERE student_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    codes = db.execute("SELECT DISTINCT subject_code FROM student_tasks WHERE student_id=? ORDER BY subject_code", (session["user_id"],)).fetchall()
    return render_template("student_tasks.html", tasks=tasks, edit_task=task, subject_code="", subject_codes=codes)

@app.route("/tasks/<int:task_id>/submit-link", methods=["POST"])
@login_required
def submit_task_link(task_id):
    db = get_db()
    task = db.execute("SELECT id FROM student_tasks WHERE id=? AND student_id=?", (task_id, session["user_id"])).fetchone()
    if not task:
        flash("Task not found.", "error")
        return redirect(url_for("student_tasks"))
    work_link = request.form.get("work_link", "").strip()
    if not work_link:
        flash("Please paste a link to your submitted work.", "error")
    else:
        if not work_link.startswith(("http://", "https://")):
            work_link = "https://" + work_link
        db.execute("UPDATE student_tasks SET work_link=?, updated_at=? WHERE id=? AND student_id=?", (work_link, _now(), task_id, session["user_id"]))
        db.commit()
        flash("Submission link saved. Teachers can now open it.", "success")
    return redirect(url_for("student_tasks"))

@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM student_tasks WHERE id=? AND student_id=?", (task_id, session["user_id"]))
    db.commit()
    flash("Task removed.", "success")
    return redirect(url_for("student_tasks"))

# ---------------------------------------------------------------- teacher panel
@app.route("/teacher")
@login_required
@teacher_required
def teacher_panel():
    db = get_db()
    subject_code = request.args.get("subject_code", "").strip().upper()
    student_filter = request.args.get("student_id", "").strip()
    query = ("SELECT t.*, u.name AS student_name, u.email AS student_email, u.student_id AS student_roll "
             "FROM student_tasks t JOIN users u ON u.id = t.student_id")
    where, params = [], []
    if subject_code:
        where.append("t.subject_code=?")
        params.append(subject_code)
    if student_filter.isdigit():
        where.append("t.student_id=?")
        params.append(int(student_filter))
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY t.id DESC"
    tasks = db.execute(query, params).fetchall()
    students = db.execute("SELECT id, name, student_id FROM users WHERE NOT is_admin AND NOT is_teacher ORDER BY name").fetchall()
    codes = db.execute("SELECT DISTINCT subject_code FROM student_tasks ORDER BY subject_code").fetchall()
    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")
    in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
    avg_progress = round(sum(t["progress"] for t in tasks) / total) if total else 0
    return render_template("teacher.html", tasks=tasks, students=students, subject_codes=codes,
        subject_code=subject_code, selected_student=student_filter, total=total,
        completed=completed, in_progress=in_progress, avg_progress=avg_progress)

@app.route("/teacher/tasks/<int:task_id>/update", methods=["POST"])
@login_required
@teacher_required
def teacher_update_task(task_id):
    db = get_db()
    if not db.execute("SELECT id FROM student_tasks WHERE id=?", (task_id,)).fetchone():
        flash("Task not found.", "error")
        return redirect(url_for("teacher_panel"))
    status = request.form.get("status", "pending").strip()
    if status not in ("pending", "in_progress", "completed"):
        status = "pending"
    try:
        progress = int(request.form.get("progress", "0"))
    except ValueError:
        progress = 0
    progress = max(0, min(100, progress))
    if status == "completed":
        progress = 100
    remark = request.form.get("remark", "").strip()
    db.execute("UPDATE student_tasks SET status=?, progress=?, teacher_remark=?, updated_at=? WHERE id=?",
        (status, progress, remark, _now(), task_id))
    db.commit()
    flash("Task status updated.", "success")
    return redirect(url_for("teacher_panel",
        subject_code=request.form.get("subject_code", ""),
        student_id=request.form.get("student_id", "")))

with app.app_context(): init_database()
if __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)