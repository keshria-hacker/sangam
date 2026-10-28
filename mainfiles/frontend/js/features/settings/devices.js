/**
 * Devices & LAN access (Batch 6) — Settings custom section.
 *
 * Renders under the Settings "Devices" category (see settings_page.js):
 * LAN addresses + binding note, pairing start (QR + 6-digit code),
 * pending-pairing approve/deny, paired-device list + revoke, certificate
 * fingerprint + regenerate, HTTP-fallback banner, and the threat model
 * in plain language.
 *
 * Conventions (a previous batch broke these — do not repeat):
 * - apiGet/apiPost/apiDelete return the RAW Response: call .json() first.
 * - showToast takes an OBJECT: showToast({ message: '...' }).
 * - State-changing POSTs use apiPost so the CSRF header is attached.
 *
 * Honest limits, stated in the UI itself:
 * - The QR code is rendered client-side by js/vendor/qrcode.min.js
 *   (loaded on demand); if it fails to load, the code + payload text
 *   still work for manual entry.
 * - Browsers cannot pin a certificate automatically: the fingerprint
 *   next to the QR code is for MANUAL comparison on first connect.
 * - The HTTP banner appears when this section loads over plain http
 *   on a non-loopback host. (A fully global banner would need an
 *   app.js hook, which is out of this batch's scope.)
 */
import { apiDelete, apiGet, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { getSetting } from '../../shared/settings_store.js';

console.log('[Module] settings/devices.js loaded');

const THREAT_HTML = `
  <h4>What this protects — and what it doesn't</h4>
  <p class="settings-hint">Protected:</p>
  <ul class="threat-list">
    <li>Same-Wi-Fi strangers without the code + host approval — they get nothing.</li>
    <li>Code guessing or replay — codes are single-use, expire in 5 minutes, are rate-limited, and still need your approval.</li>
    <li>Passive eavesdropping on the Wi-Fi — defeated in TLS mode (see the certificate below).</li>
    <li>A stolen phone — revoke that one device here and its token stops working immediately.</li>
    <li>Token-database theft — only token hashes are stored, never raw tokens.</li>
    <li>Raw provider-key readout — keys are encrypted at rest and never sent to clients.</li>
  </ul>
  <p class="settings-hint">NOT protected:</p>
  <ul class="threat-list">
    <li>Physical access to the unlocked laptop — lock the laptop.</li>
    <li>A compromised laptop — if the host is owned, all bets are off.</li>
    <li>A malicious or compromised phone you approved — approval gives it full account access.</li>
    <li>The HTTP fallback mode — traffic is readable on the Wi-Fi.</li>
    <li>Internet exposure via port-forwarding — do not expose Sangam to the internet. This design assumes your Wi-Fi only.</li>
  </ul>`;

function fmtTime(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function isLoopbackHost(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]' || hostname === '::1';
}

function showHttpBanner() {
  // Persistent banner on this device when loaded over plain http off-loopback.
  if (window.location.protocol !== 'http:' || isLoopbackHost(window.location.hostname)) return;
  if (document.getElementById('sangam-lan-http-banner')) return;
  const banner = document.createElement('div');
  banner.id = 'sangam-lan-http-banner';
  banner.className = 'lan-banner';
  banner.textContent = 'LAN connection is not encrypted — anyone on this Wi-Fi can read your traffic.';
  document.body.prepend(banner);
}

let qrLoadPromise = null;
function ensureQrLibrary() {
  if (window.SangamQR) return Promise.resolve(true);
  if (qrLoadPromise) return qrLoadPromise;
  qrLoadPromise = new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = 'js/vendor/qrcode.min.js';
    script.onload = () => resolve(!!window.SangamQR);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
  return qrLoadPromise;
}

function clearDevicesTimers() {
  if (window.__sangamDevicesTimers) {
    for (const id of Object.values(window.__sangamDevicesTimers)) clearInterval(id);
  }
  window.__sangamDevicesTimers = {};
}

function showDevicesConfirm({ title, message, confirmLabel, onConfirm }) {
  // Same confirm-overlay pattern as Settings Reset-all (settings_page.js):
  // a fresh element per open, Escape/backdrop/Cancel dismiss, focus on
  // Cancel. Replaces the native window.confirm calls this file used to
  // make, so destructive device actions get the same in-app dialog.
  const overlay = document.createElement('div');
  overlay.className = 'confirm-overlay';
  overlay.innerHTML = `
      <div class="confirm-dialog" role="alertdialog" aria-modal="true">
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(message)}</p>
        <div class="confirm-actions">
          <button class="btn-secondary" type="button" data-devices-cancel>Cancel</button>
          <button class="btn-danger" type="button" data-devices-confirm>${escapeHtml(confirmLabel)}</button>
        </div>
      </div>`;
  const close = () => { overlay.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  overlay.querySelector('[data-devices-cancel]').addEventListener('click', close);
  overlay.querySelector('[data-devices-confirm]').addEventListener('click', () => {
    close();
    onConfirm();
  });
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
  overlay.querySelector('[data-devices-cancel]').focus();
}

async function fetchJson(path) {
  // Returns { ok, status, data } without throwing on HTTP errors.
  // Network failures still throw (caller maps them to the unreachable panel).
  const resp = await apiGet(path, false);
  let data = null;
  try { data = await resp.json(); } catch { data = null; }
  return { ok: resp.ok, status: resp.status, data };
}

export async function renderDevicesSection(container) {
  clearDevicesTimers();
  showHttpBanner();
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section devices-section';
  wrap.setAttribute('data-devices-section', '');
  wrap.innerHTML = `<h3 class="sp-section-title"><i class="fa-solid fa-mobile-screen"></i> Devices &amp; LAN access</h3>
    <div class="sp-section-body" data-devices-body><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  const body = wrap.querySelector('[data-devices-body]');

  const renderUnreachable = () => {
    body.innerHTML = `<div class="devices-unreachable">
      <p>Can't reach your Sangam — connect to the same Wi-Fi as your laptop.</p>
      <button type="button" class="btn-secondary" data-devices-retry>Retry</button>
    </div>`;
    body.querySelector('[data-devices-retry]').addEventListener('click', () => {
      container.removeChild(wrap);
      renderDevicesSection(container);
    });
  };

  let lan, devices, pairings, cert;
  try {
    const results = await Promise.all([
      fetchJson('/devices/lan'),
      fetchJson('/devices'),
      fetchJson('/devices/pairing'),
      fetchJson('/devices/cert'),
    ]);
    [lan, devices, pairings, cert] = results;
  } catch {
    renderUnreachable();
    return;
  }

  // Token expired/revoked on this device: the API says so in plain terms.
  const unauth = [lan, devices, pairings, cert].find((r) => r.status === 401);
  if (unauth) {
    const detail = unauth.data && unauth.data.detail;
    if (detail === 'device_revoked') {
      body.innerHTML = `<div class="devices-unreachable">
        <p>This device was revoked — pair again.</p>
        <p class="settings-hint">Open Settings → Devices on your laptop and start a new pairing, then scan the fresh code from this device.</p>
      </div>`;
      return;
    }
    if (detail === 'device_expired') {
      body.innerHTML = `<div class="devices-unreachable">
        <p>This device's access expired — pair again.</p>
        <p class="settings-hint">Device access lasts 90 days. Open Settings → Devices on your laptop and start a new pairing.</p>
      </div>`;
      return;
    }
  }
  if (!lan.ok && !devices.ok) {
    renderUnreachable();
    return;
  }

  const lanData = lan.data || {};
  const ips = Array.isArray(lanData.ips) ? lanData.ips : [];
  const port = lanData.port || 8001;
  const lanEnabled = !!getSetting('LAN_ENABLED');
  const httpFallback = !!getSetting('LAN_ALLOW_HTTP');
  const fingerprint = cert.data && cert.data.fingerprint_sha256;

  const urlList = ips.length
    ? ips.map((ip) => `<li><code>http://${escapeHtml(ip)}:${port}</code></li>`).join('')
    : `<li class="settings-hint">No LAN address detected on this machine.</li>`;

  body.innerHTML = `
    ${window.location.protocol === 'http:' && !isLoopbackHost(window.location.hostname)
      ? `<div class="lan-banner">LAN connection is not encrypted — anyone on this Wi-Fi can read your traffic.</div>` : ''}
    <p class="settings-hint">The same Sangam UI on another device over Wi-Fi — no new account.
      Your laptop stays the host; the phone just talks to it.</p>
    <h4>Your LAN addresses</h4>
    <ul class="lan-url-list">${urlList}</ul>
    ${lanData.loaded_via_loopback
      ? `<p class="settings-hint devices-note">This page was loaded via localhost, so LAN reachability can't be confirmed from here.
         To let a phone connect, start the server with <code>--host 0.0.0.0</code> (today's default binds loopback only),
         then open one of the addresses above from the phone.</p>`
      : `<p class="settings-hint devices-note">This page was loaded over the network. If the phone can't reach these addresses,
         make sure the server was started with <code>--host 0.0.0.0</code>.</p>`}
    <p class="settings-hint devices-note">If the server runs behind a custom origin, set
      <code>SANGAM_EXTRA_ORIGINS</code> (comma-separated, e.g. <code>http://192.168.1.42:8001</code>)
      before starting it — that list is added to CORS and to the page's connect policy. CORS is never opened to *.
      Do not port-forward Sangam to the internet.</p>
    ${httpFallback
      ? `<div class="lan-banner">Unencrypted LAN fallback is ON — anyone on this Wi-Fi can read your traffic.
         Turn it off above (Allow unencrypted LAN) unless a phone browser rejects the certificate.</div>`
      : `<p class="settings-hint devices-note">HTTP fallback is off. Phones connect over TLS once the server is restarted with the certificate below.</p>`}
    <h4>Pair a new device</h4>
    ${lanEnabled
      ? `<div class="devices-pair-form">
          <input type="text" class="provider-key-input" data-pair-name placeholder="Device name (e.g. My phone)" aria-label="Device name">
          <button type="button" class="btn-secondary" data-devices-pair>Pair a new device</button>
        </div>
        <div data-pair-card></div>`
      : `<p class="settings-hint devices-note">Turn on “Allow devices on my Wi-Fi (LAN mode)” above to pair a device.
         Pairing still needs your approval here on the laptop — the code alone is never enough.</p>`}
    <h4>Pairings waiting for you <button type="button" class="btn-secondary btn-sm" data-pairings-refresh>Refresh</button></h4>
    <div data-pairings-list></div>
    <h4>Paired devices</h4>
    <div data-paired-list></div>
    <h4>Certificate (TLS)</h4>
    <div data-cert-block></div>
    <h4>If the laptop's address changes</h4>
    <p class="settings-hint devices-note">Wi-Fi addresses change when the router reassigns them (DHCP).
      If your phone stops reaching Sangam, just scan a fresh QR code here — the QR doubles as rediscovery.
      Automatic discovery (mDNS) is not in this version.</p>
    <p class="settings-hint devices-note">Changing your password does not revoke paired devices — use Revoke all below if you need that.</p>
    ${THREAT_HTML}`;

  const pairCard = body.querySelector('[data-pair-card]');
  const pairingsList = body.querySelector('[data-pairings-list]');
  const pairedList = body.querySelector('[data-paired-list]');
  const certBlock = body.querySelector('[data-cert-block]');

  function renderPairings(list) {
    const rows = (list || []).filter((p) => p.status === 'pending' || p.status === 'approved');
    if (!rows.length) {
      pairingsList.innerHTML = '<p class="settings-hint">No pairings waiting.</p>';
      return;
    }
    pairingsList.innerHTML = rows.map((p) => `
      <div class="device-row" data-pairing-row="${escapeHtml(p.pairing_id)}">
        <span><strong>${escapeHtml(p.device_name)}</strong>
          <span class="settings-hint">${p.code
            ? `code ${escapeHtml(p.code)}`
            // Restart-hydrated pairing: only the code hash survives, so
            // the digits are unrecoverable by design. Never render a
            // placeholder code (it looks like a hidden-but-real code);
            // approval works by pairing_id, so approve by device name.
            : 'code unavailable after restart — approve by device name'} · ${escapeHtml(p.status)} · expires ${escapeHtml(fmtTime(p.expires_at))}</span></span>
        <span>
          ${p.status === 'pending'
            ? `<button type="button" class="btn-secondary btn-sm" data-approve-pairing="${escapeHtml(p.pairing_id)}">Approve</button>
               <button type="button" class="btn-secondary btn-sm" data-deny-pairing="${escapeHtml(p.pairing_id)}">Deny</button>`
            : `<span class="settings-hint">Approved — waiting for the phone to claim it.</span>`}
        </span>
      </div>`).join('');
    pairingsList.querySelectorAll('[data-approve-pairing]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const resp = await apiPost(`/devices/pairing/${btn.dataset.approvePairing}/approve`, {}, false);
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || `Approve failed (${resp.status})`);
          showToast({ type: 'success', message: 'Pairing approved. The phone can now claim it.' });
          await refreshPairings();
        } catch (e) {
          showToast({ type: 'error', message: `Couldn't approve pairing: ${e.message || e}` });
        }
      });
    });
    pairingsList.querySelectorAll('[data-deny-pairing]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const resp = await apiPost(`/devices/pairing/${btn.dataset.denyPairing}/deny`, {}, false);
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || `Deny failed (${resp.status})`);
          showToast({ type: 'info', message: 'Pairing denied.' });
          await refreshPairings();
        } catch (e) {
          showToast({ type: 'error', message: `Couldn't deny pairing: ${e.message || e}` });
        }
      });
    });
  }

  async function refreshPairings() {
    try {
      const r = await fetchJson('/devices/pairing');
      if (r.ok) renderPairings(r.data.pairings || []);
    } catch { /* keep the last list; the next poll retries */ }
  }

  function renderPaired(list) {
    const rows = list || [];
    if (!rows.length) {
      pairedList.innerHTML = '<p class="settings-hint">No devices paired yet.</p>';
      return;
    }
    pairedList.innerHTML = rows.map((d) => `
      <div class="device-row" data-device-row="${escapeHtml(d.id)}">
        <span><strong>${escapeHtml(d.device_name)}</strong>
          <span class="settings-hint">paired ${escapeHtml(fmtTime(d.created_at))} · expires ${escapeHtml(fmtTime(d.expires_at))}
          · last used ${d.last_used_at ? escapeHtml(fmtTime(d.last_used_at)) : 'never'}${d.revoked ? ' · revoked' : ''}</span></span>
        ${d.revoked ? '' : `<button type="button" class="btn-secondary btn-sm sp-danger" data-revoke-device="${escapeHtml(d.id)}">Revoke</button>`}
      </div>`).join('')
      + `<p><button type="button" class="btn-secondary btn-sm sp-danger" data-revoke-all>Revoke all devices</button></p>`;
    pairedList.querySelectorAll('[data-revoke-device]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const resp = await apiDelete(`/devices/${btn.dataset.revokeDevice}`, false);
          if (!resp.ok) throw new Error(`Revoke failed (${resp.status})`);
          showToast({ type: 'success', message: 'Device revoked. Its token stops working immediately.' });
          const r = await fetchJson('/devices');
          if (r.ok) renderPaired(r.data.devices || []);
        } catch (e) {
          showToast({ type: 'error', message: `Couldn't revoke device: ${e.message || e}` });
        }
      });
    });
    const revokeAll = pairedList.querySelector('[data-revoke-all]');
    if (revokeAll) {
      revokeAll.addEventListener('click', () => {
        showDevicesConfirm({
          title: 'Revoke all devices?',
          message: 'Every phone must pair again.',
          confirmLabel: 'Revoke all',
          onConfirm: async () => {
            try {
              const resp = await apiPost('/devices/revoke-all', {}, false);
              const data = await resp.json();
              if (!resp.ok) throw new Error(data.detail || `Revoke all failed (${resp.status})`);
              showToast({ type: 'success', message: `Revoked ${data.revoked || 0} device(s).` });
              const r = await fetchJson('/devices');
              if (r.ok) renderPaired(r.data.devices || []);
            } catch (e) {
              showToast({ type: 'error', message: `Couldn't revoke devices: ${e.message || e}` });
            }
          },
        });
      });
    }
  }

  function renderCert(info) {
    if (info && info.exists && info.fingerprint_sha256) {
      certBlock.innerHTML = `<p>Certificate fingerprint (SHA-256):<br>
        <code class="cert-fingerprint">${escapeHtml(info.fingerprint_sha256)}</code></p>
        <p class="settings-hint">Created ${escapeHtml(fmtTime(info.created_at))}.
        On first connect, the phone browser will warn about the self-signed certificate — compare the fingerprint
        it shows with this one. Browsers do not let a web page pin a certificate automatically, so this manual
        comparison is the check. Generating a certificate does not switch the running server to TLS by itself:
        restart it with <code>--ssl-certfile mainfiles/config/lan-cert/cert.pem --ssl-keyfile mainfiles/config/lan-cert/key.pem</code>.</p>`;
    } else {
      certBlock.innerHTML = `<p class="settings-hint">No certificate yet. Generate one to enable TLS mode.</p>`;
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-secondary btn-sm';
    btn.textContent = info && info.exists ? 'Regenerate certificate' : 'Generate certificate';
    btn.addEventListener('click', () => {
      showDevicesConfirm({
        title: 'Regenerate certificate?',
        message: 'This invalidates ALL pairings: every device must pair again.',
        confirmLabel: 'Regenerate',
        onConfirm: async () => {
          try {
            const resp = await apiPost('/devices/cert/regenerate', {}, false);
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || `Regenerate failed (${resp.status})`);
            showToast({ type: 'success', message: data.warning || 'Certificate regenerated.' });
            renderCert(data);
            const r = await fetchJson('/devices');
            if (r.ok) renderPaired(r.data.devices || []);
            await refreshPairings();
          } catch (e) {
            showToast({ type: 'error', message: `Couldn't regenerate certificate: ${e.message || e}` });
          }
        },
      });
    });
    certBlock.appendChild(btn);
  }

  renderPairings(pairings.data ? pairings.data.pairings || [] : []);
  renderPaired(devices.data ? devices.data.devices || [] : []);
  renderCert(cert.data || null);

  body.querySelector('[data-pairings-refresh]').addEventListener('click', refreshPairings);

  const pairBtn = body.querySelector('[data-devices-pair]');
  if (pairBtn) {
    pairBtn.addEventListener('click', async () => {
      const nameInput = body.querySelector('[data-pair-name]');
      const deviceName = (nameInput && nameInput.value.trim()) || 'Phone';
      pairBtn.disabled = true;
      try {
        const resp = await apiPost('/devices/pairing/start', { device_name: deviceName }, false);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || `Pairing failed (${resp.status})`);
        const expiresAt = new Date(data.expires_at);
        pairCard.innerHTML = `
          <div class="pair-card">
            <div class="qr-wrap"><canvas data-qr-canvas width="220" height="220" aria-label="Pairing QR code"></canvas></div>
            <p class="settings-hint">Scan this QR code with the phone, or type the code on the phone:</p>
            <div class="pair-code" data-pair-code>${escapeHtml(data.code)}</div>
            <p class="settings-hint" data-pair-countdown>Code expires at ${escapeHtml(fmtTime(data.expires_at))}</p>
            <p class="settings-hint">LAN address: <code>${escapeHtml(data.lan_url)}</code></p>
            <p class="settings-hint">Certificate fingerprint: <code>${data.payload && JSON.parse(data.payload).fingerprint
              ? escapeHtml(JSON.parse(data.payload).fingerprint) : 'none yet — generate a certificate below'}</code></p>
            <p class="settings-hint">After the phone claims, approve it in “Pairings waiting for you” above — the code alone is never enough.
              The code is single-use and expires in 5 minutes.</p>
          </div>`;
        const canvas = pairCard.querySelector('[data-qr-canvas]');
        const countdownEl = pairCard.querySelector('[data-pair-countdown]');
        const ok = await ensureQrLibrary();
        if (ok && window.SangamQR) {
          const qr = window.SangamQR.drawToCanvas(canvas, data.payload, 4);
          if (!qr) {
            pairCard.querySelector('.qr-wrap').innerHTML = `<p class="settings-hint">QR couldn't render — type the code above instead.</p>
              <p><code>${escapeHtml(data.payload)}</code></p>`;
          }
        } else {
          pairCard.querySelector('.qr-wrap').innerHTML = `<p class="settings-hint">QR library couldn't load — type the code above instead.</p>
            <p><code>${escapeHtml(data.payload)}</code></p>`;
        }
        if (window.__sangamDevicesTimers.countdown) clearInterval(window.__sangamDevicesTimers.countdown);
        window.__sangamDevicesTimers.countdown = setInterval(() => {
          if (!countdownEl.isConnected) return;
          const left = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
          if (left <= 0) {
            countdownEl.textContent = 'Code expired — start a new pairing.';
          } else {
            countdownEl.textContent = `Code expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
          }
        }, 1000);
        await refreshPairings();
      } catch (e) {
        showToast({ type: 'error', message: `Couldn't start pairing: ${e.message || e}` });
      } finally {
        pairBtn.disabled = false;
      }
    });
  }

  // Poll pending pairings while this section is on screen.
  window.__sangamDevicesTimers.poll = setInterval(() => {
    if (!wrap.isConnected) {
      clearInterval(window.__sangamDevicesTimers.poll);
      return;
    }
    refreshPairings();
  }, 15000);
}
