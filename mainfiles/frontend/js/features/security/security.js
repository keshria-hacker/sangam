/**
 * Security section page for the Work hub — Batch 2 (security).
 *
 * Own-systems-only testing: runs need an allowlist entry first, are
 * created PENDING, and only execute after a separate approval. The
 * report button shows the validation gate error honestly (it lists
 * the findings that block the report) instead of hiding it.
 * Catalog entries are data only: nothing here installs or runs tools.
 */
import { apiDelete, apiGet, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] security.js loaded');

const PHASES = ['recon', 'vuln-hunter', 'validator', 'reporter'];

function errText(err) {
  if (err && err.detail && typeof err.detail === 'object') {
    const blocked = (err.detail.unvalidated || []).map((f) => f.title).join(', ');
    return `${err.detail.error || 'Report refused'}${blocked ? `: ${blocked}` : ''}`;
  }
  return (err && (err.detail || err.message)) || 'Request failed';
}

export async function renderSecurityPage(bodyEl) {
  bodyEl.innerHTML = `
    <section class="library" aria-labelledby="securityTitle">
      <h2 id="securityTitle">Security</h2>
      <p class="settings-hint" aria-label="Security steps">1 Allow &rarr; 2 Create &rarr; 3 Approve &rarr; 4 Report</p>
      <p class="settings-hint">Test only systems you own: add the target to the allowlist, create a run (it stays pending), then approve it. High-risk catalog tools are disabled by default and are data only — Sangam does not install or run them for you.</p>
      <h3>Allowlist</h3>
      <form id="secAllowForm">
        <label>Host pattern <input type="text" id="secAllowHost" placeholder="example.com or *.example.com" aria-label="Allowlist host pattern" required></label>
        <label>Note <input type="text" id="secAllowNote" placeholder="My own staging site" aria-label="Allowlist note"></label>
        <button type="submit" class="btn" aria-label="Add allowlist target">Add target</button>
      </form>
      <div id="secAllowList" role="region" aria-label="Allowlist targets"><p class="settings-hint">Loading…</p></div>
      <h3>Scope check</h3>
      <p class="settings-hint">Check a target against a scope file first. In scope still
      needs its own per-run approval; out of scope is rejected, not warned about.</p>
      <div class="kn-mem-controls">
        <input type="text" id="secScopeTarget" class="provider-key-input" placeholder="Target host, e.g. example.com" aria-label="Target host" style="flex:1">
        <input type="text" id="secScopeDomains" class="provider-key-input" placeholder="In-scope domains, comma-separated" aria-label="In-scope domains" style="flex:1">
        <button type="button" class="btn-secondary" id="secScopeBtn">Check scope</button>
      </div>
      <div id="secScopeOut" class="kn-mem-list"><p class="settings-hint">No scope checked yet.</p></div>
      <h3>Tool catalog (data only)</h3>
      <div id="secCatalog" role="region" aria-label="Security tool catalog"><p class="settings-hint">Loading…</p></div>
      <h3>New run</h3>
      <form id="secRunForm">
        <label>Target <input type="text" id="secRunTarget" placeholder="https://staging.example.com" aria-label="Run target" required></label>
        <label>Scope <input type="text" id="secRunScope" placeholder="Staging only, no production" aria-label="Run scope"></label>
        <label>Tool class
          <select id="secRunClass" aria-label="Tool class">
            <option value="recon">recon (passive only)</option>
            <option value="scan">scan (catalogued, not auto-run in v1)</option>
            <option value="browser-automation">browser-automation</option>
            <option value="browser-security-test">browser-security-test</option>
          </select>
        </label>
        <label><input type="checkbox" id="secBrowserAuto"> Approve browser automation for this run</label>
        <label><input type="checkbox" id="secBrowserSec"> Approve browser security-test for this run</label>
        <button type="submit" class="btn" aria-label="Create security run">Create run (pending)</button>
      </form>
      <h3>Runs</h3>
      <div id="secRuns" role="region" aria-label="Security runs"><p class="settings-hint">Loading…</p></div>
    </section>`;

  const allowEl = bodyEl.querySelector('#secAllowList');
  const catalogEl = bodyEl.querySelector('#secCatalog');
  const runsEl = bodyEl.querySelector('#secRuns');

  async function loadAllowlist() {
    try {
      const data = await (await apiGet('/security/allowlist')).json();
      allowEl.innerHTML = (data.targets || []).length ? `<ul>${data.targets.map((t) => `
        <li>${escapeHtml(t.host_pattern)}${t.note ? ` — ${escapeHtml(t.note)}` : ''}
        <button type="button" class="btn" data-del-allow="${escapeHtml(t.id)}" aria-label="Delete allowlist target ${escapeHtml(t.host_pattern)}">Delete</button></li>`).join('')}</ul>`
        : '<p class="settings-hint">No allowlist targets yet. Nothing can run until you add one.</p>';
      allowEl.querySelectorAll('[data-del-allow]').forEach((b) => b.addEventListener('click', async () => {
        await apiDelete(`/security/allowlist/${b.dataset.delAllow}`);
        showToast({ message: 'Allowlist target deleted' });
        await loadAllowlist();
      }));
    } catch (err) { allowEl.innerHTML = `<p class="settings-hint">${escapeHtml(errText(err))}</p>`; }
  }

  async function loadCatalog() {
    try {
      const data = await (await apiGet('/security/catalog')).json();
      catalogEl.innerHTML = `<ul>${(data.tools || []).map((t) => `
        <li><strong>${escapeHtml(t.name)}</strong> (${escapeHtml(t.category)}, risk ${escapeHtml(t.risk)})
        — ${escapeHtml(t.description)}
        <button type="button" class="btn" data-cat="${escapeHtml(t.name)}" data-enabled="${t.enabled ? 'false' : 'true'}" aria-label="${t.enabled ? 'Disable' : 'Enable'} ${escapeHtml(t.name)}">${t.enabled ? 'Disable' : 'Enable'}</button></li>`).join('')}</ul>
        <p class="settings-hint">Never offered here: ${(data.exclusions || []).join(', ')}.</p>`;
      catalogEl.querySelectorAll('[data-cat]').forEach((b) => b.addEventListener('click', async () => {
        await apiPost(`/security/catalog/${b.dataset.cat}/enable`, { enabled: b.dataset.enabled === 'true' });
        await loadCatalog();
      }));
    } catch (err) { catalogEl.innerHTML = `<p class="settings-hint">${escapeHtml(errText(err))}</p>`; }
  }

  async function loadRuns() {
    try {
      const data = await (await apiGet('/security/runs')).json();
      if (!(data.runs || []).length) {
        runsEl.innerHTML = '<p class="settings-hint">No security runs yet.</p>';
        return;
      }
      runsEl.innerHTML = await Promise.all(data.runs.map(async (r) => {
        let findingsHtml = '';
        try {
          const f = await (await apiGet(`/security/runs/${r.id}/findings`)).json();
          findingsHtml = (f.findings || []).map((x) => `
            <li>${escapeHtml(x.title)} [${escapeHtml(x.severity)}] — ${escapeHtml(x.status)}${x.validation_verdict ? ` (${escapeHtml(x.validation_verdict)})` : ''}
            <button type="button" class="btn" data-validate="${escapeHtml(x.id)}" aria-label="Validate finding ${escapeHtml(x.title)} as PASS">Validate PASS</button></li>`).join('');
        } catch { findingsHtml = ''; }
        const next = PHASES[PHASES.indexOf(r.phase) + 1];
        return `<article>
          <h4>${escapeHtml(r.target)}</h4>
          <p>Status: ${escapeHtml(r.status)} · Phase: ${escapeHtml(r.phase)} · Tool: ${escapeHtml(r.tool_class)} · Isolation: ${escapeHtml(r.isolation || 'not run yet')}</p>
          ${r.isolation_warning ? `<p class="settings-hint"><strong>Isolation warning:</strong> ${escapeHtml(r.isolation_warning)}</p>` : ''}
          ${r.status === 'pending' ? `<button type="button" class="btn" data-approve="${escapeHtml(r.id)}" aria-label="Approve run for ${escapeHtml(r.target)}">Approve &amp; run</button>` : ''}
          ${next ? `<button type="button" class="btn" data-phase="${escapeHtml(r.id)}" data-next="${escapeHtml(next)}" aria-label="Advance to ${escapeHtml(next)}">Advance to ${escapeHtml(next)}</button>` : ''}
          <button type="button" class="btn" data-report="${escapeHtml(r.id)}" aria-label="Build report for ${escapeHtml(r.target)}">Build report</button>
          <ul>${findingsHtml}</ul>
          <div data-report-out="${escapeHtml(r.id)}" role="region" aria-label="Report output"></div>
        </article>`;
      })).then((parts) => parts.join(''));
      runsEl.querySelectorAll('[data-approve]').forEach((b) => b.addEventListener('click', async () => {
        try { await apiPost(`/security/runs/${b.dataset.approve}/approve`, {}); showToast({ message: 'Run approved and executed' }); }
        catch (err) { showToast({ type: 'error', message: errText(err) }); }
        await loadRuns();
      }));
      runsEl.querySelectorAll('[data-phase]').forEach((b) => b.addEventListener('click', async () => {
        try { await apiPost(`/security/runs/${b.dataset.phase}/phase`, { phase: b.dataset.next }); }
        catch (err) { showToast({ type: 'error', message: errText(err) }); }
        await loadRuns();
      }));
      runsEl.querySelectorAll('[data-report]').forEach((b) => b.addEventListener('click', async () => {
        const out = runsEl.querySelector(`[data-report-out="${b.dataset.report}"]`);
        try {
          const rep = await (await apiPost(`/security/runs/${b.dataset.report}/report`, {})).json();
          out.innerHTML = `<pre>${escapeHtml(rep.report_markdown || '')}</pre>`;
        } catch (err) { out.innerHTML = `<p class="settings-hint">${escapeHtml(errText(err))}</p>`; }
      }));
      runsEl.querySelectorAll('[data-validate]').forEach((b) => b.addEventListener('click', async () => {
        await apiPost(`/security/findings/${b.dataset.validate}/validate`, { verdict: 'PASS', notes: 'Validated from Security page' });
        await loadRuns();
      }));
    } catch (err) { runsEl.innerHTML = `<p class="settings-hint">${escapeHtml(errText(err))}</p>`; }
  }

  // Scope check, moved here from Dev & QA so Security is the single home
  // for security work (same endpoint, same wording, same approval note).
  bodyEl.querySelector('#secScopeBtn').addEventListener('click', async () => {
    const out = bodyEl.querySelector('#secScopeOut');
    const target = bodyEl.querySelector('#secScopeTarget').value.trim();
    const domains = bodyEl.querySelector('#secScopeDomains').value.split(',').map((s) => s.trim()).filter(Boolean);
    if (!target || !domains.length) { out.innerHTML = '<p class="settings-hint">Enter a target host and at least one in-scope domain.</p>'; return; }
    try {
      const data = await (await apiPost('/devqa/security/scope/check', { target, scope: { domains } })).json();
      out.innerHTML = data.allowed
        ? `<p class="settings-hint">In scope: ${escapeHtml(target)} matches the scope file. A run still needs its own per-run approval.</p>`
        : `<p class="settings-hint">OUT OF SCOPE: ${escapeHtml(target)} does not match the scope file. A run against it would be rejected, not warned about.</p>`;
    } catch (e) { out.innerHTML = `<p class="settings-hint">Scope check failed: ${escapeHtml(e?.message || 'unknown error')}</p>`; }
  });

  bodyEl.querySelector('#secAllowForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiPost('/security/allowlist', {
        host_pattern: bodyEl.querySelector('#secAllowHost').value,
        note: bodyEl.querySelector('#secAllowNote').value,
      });
      showToast({ message: 'Allowlist target added' });
    } catch (err) { showToast({ type: 'error', message: errText(err) }); }
    await loadAllowlist();
  });
  bodyEl.querySelector('#secRunForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiPost('/security/runs', {
        target: bodyEl.querySelector('#secRunTarget').value,
        scope: bodyEl.querySelector('#secRunScope').value,
        tool_class: bodyEl.querySelector('#secRunClass').value,
        browser_automation_approved: bodyEl.querySelector('#secBrowserAuto').checked,
        browser_security_approved: bodyEl.querySelector('#secBrowserSec').checked,
      });
      showToast({ message: 'Run created (pending — approve it to execute)' });
    } catch (err) { showToast({ type: 'error', message: errText(err) }); }
    await loadRuns();
  });

  await Promise.all([loadAllowlist(), loadCatalog(), loadRuns()]);
}
