(() => {
  const POLL_INTERVAL_MS = 4000;

  let currentChallengeId = null;
  let container = null;
  let statusLine = null;
  let endpointLine = null;
  let expiresLine = null;
  let spawnBtn = null;
  let stopBtn = null;
  let pollTimer = null;
  let expiresAt = null;

  function detectChallengeId() {
    const fromData = document.querySelector("[data-challenge-id]");
    if (fromData && fromData.dataset.challengeId) {
      return parseInt(fromData.dataset.challengeId, 10);
    }
    const modal = document.querySelector("#challenge-window, #challenge-modal");
    if (modal && modal.dataset.challengeId) {
      return parseInt(modal.dataset.challengeId, 10);
    }
    const input = document.querySelector("input[name='challenge_id']");
    if (input && input.value) {
      return parseInt(input.value, 10);
    }
    const hashMatch = window.location.hash && window.location.hash.match(/#(\d+)/);
    if (hashMatch) {
      return parseInt(hashMatch[1], 10);
    }
    const pathMatch = window.location.pathname.match(/challenges\/(\d+)/);
    if (pathMatch) {
      return parseInt(pathMatch[1], 10);
    }
    const internal = window.CTFd && window.CTFd._internal && window.CTFd._internal.challenge;
    if (internal && internal.id) {
      return parseInt(internal.id, 10);
    }
    return null;
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

  function createContainer() {
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

    const target =
      document.querySelector("#challenge-window .modal-body") ||
      document.querySelector("#challenge-modal .modal-body") ||
      document.querySelector("#challenge-window") ||
      document.querySelector("#challenge-modal") ||
      document.querySelector(".challenge-body") ||
      document.querySelector(".challenge-details") ||
      document.querySelector("main") ||
      document.body;
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

  function mountFor(challengeId) {
    if (!challengeId) return;
    if (challengeId === currentChallengeId) return;
    teardown();
    currentChallengeId = challengeId;
    createContainer();
    refreshStatus();
    pollTimer = window.setInterval(() => {
      refreshStatus();
      tickCountdown();
    }, POLL_INTERVAL_MS);
  }

  function tryMount() {
    const challengeId = detectChallengeId();
    if (challengeId) {
      mountFor(challengeId);
    }
  }

  tryMount();
  const observer = new MutationObserver(tryMount);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener("hashchange", tryMount);
})();
