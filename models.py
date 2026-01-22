import uuid
from datetime import datetime

from CTFd.models import db

STATUS_PENDING = "PENDING"
STATUS_READY = "READY"
STATUS_FAILED = "FAILED"
STATUS_STOPPED = "STOPPED"
STATUS_EXPIRED = "EXPIRED"


class K8sChallengeConfig(db.Model):
    __tablename__ = "k8s_challenge_configs"

    challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id"), primary_key=True, nullable=False
    )
    image = db.Column(db.String(256), nullable=False)
    container_port = db.Column(db.Integer, nullable=False)
    cpu_request = db.Column(db.String(32), nullable=False)
    cpu_limit = db.Column(db.String(32), nullable=False)
    mem_request = db.Column(db.String(32), nullable=False)
    mem_limit = db.Column(db.String(32), nullable=False)
    ttl_seconds = db.Column(db.Integer, default=1800, nullable=False)
    protocol = db.Column(db.String(8), default="http", nullable=False)
    allowlist_prefix = db.Column(db.String(256))
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    challenge = db.relationship(
        "Challenges", backref=db.backref("k8s_config", uselist=False)
    )

    def to_dict(self):
        return {
            "challenge_id": self.challenge_id,
            "image": self.image,
            "container_port": self.container_port,
            "cpu_request": self.cpu_request,
            "cpu_limit": self.cpu_limit,
            "mem_request": self.mem_request,
            "mem_limit": self.mem_limit,
            "ttl_seconds": self.ttl_seconds,
            "protocol": self.protocol,
            "allowlist_prefix": self.allowlist_prefix,
            "enabled": self.enabled,
        }


class K8sInstance(db.Model):
    __tablename__ = "k8s_instances"

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id"), nullable=False, index=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    k8s_namespace = db.Column(db.String(64), nullable=False, default="ctf-challenges")
    deployment_name = db.Column(db.String(128), nullable=False)
    service_name = db.Column(db.String(128), nullable=False)
    route_name = db.Column(db.String(128))
    hostname = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(16), default=STATUS_PENDING, nullable=False)
    endpoint = db.Column(db.String(256))
    last_error = db.Column(db.Text)

    challenge = db.relationship("Challenges", backref="k8s_instances")
    user = db.relationship("Users", backref="k8s_instances")

    __table_args__ = (
        db.UniqueConstraint("challenge_id", "user_id", "id"),
        db.Index("idx_k8s_instances_user_challenge", "user_id", "challenge_id"),
    )

    def is_expired(self):
        return datetime.utcnow() >= self.expires_at

    def to_dict(self):
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "user_id": self.user_id,
            "status": self.status,
            "endpoint": self.endpoint,
            "hostname": self.hostname,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_error": self.last_error,
        }
