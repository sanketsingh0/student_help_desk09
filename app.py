import os
import sqlite3
from functools import wraps
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deploying")
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(app.root_path) / "data"))
DATABASE = DATA_DIR / "studyspace.db"
DEFAULT_DRIVE_URL = os.environ.get("DRIVE_FOLDER_URL", "https://drive.google.com/")

def get_db():
    if "db" not in g:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db: db.close()

def init_database():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL, drive_url TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '📚');
    """)
    email = os.environ.get("ADMIN_EMAIL", "admin@example.com").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
    if not db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        db.execute("INSERT INTO users (name,email,password,is_admin) VALUES (?,?,?,1)", ("Administrator", email, generate_password_hash(password)))
    if not db.execute("SELECT id FROM materials").fetchone():
        db.executemany("INSERT INTO materials (title,description,category,drive_url,icon) VALUES (?,?,?,?,?)", [
          ("Class Notes", "Chapter-wise notes and explanations.", "Notes", DEFAULT_DRIVE_URL, "📝"),
          ("Previous-Year Papers", "Practice papers for examinations.", "Practice", DEFAULT_DRIVE_URL, "📄"),
          ("Assignments & Projects", "Guides and submission resources.", "Resources", DEFAULT_DRIVE_URL, "📁"),
          ("Video Lectures", "Recorded classes and learning videos.", "Videos", DEFAULT_DRIVE_URL, "🎥")])
    db.commit()

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

@app.route("/")
def home():
    return render_template("index.html", materials=get_db().execute("SELECT * FROM materials ORDER BY id DESC").fetchall())

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email, password = request.form.get("name", "").strip(), request.form.get("email", "").strip().lower(), request.form.get("password", "")
        if not name or not email or len(password) < 8: flash("Enter your name, email, and a password of at least 8 characters.", "error")
        else:
            try:
                db = get_db(); db.execute("INSERT INTO users (name,email,password) VALUES (?,?,?)", (name, email, generate_password_hash(password))); db.commit()
                flash("Registration successful. Please log in.", "success"); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("An account with this email already exists.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email, password = request.form.get("email", "").strip().lower(), request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear(); session.update(user_id=user["id"], user_name=user["name"], is_admin=bool(user["is_admin"]))
            return redirect(url_for("admin_dashboard") if user["is_admin"] else url_for("home"))
        flash("Incorrect email or password.", "error")
    return render_template("auth.html", mode="login")

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
    return render_template("admin.html", materials=get_db().execute("SELECT * FROM materials ORDER BY id DESC").fetchall(), edit_item=None)

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

with app.app_context(): init_database()
if __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
