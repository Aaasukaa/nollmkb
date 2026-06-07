// Base URL detection
const BASE = window.location.origin;

// Auth: check for stored token
function getToken() {
  const t = localStorage.getItem("nkb_token");
  if (!t) { window.location.href = "/ui/login.html"; return null; }
  return t;
}

// Auth: set headers
function authHeaders() {
  const t = getToken();
  return t ? { "Authorization": "Bearer " + t, "Content-Type": "application/json" }
           : { "Content-Type": "application/json" };
}

// Error mapping
const ERROR_MAP = {
  "unauthorized": "登录已过期，请重新登录",
  "topic cannot be empty": "标题不能留空",
  "topic contains illegal ..": "路径不合法",
  "topic not found": "笔记不存在",
  "requires topic and content fields": "标题和内容不能为空",
};

function mapError(err) {
  const msg = (typeof err === "string") ? err : (err.error || err.detail || "");
  return ERROR_MAP[msg] || "操作失败，请稍后重试";
}

// Status bar: fetch and render
let _statusTimer = null;
async function updateStatus() {
  const token = localStorage.getItem("nkb_token");
  if (!token) return;
  const hdrs = { "Authorization": "Bearer " + token };
  try {
    const r = await fetch(BASE + "/scan/status", { headers: hdrs });
    const s = await r.json();
    const el = document.getElementById("status-bar");
    if (!el) return;
    if (s.running) {
      el.textContent = `扫描中: ${s.current_file} [${s.current}/${s.total}]`;
    } else if (s.last_result) {
      el.textContent = `上次扫描: ${s.last_result}`;
    } else {
      const hr = await fetch(BASE + "/health", { headers: hdrs });
      const hd = await hr.json();
      el.textContent = `服务正常 | 已索引 ${hd.chunks} 段`;
    }
  } catch (e) {
    const el = document.getElementById("status-bar");
    if (el) el.textContent = "服务离线";
  }
}

function startStatusPolling() {
  updateStatus();
  _statusTimer = setInterval(updateStatus, 30000);
}
startStatusPolling();

// Nav: mark active page + login/logout toggle
document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  document.querySelectorAll("nav a").forEach(a => {
    if (a.dataset.page === page) a.classList.add("active");
  });
  const li = document.getElementById("nav-login");
  if (li) {
    if (localStorage.getItem("nkb_token")) {
      li.innerHTML = `<a href="#" onclick="localStorage.removeItem('nkb_token');localStorage.removeItem('nkb_user');location.href='/ui/login.html';return false">退出</a>`;
    } else {
      li.innerHTML = `<a href="/ui/login.html">登录</a>`;
    }
  }
});
