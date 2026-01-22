(() => {
  const POLL_INTERVAL_MS = 4000;
  const DETECT_INTERVAL_MS = 500;

  let currentChallengeId = null;
  let container = null;
  let statusLine = null;
  let endpointLine = null;
  let expiresLine = null;
  let spawnBtn = null;
  let stopBtn = null;
  let pollTimer = null;
  let detectTimer = null;
  let expiresAt = null;

  function parseIntSafe(val) {
    const n = parseInt(val, 10);
    return Number.isFinite(n) ? n : null;
  }

  function detectChallengeId(root = document) {
    if (root && root.dataset && root.dataset.challengeId) {
      return parseIntSafe(root.dataset.challengeId);
    }
    const attr = root.querySelector("[data-challenge-id]");
    if (attr && attr.dataset.challengeId) return parseIntSafe(attr.dataset.challengeId);

    const modal = root.querySelector("#challenge-window") || root.querySelector("#challenge-modal");
    if (modal && modal.dataset && modal.dataset.challengeId)
      return parseIntSafe(modal.dataset.challengeId);

    const input = root.querySelector("input[name='challenge_id']");
    if (input && input.value) return parseIntSafe(input.value);

    const hidden = root.querySelector("#challenge-id");
    if (hidden && hidden.textContent) return parseIntSafe(hidden.textContent.trim());

    const hashMatch = window.location.hash && window.location.hash.match(/#(\d+)/);
    if (hashMatch) return parseIntSafe(hashMatch[1]);

    const pathMatch = window.location.pathname.match(/challenges\/(\d+)/);
    if (pathMatch) return parseIntSafe(pathMatch[1]);

    const internal = window.CTFd && window.CTFd._internal && window.CTFd._internal.challenge;
    if (internal && internal.id) return parseIntSafe(internal.id);

    return null;
  }

  function findTarget(root = document) {
    if (root && typeof root.matches === "function") {
      if (root.matches("#challenge-window") || root.matches("#challenge-modal")) {
        return root.querySelector(".modal-body") || root;
      }
    }
    return (
      root.querySelector("#challenge-window .modal-body") ||
      root.querySelector("#challenge-modal .modal-body") ||
      root.querySelector("#challenge-window") ||
      root.querySelector("#challenge-modal") ||
      root.querySelector(".challenge-body") ||
      root.querySelector(".challenge-details") ||
      root.querySelector("main") ||
      root.body ||
      document.body
    );
  }

  function teardown() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
    expiresAt = null;
    if (container && container.parentNode) {
      container.parentNode.removeChild(container);
    }
    container = null;
    statusLine = null;
    endpointLine = null;
    expiresLine = null;
    spawnBtn = null;
    stopBtn = null;
    currentChallengeId = null;
  }

  function createContainer(target) {
    container = document.createElement("div");
    container.id = "k8s-spawn-widget";
    container.style.border = "1px solid #e5e5e5";
    container.style.padding = "12px";
    container.style.marginTop = "12px";
    container.style.borderRadius = "8px";

    const title = document.createElement("div");
    title.textContent = "Instance Kubernetes";
    title.style.fontWeight = "bold";
    title.style.marginBottom = "6px";

    statusLine = document.createElement("div");
    endpointLine = document.createElement("div");
    endpointLine.style.wordBreak = "break-all";
    expiresLine = document.createElement("div");

    const buttons = document.createElement("div");
    buttons.style.marginTop = "8px";
    spawnBtn = document.createElement("button");
    spawnBtn.textContent = "Déployer";
    spawnBtn.className = "btn btn-primary btn-sm";

    stopBtn = document.createElement("button");
    stopBtn.textContent = "Arrêter";
    stopBtn.className = "btn btn-outline-danger btn-sm";
    stopBtn.style.marginLeft = "6px";

    buttons.appendChild(spawnBtn);
    buttons.appendChild(stopBtn);
    container.appendChild(title);
    container.appendChild(statusLine);
    container.appendChild(endpointLine);
    container.appendChild(expiresLine);
    container.appendChild(buttons);

    target.appendChild(container);

    spawnBtn.addEventListener("click", (e) => {
      e.preventDefault();
      spawn();
    });
    stopBtn.addEventListener("click", (e) => {
      e.preventDefault();
      stop();
    });
  }

  function setLoading(isLoading) {
    if (spawnBtn) spawnBtn.disabled = isLoading;
    if (stopBtn) stopBtn.disabled = isLoading;
  }

  function updateView(instance) {
    if (!instance) {
      statusLine.textContent = "Aucune instance en cours.";
      endpointLine.textContent = "";
      expiresLine.textContent = "";
      return;
    }
    statusLine.textContent = `Statut : ${instance.status}`;
    endpointLine.textContent = instance.endpoint
      ? `Endpoint : ${instance.endpoint}`
      : "Endpoint : n/a";
    expiresAt = instance.expires_at ? new Date(instance.expires_at) : null;
    if (expiresAt) {
      const delta = Math.max(0, expiresAt.getTime() - Date.now());
      const mins = Math.floor(delta / 60000);
      const secs = Math.floor((delta % 60000) / 1000);
      expiresLine.textContent = `Expiration dans ${mins}m ${secs}s`;
    } else {
      expiresLine.textContent = "";
    }
  }

  async function api(path, opts) {
    const resp = await fetch(`/plugins/podspawner/${path}`, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.success === false) {
      const msg = data.message || resp.statusText || "Erreur";
      throw new Error(msg);
    }
    return data;
  }

  async function refreshStatus() {
    if (!currentChallengeId) return;
    try {
      const data = await api(`status/${currentChallengeId}`, { method: "GET" });
      updateView(data.instance);
    } catch (err) {
      updateView(null);
    }
  }

  async function spawn() {
    if (!currentChallengeId) return;
    setLoading(true);
    try {
      const data = await api(`spawn/${currentChallengeId}`, { method: "POST" });
      updateView(data.instance);
    } catch (err) {
      alert(`Impossible de déployer : ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function stop() {
    if (!currentChallengeId) return;
    setLoading(true);
    try {
      const data = await api(`stop/${currentChallengeId}`, { method: "POST" });
      updateView(data.instance);
    } catch (err) {
      alert(`Arrêt impossible : ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  function tickCountdown() {
    if (expiresAt) {
      const delta = expiresAt.getTime() - Date.now();
      if (delta <= 0) {
        expiresLine.textContent = "Expirée";
        expiresAt = null;
      } else {
        const mins = Math.floor(delta / 60000);
        const secs = Math.floor((delta % 60000) / 1000);
        expiresLine.textContent = `Expiration dans ${mins}m ${secs}s`;
      }
    }
  }

  function mountFor(challengeId, target) {
    if (!challengeId || !target) return;
    if (challengeId === currentChallengeId && container) return;
    teardown();
    currentChallengeId = challengeId;
    createContainer(target);
    refreshStatus();
    pollTimer = window.setInterval(() => {
      refreshStatus();
      tickCountdown();
    }, POLL_INTERVAL_MS);
  }

  function detectAndMount(root = document) {
    const challengeId = detectChallengeId(root);
    const target = findTarget(root);
    if (challengeId && target) {
      mountFor(challengeId, target);
    } else if (!challengeId && container) {
      teardown();
    }
  }

  function setupDetectors() {
    detectAndMount();
    detectTimer = window.setInterval(detectAndMount, DETECT_INTERVAL_MS);

    window.addEventListener("hashchange", detectAndMount);
    document.addEventListener("shown.bs.modal", (ev) => {
      const modal = ev.target;
      if (!modal.matches("#challenge-window, #challenge-modal")) return;
      detectAndMount(modal);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupDetectors);
  } else {
    setupDetectors();
  }
})();
