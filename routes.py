import re
import time
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from CTFd.models import Challenges, db
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils.user import get_current_user

from .k8s_client import K8sApiError, K8sClient
from .models import (
    K8sChallengeConfig,
    K8sInstance,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_STOPPED,
)

k8s_bp = Blueprint(
    "k8sspawn",
    __name__,
    template_folder="templates",
    static_folder="assets",
    url_prefix="/plugins/k8sspawn",
)


def _now():
    return datetime.utcnow()


def _get_namespace():
    return current_app.config.get("K8SSPAWN_NAMESPACE", "ctf-challenges")


def _build_client():
    return K8sClient(
        host=current_app.config.get("K8SSPAWN_API_HOST", "kubernetes.default.svc"),
        namespace=_get_namespace(),
        token_path=current_app.config.get(
            "K8SSPAWN_TOKEN_PATH",
            "/var/run/secrets/kubernetes.io/serviceaccount/token",
        ),
        ca_path=current_app.config.get(
            "K8SSPAWN_CA_PATH",
            "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        ),
        timeout=int(current_app.config.get("K8SSPAWN_API_TIMEOUT", 5)),
    )


def _get_client_safe():
    try:
        return _build_client(), None
    except Exception as exc:
        current_app.logger.exception("Unable to initialize Kubernetes client")
        return None, str(exc)


def _image_allowed(image, allowlist_prefix=None):
    prefix = allowlist_prefix or current_app.config.get("K8SSPAWN_IMAGE_PREFIX")
    if prefix:
        return image.startswith(prefix)
    return True


def _build_resource_limits(config: K8sChallengeConfig):
    return {
        "requests": {"cpu": config.cpu_request, "memory": config.mem_request},
        "limits": {"cpu": config.cpu_limit, "memory": config.mem_limit},
    }


def _sanitize_name(value):
    return re.sub(r"[^a-z0-9-]", "", value.lower())


def _build_resource_name(kind, challenge_id, user_id, instance_id):
    short_id = instance_id.split("-")[0]
    base = f"{kind}-chal{challenge_id}-u{user_id}-{short_id}"
    return _sanitize_name(base)[:63]


def _build_endpoint(service_name, namespace, port, protocol="http"):
    proto = (protocol or "http").lower()
    if proto not in {"http", "https"}:
        proto = "http"
    return f"{proto}://{service_name}.{namespace}.svc.cluster.local:{port}"


def _rate_limit_seconds():
    try:
        return int(current_app.config.get("K8SSPAWN_RATE_LIMIT_SECONDS", 10))
    except (TypeError, ValueError):
        return 10


def _serialize_instance(instance: K8sInstance):
    return {
        "instance_id": instance.id,
        "status": instance.status,
        "endpoint": instance.endpoint,
        "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
        "last_error": instance.last_error,
    }


def _validate_config(config: K8sChallengeConfig):
    if not config.enabled:
        return False, "Challenge not enabled for Kubernetes"
    required = [
        config.image,
        config.container_port,
        config.cpu_request,
        config.cpu_limit,
        config.mem_request,
        config.mem_limit,
        config.ttl_seconds,
    ]
    if any(v is None or v == "" for v in required):
        return False, "Configuration incomplete"
    if config.container_port <= 0 or config.ttl_seconds <= 0:
        return False, "Port and TTL must be greater than zero"
    if config.protocol and config.protocol.lower() not in {"http", "https"}:
        return False, "Protocol must be http or https"
    if not _image_allowed(config.image, config.allowlist_prefix):
        return False, "Image not allowed by allowlist prefix"
    return True, None


@k8s_bp.route("/admin", methods=["GET"])
@admins_only
def admin_index():
    challenges = Challenges.query.all()
    configs = {cfg.challenge_id: cfg for cfg in K8sChallengeConfig.query.all()}
    return render_template(
        "admin/k8sspawn.html",
        challenges=challenges,
        configs=configs,
        namespace=_get_namespace(),
    )


@k8s_bp.route("/admin/<int:challenge_id>", methods=["POST"])
@admins_only
def admin_save_config(challenge_id):
    data = request.form or request.json or {}
    config = K8sChallengeConfig.query.filter_by(challenge_id=challenge_id).first()
    if not config:
        config = K8sChallengeConfig(challenge_id=challenge_id)
    config.image = data.get("image", "").strip()
    config.container_port = int(data.get("container_port", 0) or 0)
    config.cpu_request = data.get("cpu_request", "").strip()
    config.cpu_limit = data.get("cpu_limit", "").strip()
    config.mem_request = data.get("mem_request", "").strip()
    config.mem_limit = data.get("mem_limit", "").strip()
    config.ttl_seconds = int(data.get("ttl_seconds", 0) or 0)
    config.allowlist_prefix = (data.get("allowlist_prefix") or "").strip() or None
    config.enabled = str(data.get("enabled", "")).lower() in {"1", "true", "on", "yes"}
    config.protocol = (data.get("protocol") or "http").lower()
    db.session.add(config)
    db.session.commit()
    if request.is_json:
        return jsonify({"success": True, "config": config.to_dict()})
    return redirect(url_for("k8sspawn.admin_index"))


def _get_latest_instance(challenge_id, user_id):
    inst = (
        K8sInstance.query.filter_by(challenge_id=challenge_id, user_id=user_id)
        .order_by(K8sInstance.created_at.desc())
        .first()
    )
    if inst and inst.expires_at and inst.expires_at <= _now():
        if inst.status not in {STATUS_STOPPED, STATUS_EXPIRED}:
            inst.status = STATUS_EXPIRED
            db.session.add(inst)
            db.session.commit()
    return inst


def _get_active_instance(challenge_id, user_id):
    inst = _get_latest_instance(challenge_id, user_id)
    if not inst:
        return None
    if inst.status in {STATUS_STOPPED, STATUS_EXPIRED}:
        return None
    if inst.expires_at and inst.expires_at <= _now():
        return None
    return inst


def _enforce_rate_limit(challenge_id, user_id):
    window = timedelta(seconds=_rate_limit_seconds())
    latest = (
        K8sInstance.query.filter_by(challenge_id=challenge_id, user_id=user_id)
        .order_by(K8sInstance.created_at.desc())
        .first()
    )
    if not latest:
        return False
    return _now() - latest.created_at < window


@k8s_bp.route("/spawn/<int:challenge_id>", methods=["POST"])
@authed_only
def spawn_instance(challenge_id):
    user = get_current_user()
    challenge = Challenges.query.filter_by(id=challenge_id).first()
    if not challenge:
        return jsonify({"success": False, "message": "Challenge not found"}), 404

    if _enforce_rate_limit(challenge_id, user.id):
        return jsonify({"success": False, "message": "Too many requests"}), 429

    config = K8sChallengeConfig.query.filter_by(challenge_id=challenge_id).first()
    if not config:
        return jsonify({"success": False, "message": "Challenge not configured"}), 400

    ok, error = _validate_config(config)
    if not ok:
        return jsonify({"success": False, "message": error}), 400

    active = _get_active_instance(challenge_id, user.id)
    if active:
        return jsonify({"success": True, "instance": _serialize_instance(active)})

    instance_id = str(uuid.uuid4())
    deployment_name = _build_resource_name("deploy", challenge_id, user.id, instance_id)
    service_name = _build_resource_name("svc", challenge_id, user.id, instance_id)
    expires_at = _now() + timedelta(seconds=config.ttl_seconds)

    labels = {
        "ctf.managed": "true",
        "ctf.user_id": str(user.id),
        "ctf.challenge_id": str(challenge_id),
        "ctf.instance_id": instance_id,
    }

    instance = K8sInstance(
        id=instance_id,
        challenge_id=challenge_id,
        user_id=user.id,
        k8s_namespace=_get_namespace(),
        deployment_name=deployment_name,
        service_name=service_name,
        created_at=_now(),
        expires_at=expires_at,
        status=STATUS_PENDING,
    )
    db.session.add(instance)
    db.session.commit()

    client, client_error = _get_client_safe()
    if not client:
        instance.status = STATUS_FAILED
        instance.last_error = client_error
        db.session.add(instance)
        db.session.commit()
        return (
            jsonify({"success": False, "message": "Kubernetes client error", "error": client_error}),
            500,
        )
    try:
        _ = client.create_deployment(
            name=deployment_name,
            image=config.image,
            container_port=config.container_port,
            resources=_build_resource_limits(config),
            labels=labels,
        )
        _ = client.create_service(
            name=service_name,
            selector_labels=labels,
            port=config.container_port,
            target_port=config.container_port,
            labels=labels,
        )
        status_info = client.get_deployment_status(deployment_name)
        instance.status = STATUS_READY if status_info.get("ready") else STATUS_PENDING
        instance.endpoint = _build_endpoint(
            service_name, _get_namespace(), config.container_port, config.protocol
        )
        db.session.add(instance)
        db.session.commit()
    except (K8sApiError, SQLAlchemyError) as exc:
        current_app.logger.exception("Failed to spawn challenge instance")
        instance.status = STATUS_FAILED
        instance.last_error = str(exc)
        db.session.add(instance)
        db.session.commit()
        try:
            client.delete_service(service_name)
            client.delete_deployment(deployment_name)
        except Exception:
            pass
        return jsonify({"success": False, "message": "Kubernetes error", "error": str(exc)}), 500

    return jsonify({"success": True, "instance": _serialize_instance(instance)})


@k8s_bp.route("/stop/<int:challenge_id>", methods=["POST"])
@authed_only
def stop_instance(challenge_id):
    user = get_current_user()
    inst = _get_active_instance(challenge_id, user.id)
    if not inst:
        return jsonify({"success": False, "message": "No active instance"}), 404

    client, client_error = _get_client_safe()
    if not client:
        inst.last_error = client_error
        db.session.add(inst)
        db.session.commit()
        return (
            jsonify({"success": False, "message": "Kubernetes client error", "error": client_error}),
            500,
        )
    try:
        client.delete_service(inst.service_name)
        client.delete_deployment(inst.deployment_name)
    except K8sApiError as exc:
        inst.last_error = str(exc)
    inst.status = STATUS_STOPPED
    inst.expires_at = _now()
    db.session.add(inst)
    db.session.commit()
    return jsonify({"success": True, "instance": _serialize_instance(inst)})


@k8s_bp.route("/status/<int:challenge_id>", methods=["GET"])
@authed_only
def instance_status(challenge_id):
    user = get_current_user()
    inst = _get_latest_instance(challenge_id, user.id)
    if not inst:
        return jsonify({"success": False, "message": "No instance"}), 404

    if inst.status not in {STATUS_STOPPED, STATUS_EXPIRED, STATUS_FAILED}:
        try:
            client, client_error = _get_client_safe()
            if not client:
                return (
                    jsonify(
                        {"success": False, "message": "Kubernetes client error", "error": client_error}
                    ),
                    500,
                )
            status_info = client.get_deployment_status(inst.deployment_name)
            inst.status = STATUS_READY if status_info.get("ready") else STATUS_PENDING
            db.session.add(inst)
            db.session.commit()
        except K8sApiError as exc:
            inst.status = STATUS_FAILED
            inst.last_error = str(exc)
            db.session.add(inst)
            db.session.commit()
    return jsonify({"success": True, "instance": _serialize_instance(inst)})


@k8s_bp.route("/cron/cleanup", methods=["POST"])
@admins_only
def cleanup_route():
    cleaned = cleanup_expired_instances()
    return jsonify({"success": True, "cleaned": cleaned})


def cleanup_expired_instances():
    client, client_error = _get_client_safe()
    if not client:
        current_app.logger.error("Cleanup skipped: %s", client_error)
        return 0
    now = _now()
    expired = (
        K8sInstance.query.filter(
            K8sInstance.expires_at <= now,
            K8sInstance.status.notin_([STATUS_EXPIRED, STATUS_STOPPED]),
        )
        .limit(50)
        .all()
    )
    cleaned = 0
    for inst in expired:
        try:
            client.delete_service(inst.service_name)
            client.delete_deployment(inst.deployment_name)
        except Exception as exc:
            inst.last_error = str(exc)
        inst.status = STATUS_EXPIRED
        db.session.add(inst)
        cleaned += 1
    if cleaned:
        db.session.commit()
    return cleaned


def schedule_cleanup_loop(app, interval=60):
    while True:
        try:
            with app.app_context():
                cleanup_expired_instances()
        except Exception as exc:
            app.logger.error("Cleanup loop failed: %s", exc)
        time.sleep(interval)
