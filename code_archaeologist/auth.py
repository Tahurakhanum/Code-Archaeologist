import re
from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from .database import get_db
from .security import csrf_protect

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        return _signup_post()
    return render_template("auth/signup.html")

@csrf_protect
def _signup_post():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if len(name) < 2 or not EMAIL.match(email) or len(password) < 8:
        flash("Use a name, valid email, and password of at least 8 characters.", "error")
        return render_template("auth/signup.html"), 400
    db = get_db()
    try:
        cursor = db.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)", (name, email, generate_password_hash(password)))
        db.commit()
    except Exception:
        flash("Unable to create the account. Try signing in or another email.", "error")
        return render_template("auth/signup.html"), 400
    session.clear()
    session["user_id"], session["user_name"] = cursor.lastrowid, name
    flash("Account created. Welcome to Code Archaeologist!", "success")
    return redirect(url_for("dashboard.index"))

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        return _login_post()
    return render_template("auth/login.html")

@csrf_protect
def _login_post():
    email, password = request.form.get("email", "").strip().lower(), request.form.get("password", "")
    user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        flash("Incorrect email or password.", "error")
        return render_template("auth/login.html"), 401
    session.clear()
    session["user_id"], session["user_name"] = user["id"], user["name"]
    return redirect(url_for("dashboard.index"))

@auth_bp.post("/logout")
@login_required
@csrf_protect
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.landing"))
