/*
Design Philosophy: Apple Cinematic Minimalism.
This interaction layer favors calm, product-like flows: immediate feedback, concise result cards, algorithm transparency, and map interactions that clarify rather than decorate. Every UI update should support the course-design demonstration of data structures and algorithms.
*/
const state = {
  token: localStorage.getItem("travel_token") || "",
  user: null,
  destinations: [],
  currentMap: null,
  currentRoute: [],
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `请求失败：${res.status}`);
  return data;
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2600);
}

function fmt(num) {
  return Number(num || 0).toLocaleString("zh-CN");
}

function chips(tags = []) {
  return `<div class="chip-row">${tags.map((t) => `<span class="chip">${t}</span>`).join("")}</div>`;
}

function option(value, label) {
  return `<option value="${String(value).replaceAll('"', '&quot;')}">${label}</option>`;
}

async function init() {
  bindEvents();
  await Promise.all([loadHealth(), loadDestinations(), loadNotes(), loadRooms()]);
  if (state.token) await refreshMe();
  await loadFoods();
  await loadDiaries();
}

function bindEvents() {
  $("openLogin").addEventListener("click", () => $("loginDialog").showModal());
  $("loginBtn").addEventListener("click", login);
  $("registerBtn").addEventListener("click", register);
  $("loadDestinations").addEventListener("click", loadDestinations);
  $("plannerDestination").addEventListener("change", loadMap);
  $("planRoute").addEventListener("click", planRoute);
  $("findFacilities").addEventListener("click", findFacilities);
  $("loadFoods").addEventListener("click", loadFoods);
  $("loadDiaries").addEventListener("click", loadDiaries);
  $("createDiaryForm").addEventListener("submit", createDiary);
  $("planIndoor").addEventListener("click", planIndoor);
}

async function loadHealth() {
  const h = await api("/api/health");
  $("metrics").innerHTML = `
    <div class="metric"><strong>${fmt(h.destinations)}</strong><span>目的地元数据</span></div>
    <div class="metric"><strong>${fmt(h.diaries)}</strong><span>游记记录</span></div>
    <div class="metric"><strong>${fmt(h.foods)}</strong><span>美食条目</span></div>
    <div class="metric"><strong>${fmt(h.users)}</strong><span>用户账号</span></div>`;
}

async function loadDestinations() {
  const params = new URLSearchParams({
    q: $("destQuery").value,
    interests: $("interestInput").value,
    category: $("categorySelect").value,
    sort: $("destSort").value,
    hot_weight: $("hotWeight").value,
    rating_weight: $("ratingWeight").value,
    interest_weight: String(Math.max(0, 1 - Number($("hotWeight").value) - Number($("ratingWeight").value))),
    limit: "10",
  });
  const data = await api(`/api/destinations?${params}`);
  state.destinations = data.items;
  renderDestinations(data.items, data.algorithm);
  await ensureDestinationOptions();
}

async function ensureDestinationOptions() {
  if (!state.allDestinations) {
    const all = await api("/api/destinations?limit=100&sort=hot");
    state.allDestinations = all.items;
    const categories = [...new Set(all.items.map((d) => d.category))].sort();
    $("categorySelect").innerHTML = option("", "全部分类") + categories.map((c) => option(c, c)).join("");
  }
  const opts = state.allDestinations.map((d) => option(d.id, `${d.name} · ${d.category}`)).join("");
  $("plannerDestination").innerHTML = opts;
  $("newDiaryDestination").innerHTML = opts;
  if (!state.currentMap && state.allDestinations.length) await loadMap();
}

function renderDestinations(items, algorithm) {
  $("destinationCards").innerHTML = items.map((d) => `
    <article class="card">
      <div class="score"><span>${d.city} · ${d.category}</span><strong>推荐分 ${Number(d.recommend_score || 0).toFixed(3)}</strong></div>
      <h3>${d.name}</h3>
      <p>${d.description}</p>
      <div class="score"><span>评分 ${d.rating}</span><span>热度 ${fmt(d.views)}</span><span>${d.recommended_hours}h</span></div>
      ${chips(d.tags)}
      <button class="secondary-btn" onclick="selectDestination('${d.id}')">在地图中打开</button>
    </article>`).join("") + `<article class="card"><h3>算法说明</h3><p>${algorithm}</p><p>这里保留推荐权重输入，便于演示不同用户兴趣导致的 Top 10 结果变化。</p></article>`;
}

window.selectDestination = async function (id) {
  $("plannerDestination").value = id;
  location.hash = "planner";
  await loadMap();
};

async function loadMap() {
  const destId = $("plannerDestination").value || "dest_001";
  const data = await api(`/api/map/${destId}`);
  state.currentMap = data;
  state.currentRoute = [];
  const nodeOpts = data.nodes.map((n) => option(n.node_id, `${n.name} (${n.node_id})`)).join("");
  $("startNode").innerHTML = nodeOpts;
  $("waypointNode").innerHTML = option("", "不设置") + nodeOpts;
  $("endNode").innerHTML = nodeOpts;
  $("startNode").value = data.nodes[0]?.node_id || "";
  $("endNode").value = data.nodes[Math.min(80, data.nodes.length - 1)]?.node_id || "";
  drawMap();
}

function drawMap() {
  const svg = $("mapSvg");
  const data = state.currentMap;
  if (!data) return;
  const width = data.width || 1180;
  const height = data.height || 720;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const nodes = new Map(data.nodes.map((n) => [String(n.node_id), n]));
  const routePairs = new Set();
  for (let i = 0; i < state.currentRoute.length - 1; i++) {
    routePairs.add(`${state.currentRoute[i]}-${state.currentRoute[i + 1]}`);
    routePairs.add(`${state.currentRoute[i + 1]}-${state.currentRoute[i]}`);
  }
  const edges = data.edges.map((e) => {
    const a = nodes.get(String(e.source_id));
    const b = nodes.get(String(e.target_id));
    if (!a || !b) return "";
    const isRoute = routePairs.has(`${e.source_id}-${e.target_id}`);
    return `<line class="map-edge ${isRoute ? "route" : ""}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"></line>`;
  }).join("");
  const routeSet = new Set(state.currentRoute);
  const serviceTypes = new Set(["toilet", "supermarket", "restaurant_cn", "restaurant_we", "coffee", "shop", "canteen", "library"]);
  const nodeEls = data.nodes.map((n, idx) => {
    const active = routeSet.has(String(n.node_id));
    const service = serviceTypes.has(n.type);
    const label = idx % 8 === 0 || active ? `<text class="map-label" x="${n.x + 7}" y="${n.y - 8}">${n.name.slice(0, 7)}</text>` : "";
    return `<g onclick="chooseNode('${n.node_id}')"><circle class="map-node ${service ? "service" : ""} ${active ? "active" : ""}" cx="${n.x}" cy="${n.y}" r="${active ? 6 : service ? 5 : 3.8}"><title>${n.name} · ${n.type}</title></circle>${label}</g>`;
  }).join("");
  svg.innerHTML = `<rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>${edges}${nodeEls}`;
}

window.chooseNode = function (id) {
  if (!$("startNode").value) $("startNode").value = id;
  else $("endNode").value = id;
  toast(`已选择节点 ${id}，可作为终点或起点调整。`);
};

async function planRoute() {
  const body = {
    destination_id: $("plannerDestination").value,
    start_id: $("startNode").value,
    end_id: $("endNode").value,
    waypoints: $("waypointNode").value ? [$("waypointNode").value] : [],
    strategy: $("routeStrategy").value,
    transport: $("transportMode").value,
  };
  const data = await api("/api/route", { method: "POST", body: JSON.stringify(body) });
  if (!data.success) {
    $("routeResult").textContent = data.message || "规划失败";
    return;
  }
  state.currentRoute = data.path.map(String);
  drawMap();
  $("routeResult").innerHTML = `
    <strong>${data.algorithm}</strong><br>
    总距离：${data.distance_meters} 米；预计时间：${data.estimated_time_minutes} 分钟；访问节点：${data.visited_count} 个。
    <ol>${data.path_nodes.slice(0, 18).map((n) => `<li>${n.name} <span class="muted">${n.node_id}</span></li>`).join("")}</ol>
    ${data.path_nodes.length > 18 ? `<p>路径较长，已展示前 18 个节点。</p>` : ""}`;
}

async function findFacilities() {
  const params = new URLSearchParams({ node_id: $("startNode").value, type: $("facilityType").value, limit: "10" });
  const data = await api(`/api/facilities/${$("plannerDestination").value}?${params}`);
  $("routeResult").innerHTML = `<strong>${data.algorithm}</strong><br>${data.items.map((f) => `${f.name}：${f.path_distance_meters} 米`).join("<br>") || "附近暂无该类设施。"}`;
}

async function loadFoods() {
  const destId = $("plannerDestination")?.value || "";
  const params = new URLSearchParams({ destination_id: destId, q: $("foodQuery")?.value || "", sort: $("foodSort")?.value || "weighted", limit: "10" });
  const data = await api(`/api/foods?${params}`);
  $("foodList").innerHTML = data.items.map((f) => `
    <div class="list-item">
      <header><strong>${f.name}</strong><span class="chip">${f.cuisine}</span></header>
      <p>${f.restaurant} · ${f.destination_name} · ${f.distance_meters} 米 · 评分 ${f.rating} · 人均 ¥${f.price_per_person}</p>
      <p>${f.description}</p>
    </div>`).join("") || `<p class="muted">暂无匹配美食。</p>`;
}

async function loadDiaries() {
  const params = new URLSearchParams({ q: $("diaryQuery").value, title: $("diaryTitle").value, sort: $("diarySort").value });
  const data = await api(`/api/diaries?${params}`);
  $("diaryList").innerHTML = data.items.map((d) => `
    <article class="list-item">
      <header><strong>${d.title}</strong><span class="chip">${d.destination_name || "未绑定"}</span></header>
      <p>作者 ${d.author} · 浏览 ${fmt(d.views)} · 评分 ${d.rating || 0} · KMP命中 ${d.kmp_hits ?? "-"}</p>
      ${d.snippet ? `<p>${d.snippet}</p>` : ""}
      <div class="list-actions">
        <button class="mini-btn" onclick="showDiary('${d.id}')">阅读全文</button>
        <button class="mini-btn" onclick="compressDiary('${d.id}')">哈夫曼压缩</button>
        <button class="mini-btn" onclick="coverDiary('${d.id}')">生成封面提示</button>
        <button class="mini-btn" onclick="rateDiary('${d.id}', 5)">评 5 分</button>
      </div>
    </article>`).join("") || `<p class="muted">暂无匹配游记。</p>`;
}

window.showDiary = async function (id) {
  const d = await api(`/api/diaries/${id}`);
  $("diaryList").insertAdjacentHTML("afterbegin", `<article class="list-item"><header><strong>${d.title}</strong><span class="chip">正文</span></header><p>${d.content.replaceAll("\n", "<br>")}</p></article>`);
};

window.compressDiary = async function (id) {
  const d = await api(`/api/diaries/${id}/compress`, { method: "POST" });
  toast(`压缩完成：${d.zip_file}，节省率 ${d.saving_ratio}%`);
  $("diaryList").insertAdjacentHTML("afterbegin", `<article class="list-item"><strong>哈夫曼压缩结果</strong><p>原始 ${d.original_bytes} bytes，存储 ${d.stored_bytes} bytes，节省率 ${d.saving_ratio}%。码表样例：${d.tree_summary.slice(0, 8).map((x) => `${x.char}:${x.code}`).join("，")}</p></article>`);
};

window.coverDiary = async function (id) {
  const d = await api(`/api/diaries/${id}/cover`, { method: "POST" });
  toast("封面提示词已生成");
  $("diaryList").insertAdjacentHTML("afterbegin", `<article class="list-item"><header><strong>封面生成演示</strong><span class="chip">AIGC Prompt</span></header><p>${d.prompt}</p><img src="${d.cover_url}" alt="生成封面" style="border-radius:18px;max-height:260px;object-fit:cover"></article>`);
};

window.rateDiary = async function (id, score) {
  const d = await api(`/api/diaries/${id}/rate`, { method: "POST", body: JSON.stringify({ score }) });
  toast(`评分成功，当前均分 ${d.rating}`);
  await loadDiaries();
};

async function createDiary(event) {
  event.preventDefault();
  try {
    const body = { title: $("newDiaryTitle").value, destination_id: $("newDiaryDestination").value, content: $("newDiaryContent").value };
    await api("/api/diaries", { method: "POST", body: JSON.stringify(body) });
    toast("游记发布成功");
    $("newDiaryContent").value = "";
    await loadDiaries();
    await loadHealth();
  } catch (err) { toast(err.message); }
}

async function loadRooms() {
  try {
    const data = await api("/api/indoor/public_teaching_building/rooms");
    $("roomSelect").innerHTML = data.rooms.slice(0, 60).map((r) => option(r.id, `${r.name} · ${r.floor}楼`)).join("");
    $("indoorResult").textContent = `${data.building?.name || "公共教学楼"}已加载，可选择房间进行导航。`;
  } catch (err) {
    $("indoorResult").textContent = err.message;
  }
}

async function planIndoor() {
  const data = await api("/api/indoor/public_teaching_building/navigate", { method: "POST", body: JSON.stringify({ room_id: $("roomSelect").value }) });
  $("indoorResult").innerHTML = `<strong>${data.algorithm}</strong><br>目标：${data.destination?.name}；访问节点：${data.visited_count}；权重：${data.total_weight}<ol>${data.steps.map((s) => `<li>${s.description}（${s.distance}米）</li>`).join("")}</ol>`;
}

async function loadNotes() {
  const data = await api("/api/algorithm-notes");
  $("algorithmNotes").innerHTML = Object.entries(data).map(([k, v]) => `<article class="algorithm-card"><h3>${k}</h3><p>${v}</p></article>`).join("");
}

async function login() {
  try {
    const body = { username: $("authUsername").value, password: $("authPassword").value };
    const data = await api("/api/login", { method: "POST", body: JSON.stringify(body) });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem("travel_token", state.token);
    $("loginDialog").close();
    toast(`欢迎回来，${state.user.username}`);
    await renderProfile();
  } catch (err) { toast(err.message); }
}

async function register() {
  try {
    const body = {
      username: $("authUsername").value,
      password: $("authPassword").value,
      portrait: Number($("authPortrait").value || 1),
      interests: $("authInterests").value.split(",").map((x) => x.trim()).filter(Boolean),
    };
    const data = await api("/api/register", { method: "POST", body: JSON.stringify(body) });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem("travel_token", state.token);
    $("loginDialog").close();
    toast(`注册成功，${state.user.username}`);
    await renderProfile();
    await loadHealth();
  } catch (err) { toast(err.message); }
}

async function refreshMe() {
  try {
    state.user = await api("/api/me");
    await renderProfile();
  } catch (_) {
    state.token = "";
    localStorage.removeItem("travel_token");
    renderLoggedOut();
  }
}

async function renderProfile() {
  if (!state.user) return renderLoggedOut();
  $("openLogin").textContent = state.user.username;
  $("profilePanel").innerHTML = `
    <div style="display:flex;gap:18px;align-items:center;margin-bottom:18px"><img src="${state.user.portrait_url}" alt="头像" style="width:72px;height:72px;border-radius:50%;object-fit:cover"><div><h3>${state.user.username}</h3><p class="muted">角色：${state.user.role}</p></div></div>
    <label>头像编号<input id="profilePortrait" type="number" min="1" max="24" value="${state.user.portrait}"></label>
    <label>兴趣标签<input id="profileInterests" value="${(state.user.interests || []).join(",")}"></label>
    <button class="primary-btn" onclick="saveProfile()">保存资料</button>
    <button class="secondary-btn" onclick="logout()">退出登录</button>`;
  if (state.user.role === "admin") await loadAdminUsers();
  else $("adminPanel").innerHTML = "管理员登录后会显示用户管理列表。";
}

function renderLoggedOut() {
  $("openLogin").textContent = "登录 / 注册";
  $("profilePanel").textContent = "当前未登录。";
  $("adminPanel").textContent = "管理员登录后会显示用户管理列表。";
}

window.saveProfile = async function () {
  const data = await api("/api/me", { method: "PUT", body: JSON.stringify({ portrait: Number($("profilePortrait").value), interests: $("profileInterests").value.split(",").map((x) => x.trim()).filter(Boolean) }) });
  state.user = data;
  toast("资料已保存");
  await renderProfile();
};

window.logout = function () {
  state.token = "";
  state.user = null;
  localStorage.removeItem("travel_token");
  renderLoggedOut();
  toast("已退出登录");
};

async function loadAdminUsers() {
  const users = await api("/api/admin/users");
  $("adminPanel").innerHTML = `<h3>用户管理</h3><div class="list">${users.map((u) => `<div class="list-item"><header><strong>${u.username}</strong><span class="chip">${u.role}</span></header><p>兴趣：${(u.interests || []).join("、") || "未设置"}</p>${u.username !== "admin" ? `<button class="mini-btn" onclick="deleteUser('${u.username}')">删除用户</button>` : ""}</div>`).join("")}</div>`;
}

window.deleteUser = async function (username) {
  if (!confirm(`确定删除用户 ${username}？`)) return;
  await api(`/api/admin/users/${username}`, { method: "DELETE" });
  toast("用户已删除");
  await loadAdminUsers();
  await loadHealth();
};

window.addEventListener("error", (e) => toast(e.message || "页面出现错误"));
init().catch((err) => toast(err.message));
