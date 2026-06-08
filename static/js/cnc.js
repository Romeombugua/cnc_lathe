/* ── CSRF helper ────────────────────────────────────────── */
function getCsrfToken() {
    const match = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
    return match ? match.trim().split('=')[1] : '';
}

/* ── JSON POST helper ───────────────────────────────────── */
async function postJson(url, data) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify(data),
    });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

/* ── Toast notification ─────────────────────────────────── */
function showToast(message, type) {
    type = type || 'info';
    const colors = {
        success: '#198754',
        danger:  '#dc3545',
        warning: '#fd7e14',
        info:    '#0dcaf0',
    };
    const container = document.getElementById('toast-container');
    if (!container) return;

    const div = document.createElement('div');
    div.className = 'toast-msg';
    div.style.background = colors[type] || colors.info;
    div.textContent = message;
    container.appendChild(div);

    requestAnimationFrame(() => { div.style.opacity = '1'; });
    setTimeout(function () {
        div.style.opacity = '0';
        setTimeout(function () { div.remove(); }, 320);
    }, 4000);
}

/* ── Machine status polling ─────────────────────────────── */
function updateMachineStatus() {
    fetch('/machine/status/')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            /* Navbar indicator */
            const dot   = document.getElementById('status-dot');
            const label = document.getElementById('status-label');
            if (dot)   dot.className   = 'status-dot ' + data.status;
            if (label) label.textContent =
                data.status.charAt(0).toUpperCase() + data.status.slice(1);

            /* Broadcast for pages that listen (includes grbl_state, mpos, wpos, etc.) */
            document.dispatchEvent(
                new CustomEvent('machine-status', { detail: data })
            );
        })
        .catch(function () { /* ignore network blips */ });
}

/* ── Emergency stop ─────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
    setInterval(updateMachineStatus, 2000);
    updateMachineStatus();

    const btn = document.getElementById('emergency-stop-btn');
    if (!btn) return;

    btn.addEventListener('click', function () {
        btn.disabled = true;
        postJson('/serial/emergency-stop/', {})
            .then(function (data) {
                showToast(data.message || 'Emergency stop activated', 'danger');
            })
            .catch(function () {
                showToast('Emergency stop signal sent', 'danger');
            })
            .finally(function () {
                setTimeout(function () { btn.disabled = false; }, 4000);
            });
    });
});
