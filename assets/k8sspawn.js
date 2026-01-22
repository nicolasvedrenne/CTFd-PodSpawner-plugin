(() => {
  const POLL_INTERVAL_MS = 4000;

  function detectChallengeId() {
    const fromData = document.querySelector("[data-challenge-id]");
    if (fromData && fromData.dataset.challengeId) {
      return parseInt(fromData.dataset.challengeId, 10);
    }
    const modal = document.querySelector("#challenge-window");
    if (modal && modal.dataset.challengeId) {
      return parseInt(modal.dataset.challengeId, 10);
    }
    const match = window.location.pathname.match(/challenges\/(\d+)/);
    if (match) {
      return parseInt(match[1], 10);
    }
    return null;
  }

  const challengeId = detectChallengeId();
  if (!challengeId) {
    return;
  }

  const container = document.createElement("div");
  container.id = "k8s-spawn-widget";
  container.style.border = "1px solid #e5e5e5";
  container.style.padding = "12px";
  container.style.marginTop = "12px";
  container.style.borderRadius = "8px";

  const title = document.createElement("div");
  title.textContent = "Instance Kubernetes";
  title.style.fontWeight = "bold";
  title.style.marginBottom = "6px";

  const statusLine = document.createElement("div");
  const endpointLine = document.createElement("div");
  endpointLine.style.wordBreak = "break-all";
  const expiresLine = document.createElement("div");

  const buttons = document.createElement("div");
  buttons.style.marginTop = "8px";
  const spawnBtn = document.createElement("button");
  spawnBtn.textContent = "Déployer";
  spawnBtn.className = "btn btn-primary btn-sm";

  const stopBtn = document.createElement("button");
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
    document.querySelector("#challenge-window") ||
    document.querySelector(".challenge-body") ||
    document.querySelector(".challenge-details") ||
    document.querySelector("main") ||
    document.body;
  target.appendChild(container);

  let pollTimer = null;
  let expiresAt = null;

  function setLoading(isLoading) {
    spawnBtn.disabled = isLoading;
    stopBtn.disabled = isLoading;
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
    const resp = await fetch(`/plugins/k8sspawn/${path}`, {
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
    try {
      const data = await api(`status/${challengeId}`, { method: "GET" });
      updateView(data.instance);
    } catch (err) {
      updateView(null);
    }
  }

  async function spawn() {
    setLoading(true);
    try {
      const data = await api(`spawn/${challengeId}`, { method: "POST" });
      updateView(data.instance);
    } catch (err) {
      alert(`Impossible de déployer : ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function stop() {
    setLoading(true);
    try {
      const data = await api(`stop/${challengeId}`, { method: "POST" });
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

  spawnBtn.addEventListener("click", (e) => {
    e.preventDefault();
    spawn();
  });
  stopBtn.addEventListener("click", (e) => {
    e.preventDefault();
    stop();
  });

  refreshStatus();
  pollTimer = window.setInterval(() => {
    refreshStatus();
    tickCountdown();
  }, POLL_INTERVAL_MS);
})();
