from threading import Thread
from sqlalchemy import text

from CTFd.models import db
from CTFd.plugins import (
    register_plugin_assets_directory,
    register_plugin_script,
)

from .routes import admin_bp, pod_bp, schedule_cleanup_loop


def _ensure_schema(engine):
    # Minimal safety migrations for new columns without Alembic.
    stmts = [
        ("route_name", "VARCHAR(128)"),
        ("hostname", "VARCHAR(256)"),
    ]
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for col, coltype in stmts:
            try:
                exists = None
                if dialect == "sqlite":
                    exists_rows = conn.execute(
                        text("PRAGMA table_info('k8s_instances')")
                    ).fetchall()
                    exists = any(r[1] == col for r in exists_rows)
                else:
                    exists_row = conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.COLUMNS "
                            "WHERE TABLE_NAME = 'k8s_instances' AND COLUMN_NAME = :col"
                        ),
                        {"col": col},
                    ).first()
                    exists = bool(exists_row)
                if not exists:
                    conn.execute(text(f"ALTER TABLE k8s_instances ADD COLUMN {col} {coltype}"))
            except Exception:
                # Don't break plugin load if schema check fails.
                pass


def load(app):
    register_plugin_assets_directory(app, base_path="/plugins/podspawner/assets")
    register_plugin_script("/plugins/podspawner/assets/podspawner.js")

    app.register_blueprint(pod_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        _ensure_schema(db.engine)
        db.create_all()

    # Start background cleanup thread
    thread = Thread(target=schedule_cleanup_loop, args=(app,), daemon=True)
    thread.start()
