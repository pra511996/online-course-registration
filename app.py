from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta

DATABASE = os.path.join(os.path.dirname(__file__), "ocrs.db")

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.executescript('''
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT CHECK(role IN ('student','admin')) NOT NULL
    );
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        credits INTEGER NOT NULL CHECK(credits > 0)
    );
    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
        UNIQUE(user_id, course_id)
    );
    ''')
    db.commit()

def seed_demo():
    db = get_db()

    def maybe_user(username, password, role):
        if not db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            db.execute(
                "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
                (username, generate_password_hash(password), role)
            )

    maybe_user("student1", "pass123", "student")
    maybe_user("admin", "admin123", "admin")

    for code, title, credits in [
        ("CMSC101", "Intro to Programming", 3),
        ("CMSC215", "Data Structures", 4),
        ("CMSC325", "Database Systems", 3),
        ("CMSC330", "Web Development", 3),
        ("CMSC340", "Software Engineering", 3),
    ]:
        if not db.execute("SELECT 1 FROM courses WHERE code=?", (code,)).fetchone():
            db.execute(
                "INSERT INTO courses(code,title,credits) VALUES(?,?,?)",
                (code, title, credits)
            )
    db.commit()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "devsecret")
    app.permanent_session_lifetime = timedelta(hours=8)

    # Secure session cookies (aligns with non-functional reqs)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.environ.get("FLASK_COOKIE_SECURE", ""))  # set env var to enable on HTTPS
    )

    app.teardown_appcontext(close_db)

    @app.before_request
    def _ensure_db():
        # Ensures tables exist; cheap no-op after first create
        init_db()

    # Initialize schema + seed once at startup (safe to call repeatedly)
    with app.app_context():
        init_db()
        seed_demo()

    def current_user():
        if 'user_id' in session:
            return get_db().execute(
                "SELECT * FROM users WHERE id=?", (session['user_id'],)
            ).fetchone()
        return None

    def login_required(role=None):
        from functools import wraps
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **k):
                u = current_user()
                if not u:
                    flash("Please log in.", "warning")
                    return redirect(url_for('login'))
                if role and u['role'] != role:
                    flash("Unauthorized.", "danger")
                    return redirect(url_for('dashboard'))
                return fn(*a, **k)
            return wrapper
        return deco

    @app.route('/')
    def index():
        return redirect(url_for('dashboard') if session.get('user_id') else url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            u = request.form['username'].strip()
            p = request.form['password']
            row = get_db().execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
            if row and check_password_hash(row['password_hash'], p):
                session['user_id'] = row['id']
                session.permanent = True
                flash(f"Welcome, {u}!", "success")
                return redirect(url_for('dashboard'))
            flash("Invalid credentials.", "danger")
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        flash("Logged out.", "info")
        return redirect(url_for('login'))

    @app.route('/dashboard')
    def dashboard():
        db = get_db()
        u = current_user()
        if not u:
            return redirect(url_for('login'))
        enrolled = db.execute("""
            SELECT c.* FROM enrollments e
            JOIN courses c ON c.id = e.course_id
            WHERE e.user_id = ?
        """, (u['id'],)).fetchall()
        courses = db.execute("SELECT * FROM courses ORDER BY code").fetchall()
        total = sum([c['credits'] for c in enrolled])
        return render_template('dashboard.html', user=u, enrolled=enrolled, all_courses=courses, total_credits=total)

    MAX_CREDITS = 9

    @app.route('/register/<int:course_id>', methods=['POST'])
    def register(course_id):
        u = current_user()
        if not u:
            flash("Please log in.", "warning")
            return redirect(url_for('login'))

        db = get_db()
        if db.execute(
            "SELECT 1 FROM enrollments WHERE user_id=? AND course_id=?",
            (u['id'], course_id)
        ).fetchone():
            flash("Already enrolled.", "warning")
            return redirect(url_for('dashboard'))

        total = db.execute("""
            SELECT COALESCE(SUM(c.credits),0)
            FROM enrollments e JOIN courses c ON c.id = e.course_id
            WHERE e.user_id = ?
        """, (u['id'],)).fetchone()[0]

        course = db.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        if not course:
            flash("Course not found.", "danger")
            return redirect(url_for('dashboard'))

        if total + course['credits'] > MAX_CREDITS:
            flash(f"Credit limit exceeded (max {MAX_CREDITS}).", "danger")
            return redirect(url_for('dashboard'))

        db.execute("INSERT INTO enrollments(user_id, course_id) VALUES(?, ?)", (u['id'], course_id))
        db.commit()
        flash("Enrolled.", "success")
        return redirect(url_for('dashboard'))

    @app.route('/drop/<int:course_id>', methods=['POST'])
    def drop(course_id):
        u = current_user()
        if not u:
            flash("Please log in.", "warning")
            return redirect(url_for('login'))
        db = get_db()
        db.execute("DELETE FROM enrollments WHERE user_id=? AND course_id=?", (u['id'], course_id))
        db.commit()
        flash("Dropped.", "info")
        return redirect(url_for('dashboard'))

    @app.route('/admin/courses')
    def admin_courses():
        u = current_user()
        if not u or u['role'] != 'admin':
            flash("Unauthorized.", "danger")
            return redirect(url_for('dashboard'))
        courses = get_db().execute("SELECT * FROM courses ORDER BY code").fetchall()
        return render_template('admin_courses.html', courses=courses, user=u)

    @app.route('/admin/courses/add', methods=['POST'])
    def add_course():
        u = current_user()
        if not u or u['role'] != 'admin':
            flash("Unauthorized.", "danger")
            return redirect(url_for('dashboard'))

        code = request.form['code'].strip().upper()
        title = request.form['title'].strip()
        credits = int(request.form['credits'])
        db = get_db()
        try:
            db.execute("INSERT INTO courses(code,title,credits) VALUES(?,?,?)", (code, title, credits))
            db.commit()
            flash("Added course.", "success")
        except sqlite3.IntegrityError:
            flash("Course exists or invalid.", "danger")
        return redirect(url_for('admin_courses'))

    @app.route('/admin/courses/<int:course_id>/delete', methods=['POST'])
    def delete_course(course_id):
        u = current_user()
        if not u or u['role'] != 'admin':
            flash("Unauthorized.", "danger")
            return redirect(url_for('dashboard'))
        db = get_db()
        db.execute("DELETE FROM courses WHERE id=?", (course_id,))
        db.commit()
        flash("Deleted.", "info")
        return redirect(url_for('admin_courses'))

    @app.cli.command("initdb")
    def _initdb():
        init_db()
        seed_demo()
        print("Database initialized and demo data seeded.")

    return app

if __name__ == "__main__":
    app = create_app()
    # Use FLASK_COOKIE_SECURE=1 env var when serving over HTTPS
    app.run(debug=True)
