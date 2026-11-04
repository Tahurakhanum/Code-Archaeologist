"""Application factory for Code Archaeologist."""
from flask import Flask, flash, redirect, url_for
from .config import Config
from .database import init_app as init_database
from .auth import auth_bp
from .dashboard import dashboard_bp
from .main import main_bp
from .security import csrf_token

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    init_database(app)
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.errorhandler(413)
    def upload_too_large(_error):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        flash(f"That upload is larger than the {limit} MB limit. Try a smaller ZIP or use a GitHub URL.", "error")
        return redirect(url_for("dashboard.new_analysis"))

    return app
