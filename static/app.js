const peersEl = document.querySelector("#peers");
const peerCountEl = document.querySelector("#peerCount");
const addForm = document.querySelector("#addForm");
const refreshBtn = document.querySelector("#refreshBtn");
const dialog = document.querySelector("#configDialog");
const dialogTitle = document.querySelector("#dialogTitle");
const qrImage = document.querySelector("#qrImage");
const configText = document.querySelector("#configText");
const copyConfig = document.querySelector("#copyConfig");
const downloadConfig = document.querySelector("#downloadConfig");
const closeDialog = document.querySelector("#closeDialog");
const toastEl = document.querySelector("#toast");
const diagnosticsEl = document.querySelector("#diagnostics");
const nextIpEl = document.querySelector("#nextIp");
const nextIpMetricEl = document.querySelector("#nextIpMetric");
const ifaceNameEl = document.querySelector("#ifaceName");
const firewallForm = document.querySelector("#firewallForm");
const requiredInboundPortsEl = document.querySelector("#requiredInboundPorts");
const requiredOutboundPortsEl = document.querySelector("#requiredOutboundPorts");
const effectiveInboundPortsEl = document.querySelector("#effectiveInboundPorts");
const effectiveOutboundPortsEl = document.querySelector("#effectiveOutboundPorts");

function toast(message) {
  toastEl.textContent = message;
  toastEl.classList.add("show");
  window.setTimeout(() => toastEl.classList.remove("show"), 2200);
}

function confirmAction(message) {
  return window.confirm(message);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await response.json() : await response.text();
  if (!response.ok || body.ok === false) {
    throw new Error(body.error || body || `HTTP ${response.status}`);
  }
  return body;
}

function fmtBytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB"];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function fmtHandshake(ts) {
  if (!ts) return "never connected";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function renderPeers(peers) {
  peerCountEl.textContent = `${peers.length} devices`;
  peersEl.innerHTML = "";
  if (!peers.length) {
    peersEl.innerHTML = `<p class="muted">No devices yet</p>`;
    return;
  }

  for (const peer of peers) {
    const row = document.createElement("article");
    row.className = "peer";
    row.innerHTML = `
      <div class="peer-main">
        <strong>${peer.name}</strong>
        <span class="muted">${peer.ip} · ${fmtHandshake(peer.latest_handshake)}</span>
      </div>
      <div>
        <span class="badge ${peer.enabled ? "" : "paused"}">${peer.enabled ? "active" : "paused"}</span>
        ${peer.is_admin ? '<span class="badge admin">admin</span>' : ""}
      </div>
      <div class="actions">
        <button data-action="config" data-name="${peer.name}" ${peer.has_config ? "" : "disabled"}>${peer.has_config ? "Config" : "No Config"}</button>
        <button data-action="admin" data-name="${peer.name}" data-admin="${peer.is_admin ? "0" : "1"}">${peer.is_admin ? "Remove Admin" : "Make Admin"}</button>
        <button data-action="${peer.enabled ? "pause" : "resume"}" data-name="${peer.name}">${peer.enabled ? "Pause" : "Resume"}</button>
        <button class="danger" data-action="remove" data-name="${peer.name}">Delete</button>
      </div>
      <div class="traffic">${fmtBytes(peer.rx_bytes)} recv · ${fmtBytes(peer.tx_bytes)} sent</div>
    `;
    peersEl.appendChild(row);
  }
}

function renderFirewall(policy) {
  if (!policy) return;
  requiredInboundPortsEl.textContent = policy.required_inbound_ports || "None";
  requiredOutboundPortsEl.textContent = policy.required_outbound_ports || "None";
  effectiveInboundPortsEl.textContent = policy.effective_inbound_ports || "None";
  effectiveOutboundPortsEl.textContent = policy.effective_outbound_ports || "None";
  firewallForm.elements.trusted_inbound_ports.value = policy.trusted_inbound_ports || "";
  firewallForm.elements.trusted_outbound_ports.value = policy.trusted_outbound_ports || "";
}

async function refresh() {
  const data = await api("/api/status");
  if (data.diagnostics?.length) {
    diagnosticsEl.hidden = false;
    diagnosticsEl.innerHTML = data.diagnostics.map((item) => `<div>${item}</div>`).join("");
  } else {
    diagnosticsEl.hidden = true;
    diagnosticsEl.innerHTML = "";
  }
  nextIpEl.textContent = data.next_ip || "Auto";
  nextIpMetricEl.textContent = data.next_ip || "Auto";
  ifaceNameEl.textContent = data.iface || "wg0";
  renderFirewall(data.firewall);
  renderPeers(data.peers);
}

async function openConfig(name, existingConfig = "") {
  const config = existingConfig || await fetch(`/api/peers/${encodeURIComponent(name)}/config`).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.text();
  });
  dialogTitle.textContent = `${name}.conf`;
  configText.value = config;
  qrImage.src = `/api/peers/${encodeURIComponent(name)}/qr?t=${Date.now()}`;
  downloadConfig.href = `/api/peers/${encodeURIComponent(name)}/download`;
  downloadConfig.download = `${name}.conf`;
  dialog.showModal();
}

addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(addForm);
  const name = String(form.get("name") || "").trim();
  if (!confirmAction(`Add ${name} and generate a WireGuard config?`)) return;
  try {
    const data = await api("/api/peers", {
      method: "POST",
      body: JSON.stringify({
        name,
      }),
    });
    addForm.reset();
    await refresh();
    await openConfig(data.name, data.config);
  } catch (error) {
    toast(error.message);
  }
});

firewallForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(firewallForm);
  if (!confirmAction("Save trusted ports and apply the server firewall rules now?")) return;
  try {
    const data = await api("/api/firewall", {
      method: "POST",
      body: JSON.stringify({
        trusted_inbound_ports: String(form.get("trusted_inbound_ports") || "").trim(),
        trusted_outbound_ports: String(form.get("trusted_outbound_ports") || "").trim(),
      }),
    });
    renderFirewall(data.policy);
    toast("Port policy saved");
  } catch (error) {
    toast(error.message);
  }
});

peersEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const { action, name } = button.dataset;
  try {
    if (action === "config") {
      if (!confirmAction(`Open the config and QR code for ${name}?`)) return;
      await openConfig(name);
    } else if (action === "pause") {
      if (!confirmAction(`Pause ${name}? This device will immediately lose WireGuard access.`)) return;
      await api(`/api/peers/${encodeURIComponent(name)}/pause`, { method: "POST" });
      await refresh();
    } else if (action === "resume") {
      if (!confirmAction(`Restore WireGuard access for ${name}?`)) return;
      await api(`/api/peers/${encodeURIComponent(name)}/resume`, { method: "POST" });
      await refresh();
    } else if (action === "admin") {
      const willPromote = button.dataset.admin === "1";
      if (!confirmAction(`${willPromote ? "Grant admin access to" : "Remove admin access from"} ${name}?`)) return;
      await api(`/api/peers/${encodeURIComponent(name)}/admin`, {
        method: "POST",
        body: JSON.stringify({ is_admin: willPromote }),
      });
      await refresh();
    } else if (action === "remove") {
      if (!confirmAction(`Permanently delete ${name}? Its config file and WireGuard peer will be removed.`)) return;
      await api(`/api/peers/${encodeURIComponent(name)}`, { method: "DELETE" });
      await refresh();
    }
  } catch (error) {
    toast(error.message);
  }
});

copyConfig.addEventListener("click", async () => {
  await navigator.clipboard.writeText(configText.value);
  toast("Config copied");
});

closeDialog.addEventListener("click", () => dialog.close());
refreshBtn.addEventListener("click", () => refresh().catch((error) => toast(error.message)));

refresh().catch((error) => toast(error.message));
