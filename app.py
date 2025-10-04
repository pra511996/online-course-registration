
from flask import Flask, request, redirect, url_for, render_template, flash, session
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# ------------------------
# Core Models & Exceptions
# ------------------------
class CapacityFullError(Exception): pass
class NotEnrolledError(Exception): pass
class DuplicateEnrollError(Exception): pass
class NotFoundError(Exception): pass

class Course:
    def __init__(self, course_id, title, capacity):
        self.course_id = course_id
        self.title = title
        self.capacity = int(capacity)
        self.enrolled_students = []

    def has_seat(self):
        return len(self.enrolled_students) < self.capacity

    def register_student(self, student):
        if student in self.enrolled_students:
            raise DuplicateEnrollError(f"{student.student_id} already enrolled in {self.course_id}")
        if not self.has_seat():
            raise CapacityFullError(f"{self.course_id} is full")
        self.enrolled_students.append(student)
        return True

    def drop_student(self, student):
        if student not in self.enrolled_students:
            raise NotEnrolledError(f"{student.student_id} not enrolled in {self.course_id}")
        self.enrolled_students.remove(student)
        return True

class Student:
    def __init__(self, student_id, name):
        self.student_id = student_id
        self.name = name
        self.registered_courses = []

    def register_for_course(self, course):
        if course.register_student(self):
            if course not in self.registered_courses:
                self.registered_courses.append(course)
            return True
        return False

    def drop_course(self, course):
        if course.drop_student(self):
            if course in self.registered_courses:
                self.registered_courses.remove(course)
            return True
        return False

class RegistrationSystem:
    def __init__(self):
        self.courses = {}
        self.students = {}

    def add_course(self, course):
        self.courses[course.course_id] = course

    def add_student(self, student):
        self.students[student.student_id] = student

    def get_course(self, course_id):
        if course_id not in self.courses:
            raise NotFoundError(f"Course {course_id} not found")
        return self.courses[course_id]

    def get_student(self, student_id):
        if student_id not in self.students:
            raise NotFoundError(f"Student {student_id} not found")
        return self.students[student_id]

    def enroll(self, student_id, course_id):
        return self.get_student(student_id).register_for_course(self.get_course(course_id))

    def drop(self, student_id, course_id):
        return self.get_student(student_id).drop_course(self.get_course(course_id))

# ------------------------
# Flask App Setup
# ------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = "dev-secret-change-me"
csrf = CSRFProtect(app)

system = RegistrationSystem()

# seed demo data
for c in [
    Course("CMSC101", "Intro to Computer Science", 3),
    Course("CMSC220", "Data Structures", 2),
    Course("CMSC330", "Advanced Programming", 2),
    Course("CMSC495", "Capstone Project", 1),
]:
    system.add_course(c)
alice = Student("S001", "Alice")
bob = Student("S002", "Bob")
system.add_student(alice); system.add_student(bob)

# demo users
USERS = {
    "alice": {"pw": generate_password_hash("Password1!"), "role": "student", "student_id": "S001"},
    "admin": {"pw": generate_password_hash("Password1!"), "role": "admin"},
}

# ------------------------
# Auth Helpers
# ------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            flash("Please sign in first.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def role_required(role):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get("role") != role:
                flash("Not authorized.", "error")
                return redirect(url_for("home"))
            return f(*args, **kwargs)
        return wrapper
    return deco

# ------------------------
# Routes
# ------------------------
@app.route("/")
def home():
    # New professional homepage with feature tiles (links)
    return render_template("home.html", title="Home")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").lower()
        password = request.form.get("password","")
        user = USERS.get(username)
        if not user or not check_password_hash(user["pw"], password):
            flash("Invalid credentials", "error")
            return redirect(url_for("login"))
        session["user"] = username
        session["role"] = user["role"]
        if user.get("student_id"):
            session["student_id"] = user["student_id"]
        flash(f"Welcome {username}", "success")
        return redirect(url_for("home"))
    return render_template("login.html", title="Login")

@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out", "success")
    return redirect(url_for("home"))

@app.route("/student")
@login_required
@role_required("student")
def student_dashboard():
    q = request.args.get("q","").lower()
    courses = list(system.courses.values())
    if q:
        courses = [c for c in courses if q in (c.course_id + " " + c.title).lower()]
    current_student = system.get_student(session["student_id"])
    return render_template("student.html", courses=courses, current_student=current_student, title="Student")

@app.route("/student/enroll", methods=["POST"])
@login_required
@role_required("student")
def enroll_course():
    sid = session.get("student_id"); cid = request.form.get("course_id")
    try:
        system.enroll(sid, cid)
        flash(f"Enrolled in {cid}", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("student_dashboard"))

@app.route("/student/drop", methods=["POST"])
@login_required
@role_required("student")
def drop_course():
    sid = session.get("student_id"); cid = request.form.get("course_id")
    try:
        system.drop(sid, cid)
        flash(f"Dropped {cid}", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("student_dashboard"))

@app.route("/structure")
@login_required
def view_structure():
    # Simple "structure" page that shows all courses and enrollment snapshot
    snapshot = [
        {
            "course_id": c.course_id,
            "title": c.title,
            "capacity": c.capacity,
            "enrolled": len(c.enrolled_students),
            "has_seat": c.has_seat(),
        } for c in system.courses.values()
    ]
    return render_template("structure.html", snapshot=snapshot, title="Structure")

@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    return render_template("admin.html", courses=system.courses.values(), title="Admin")

@app.route("/admin/course", methods=["POST"])
@login_required
@role_required("admin")
def admin_create_course():
    cid = request.form.get("course_id"); title = request.form.get("title"); cap = int(request.form.get("capacity","0"))
    if not cid or not title or cap <= 0:
        flash("Provide Course ID, Title, and positive Capacity.", "error")
        return redirect(url_for("admin_dashboard"))
    system.add_course(Course(cid, title, cap))
    flash(f"Course {cid} created", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/student", methods=["POST"])
@login_required
@role_required("admin")
def admin_create_student():
    sid = request.form.get("student_id"); name = request.form.get("name")
    if not sid or not name:
        flash("Provide Student ID and Name.", "error")
        return redirect(url_for("admin_dashboard"))
    system.add_student(Student(sid, name))
    flash(f"Student {sid} created", "success")
    return redirect(url_for("admin_dashboard"))

# NEW: Set Enrollment Limits (change capacity)
@app.route("/admin/limits", methods=["GET","POST"])
@login_required
@role_required("admin")
def admin_limits():
    if request.method == "POST":
        cid = request.form.get("course_id")
        try:
            new_cap = int(request.form.get("capacity","0"))
        except ValueError:
            new_cap = 0
        if not cid or new_cap <= 0:
            flash("Select a course and set a positive capacity.", "error")
            return redirect(url_for("admin_limits"))
        course = system.get_course(cid)
        # If shrinking capacity below current enrollment, prevent it
        if new_cap < len(course.enrolled_students):
            flash(f"Cannot set capacity below current enrollment ({len(course.enrolled_students)}).", "error")
            return redirect(url_for("admin_limits"))
        course.capacity = new_cap
        flash(f"Capacity for {cid} set to {new_cap}.", "success")
        return redirect(url_for("admin_limits"))
    return render_template("limits.html", courses=system.courses.values(), title="Enrollment Limits")

if __name__ == "__main__":
    app.run(debug=True)
