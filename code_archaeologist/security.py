"""CSRF protection suitable for server-rendered forms."""
import secrets
from functools import wraps
from flask import abort, session

def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]

def validate_csrf():
    from flask import request
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(submitted, expected):
        abort(400, "Invalid or missing form security token.")

def csrf_protect(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        validate_csrf()
        return view(*args, **kwargs)
    return wrapped
