import json
import os
import ssl
import http.client


class K8sApiError(Exception):
    def __init__(self, status, message, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class K8sClient:
    """
    Minimal HTTP client for Kubernetes API using stdlib only.
    """

    def __init__(
        self,
        host="kubernetes.default.svc",
        namespace="ctf-challenges",
        token_path="/var/run/secrets/kubernetes.io/serviceaccount/token",
        ca_path="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        timeout=5,
    ):
        self.host = host
        self.namespace = namespace
        self.token = self._read_file(token_path)
        self.ssl_context = self._build_ssl_context(ca_path)
        self.timeout = timeout

    def _read_file(self, path):
        if not os.path.exists(path):
            raise RuntimeError(f"Missing file: {path}")
        with open(path, "r", encoding="utf-8") as fp:
            return fp.read().strip()

    def _build_ssl_context(self, ca_path):
        if os.path.exists(ca_path):
            return ssl.create_default_context(cafile=ca_path)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _request(self, method, path, body=None, expected=(200, 201, 202, 204, 404)):
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        conn = http.client.HTTPSConnection(
            self.host, 443, context=self.ssl_context, timeout=self.timeout
        )
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            payload = json.loads(raw.decode() or "{}")
        except Exception:
            payload = {"raw": raw.decode(errors="ignore")}

        if resp.status not in expected:
            message = payload.get("message") if isinstance(payload, dict) else payload
            raise K8sApiError(
                resp.status, f"{method} {path} failed with {resp.status}: {message}", payload
            )
        return resp.status, payload

    def _ns_path(self, path):
        return path.format(namespace=self.namespace)

    def create_deployment(
        self,
        name,
        image,
        container_port,
        resources,
        labels,
        protocol="TCP",
    ):
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {
                        "labels": labels,
                    },
                    "spec": {
                        "automountServiceAccountToken": False,
                        "hostNetwork": False,
                        "hostPID": False,
                        "hostIPC": False,
                        "enableServiceLinks": False,
                        "dnsPolicy": "ClusterFirst",
                        "restartPolicy": "Always",
                        "terminationGracePeriodSeconds": 10,
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [
                            {
                                "name": "challenge",
                                "image": image,
                                "imagePullPolicy": "IfNotPresent",
                                "ports": [
                                    {
                                        "containerPort": container_port,
                                        "name": "challenge",
                                        "protocol": protocol,
                                    }
                                ],
                                "resources": resources,
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "allowPrivilegeEscalation": False,
                                    "privileged": False,
                                    "capabilities": {"drop": ["ALL"]},
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                            }
                        ],
                    },
                },
            },
        }
        return self._request(
            "POST",
            self._ns_path("/apis/apps/v1/namespaces/{namespace}/deployments"),
            body=manifest,
            expected=(200, 201, 202),
        )

    def create_service(self, name, selector_labels, port, target_port, labels, protocol="TCP"):
        manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": self.namespace, "labels": labels},
            "spec": {
                "type": "ClusterIP",
                "selector": selector_labels,
                "ports": [
                    {
                        "name": "challenge",
                        "port": port,
                        "targetPort": target_port,
                        "protocol": protocol,
                    }
                ],
            },
        }
        return self._request(
            "POST",
            self._ns_path("/api/v1/namespaces/{namespace}/services"),
            body=manifest,
            expected=(200, 201, 202),
        )

    def get_deployment_status(self, name):
        status_code, payload = self._request(
            "GET",
            self._ns_path(f"/apis/apps/v1/namespaces/{{namespace}}/deployments/{name}"),
            expected=(200, 404),
        )
        if status_code == 404:
            return {"exists": False, "ready": False, "available_replicas": 0}
        status = payload.get("status", {}) if isinstance(payload, dict) else {}
        available = status.get("availableReplicas", 0) or 0
        ready_replicas = status.get("readyReplicas", 0) or 0
        conditions = {c.get("type"): c.get("status") for c in status.get("conditions", [])}
        ready = available > 0 or conditions.get("Available") == "True"
        return {
            "exists": True,
            "ready": bool(ready),
            "available_replicas": available,
            "ready_replicas": ready_replicas,
            "conditions": conditions,
        }

    def delete_deployment(self, name):
        body = {"propagationPolicy": "Background"}
        return self._request(
            "DELETE",
            self._ns_path(f"/apis/apps/v1/namespaces/{{namespace}}/deployments/{name}"),
            body=body,
            expected=(200, 202, 204, 404),
        )

    def delete_service(self, name):
        return self._request(
            "DELETE",
            self._ns_path(f"/api/v1/namespaces/{{namespace}}/services/{name}"),
            expected=(200, 202, 204, 404),
        )
