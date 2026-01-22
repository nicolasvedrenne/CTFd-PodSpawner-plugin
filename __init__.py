from threading import Thread

from CTFd.models import db
from CTFd.plugins import (
    register_plugin_assets_directory,
    register_plugin_script,
)

from .routes import k8s_bp, schedule_cleanup_loop


def load(app):
    register_plugin_assets_directory(app, base_path="/plugins/podspawner/assets")
    register_plugin_script("/plugins/podspawner/assets/podspawner.js")

    app.register_blueprint(k8s_bp)

    with app.app_context():
        db.create_all()

    # Start background cleanup thread
    thread = Thread(target=schedule_cleanup_loop, args=(app,), daemon=True)
    thread.start()
