/**
 * XiaoMusic 控制台 —— 原生 ES module，无框架、无 jQuery。
 *
 * 设计要点（性能优先）：
 *  - 单一 API 客户端，全部走统一的 /api/** 路径；
 *  - 不做全量重渲染：列表按需分批渲染，长列表用 content-visibility 跳过视口外元素；
 *  - 轮询自适应：仅在播放中且标签页可见时轮询，页藏即停；
 *  - 设置页由接口返回的配置自动生成表单，只提交被改动过的键。
 */

/* ------------------------------------------------------------------ *
 * API 客户端
 * ------------------------------------------------------------------ */

const api = {
  async request(method, path, { body, query } = {}) {
    let url = path;
    if (query) {
      const qs = new URLSearchParams(
        Object.entries(query).filter(([, v]) => v !== undefined && v !== null)
      ).toString();
      if (qs) url += `?${qs}`;
    }
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(url, init);
    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!res.ok) {
      const detail = (data && (data.detail || data.error)) || res.status;
      throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    return data;
  },
  get: (path, query) => api.request("GET", path, { query }),
  post: (path, body) => api.request("POST", path, { body }),
};

const EP = {
  deviceList: "/api/device/list",
  status: "/api/device/status",
  volume: "/api/device/volume",
  cmd: "/api/device/cmd",
  stop: "/api/device/stop",
  playing: "/api/music/playing",
  musicList: "/api/music/list",
  musicSearch: "/api/music/search",
  playMusic: "/api/music/play",
  playlistNames: "/api/playlist/names",
  playlistMusics: "/api/playlist/musics",
  playlistPlay: "/api/playlist/play",
  playlistAdd: "/api/playlist/add",
  playlistDelete: "/api/playlist/delete",
  playlistRename: "/api/playlist/rename",
  playlistAddMusic: "/api/playlist/music/add",
  playlistDelMusic: "/api/playlist/music/delete",
  setting: "/api/system/setting",
  settingSave: "/api/system/modifiysetting",
  version: "/api/system/version",
  qrcode: "/api/get_qrcode",
};

/* ------------------------------------------------------------------ *
 * 小工具
 * ------------------------------------------------------------------ */

const $ = (id) => document.getElementById(id);

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("is-show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("is-show"), 2200);
}

function fmtTime(sec) {
  sec = Math.max(0, Math.floor(Number(sec) || 0));
  const m = Math.floor(sec / 60);
  return `${m}:${String(sec % 60).padStart(2, "0")}`;
}

/** 建任务元素的小工具，避免到处写 innerHTML 拼接（也更安全）。 */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ------------------------------------------------------------------ *
 * 状态
 * ------------------------------------------------------------------ */

const state = {
  view: "now",
  did: "",
  devices: [],
  playing: { is_playing: false, cur_music: "", cur_playlist: "", offset: 0, duration: 0 },
  musicList: {},
  libList: "",
  playlists: [],
  settings: null,
  dirty: new Map(),
  timers: { poll: null },
};

const PAGE_SIZE = 200;

/* ------------------------------------------------------------------ *
 * 设备
 * ------------------------------------------------------------------ */

function normalizeDevices(raw) {
  const list = Array.isArray(raw) ? raw : (raw && raw.devices) || [];
  return list
    .map((d) => ({
      did: String(d.miotDID || d.did || d.deviceID || ""),
      name: d.name || d.alias || d.deviceID || "未知设备",
      hardware: d.hardware || "",
    }))
    .filter((d) => d.did);
}

/** 只负责拉取并渲染设备下拉；事件绑定放在 setupDeviceSelect（只绑一次）。 */
async function loadDevices(quiet = false) {
  try {
    const raw = await api.get(EP.deviceList);
    state.devices = normalizeDevices(raw);
  } catch (err) {
    state.devices = [];
    if (!quiet) toast(`设备列表获取失败：${err.message}`);
  }

  const cached = localStorage.getItem("xm_did") || "";
  const known = state.devices.some((d) => d.did === cached);
  state.did = known ? cached : state.devices[0]?.did || "web_device";

  const sel = $("device-select");
  sel.replaceChildren();
  if (!state.devices.length) {
    sel.append(el("option", null, "无设备（未登录？）"));
    sel.disabled = true;
  } else {
    sel.disabled = false;
    for (const d of state.devices) {
      const opt = el("option", null, d.hardware ? `${d.name} (${d.hardware})` : d.name);
      opt.value = d.did;
      sel.append(opt);
    }
    sel.value = state.did;
  }
  return state.devices;
}

function setupDeviceSelect() {
  $("device-select").addEventListener("change", (e) => {
    state.did = e.target.value;
    localStorage.setItem("xm_did", state.did);
    refreshVolume();
    poll(true);
  });
}

/* ------------------------------------------------------------------ *
 * 播放状态
 * ------------------------------------------------------------------ */

function renderPlaying() {
  const p = state.playing;
  const title = p.cur_music || "未在播放";
  $("now-title").textContent = title;
  $("bar-title").textContent = title;
  $("now-sub").textContent = p.cur_playlist ? `歌单：${p.cur_playlist}` : "—";
  $("now-cover").classList.toggle("is-playing", !!p.is_playing);

  const total = Number(p.duration) || 0;
  const pos = Math.min(Number(p.offset) || 0, total);
  const pct = total > 0 ? (pos / total) * 100 : 0;
  $("progress-bar").style.width = `${pct}%`;
  $("bar-progress").style.width = `${pct}%`;
  $("pos-text").textContent = fmtTime(pos);
  $("dur-text").textContent = total ? fmtTime(total) : "0:00";
}

async function poll(force = false) {
  if (!force && (document.hidden || !state.playing.is_playing)) return;
  try {
    const data = await api.get(EP.playing, { did: state.did });
    if (data && typeof data === "object") {
      state.playing = {
        is_playing: !!data.is_playing,
        cur_music: data.cur_music || "",
        cur_playlist: data.cur_playlist || "",
        offset: data.offset || 0,
        duration: data.duration || 0,
      };
      renderPlaying();
    }
  } catch {
    /* 轮询失败静默，下个周期再试 */
  }
  schedulePoll();
}

/** 播放中 2s 轮询；空闲时放宽到 10s，省 CPU。 */
function schedulePoll() {
  clearTimeout(state.timers.poll);
  const delay = state.playing.is_playing ? 2000 : 10000;
  state.timers.poll = setTimeout(() => poll(), delay);
}

/* ------------------------------------------------------------------ *
 * 音量
 * ------------------------------------------------------------------ */

async function refreshVolume() {
  try {
    const data = await api.get(EP.volume, { did: state.did });
    const vol = Number((data && data.volume) || 0);
    $("volume").value = vol;
    $("vol-value").textContent = vol;
    $("vol-icon").textContent = vol === 0 ? "🔇" : vol < 40 ? "🔉" : "🔊";
  } catch {
    /* 忽略 */
  }
}

let volumeTimer = null;
function setupVolume() {
  const slider = $("volume");
  slider.addEventListener("input", () => {
    $("vol-value").textContent = slider.value;
  });
  // 拖动时只在停止 180ms 后发一次请求，避免刷爆接口
  slider.addEventListener("change", () => {
    clearTimeout(volumeTimer);
    const vol = Number(slider.value);
    volumeTimer = setTimeout(async () => {
      try {
        await api.post(EP.volume, { did: state.did, volume: vol });
        refreshVolume();
      } catch (err) {
        toast(`设置音量失败：${err.message}`);
      }
    }, 180);
  });
  $("vol-icon").addEventListener("click", async () => {
    const next = Number($("volume").value) > 0 ? 0 : 40;
    $("volume").value = next;
    await api.post(EP.volume, { did: state.did, volume: next }).catch(() => {});
    refreshVolume();
  });
}

/* ------------------------------------------------------------------ *
 * 播放控制
 * ------------------------------------------------------------------ */

async function sendCmd(cmd) {
  try {
    await api.post(EP.cmd, { did: state.did, cmd });
    // 口令是异步执行的，稍等再拉一次状态
    setTimeout(() => poll(true), 800);
  } catch (err) {
    toast(`指令失败：${err.message}`);
  }
}

function setupTransport() {
  for (const btn of document.querySelectorAll("[data-cmd]")) {
    btn.addEventListener("click", () => sendCmd(btn.dataset.cmd));
  }
  $("btn-toggle").addEventListener("click", () => {
    sendCmd(state.playing.is_playing ? "暂停播放" : "继续播放");
  });
  $("cmd-send").addEventListener("click", () => {
    const input = $("cmd-input");
    const value = input.value.trim();
    if (!value) return;
    input.value = "";
    sendCmd(value);
  });
  $("cmd-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("cmd-send").click();
  });
}

/* ------------------------------------------------------------------ *
 * 音乐库
 * ------------------------------------------------------------------ */

function renderList(ul, items, { onPlay, onDelete, current }) {
  ul.replaceChildren();
  const frag = document.createDocumentFragment();
  for (const item of items) {
    const li = el("li");
    if (current && item === current) li.classList.add("is-current");
    const title = el("span", "title", item);
    title.addEventListener("click", () => onPlay(item));
    li.append(title);
    if (onDelete) {
      const del = el("button", "mini", "移除");
      del.addEventListener("click", () => onDelete(item));
      li.append(del);
    }
    frag.append(li);
  }
  ul.append(frag);
}

async function loadLibrary() {
  try {
    const data = await api.get(EP.musicList);
    state.musicList = data && typeof data === "object" ? data : {};
  } catch (err) {
    state.musicList = {};
    toast(`音乐列表获取失败：${err.message}`);
  }

  const names = Object.keys(state.musicList);
  const sel = $("lib-list-select");
  sel.replaceChildren();
  for (const name of names) {
    const opt = el("option", null, `${name} (${state.musicList[name].length})`);
    opt.value = name;
    sel.append(opt);
  }
  state.libList = names.includes("全部") ? "全部" : names[0] || "";
  sel.value = state.libList;
  renderLibrary();
}

let libShown = PAGE_SIZE;

function renderLibrary() {
  const all = state.musicList[state.libList] || [];
  const kw = $("lib-filter").value.trim().toLowerCase();
  const filtered = kw ? all.filter((n) => n.toLowerCase().includes(kw)) : all;

  renderList($("lib-items"), filtered.slice(0, libShown), {
    onPlay: (name) => playFromList(state.libList, name),
    current: state.playing.cur_music,
  });

  $("lib-count").textContent = `${filtered.length} 首`;
  $("lib-more").hidden = filtered.length <= libShown;
}

async function playFromList(listname, musicname) {
  try {
    await api.post(EP.playlistPlay, { did: state.did, listname, musicname });
    toast(`已下发：${musicname}`);
    setTimeout(() => poll(true), 900);
  } catch (err) {
    toast(`播放失败：${err.message}`);
  }
}

function setupLibrary() {
  $("lib-list-select").addEventListener("change", (e) => {
    state.libList = e.target.value;
    libShown = PAGE_SIZE;
    renderLibrary();
  });
  let t = null;
  $("lib-filter").addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      libShown = PAGE_SIZE;
      renderLibrary();
    }, 150);
  });
  $("lib-more").addEventListener("click", () => {
    libShown += PAGE_SIZE;
    renderLibrary();
  });
}

/* ------------------------------------------------------------------ *
 * 歌单
 * ------------------------------------------------------------------ */

async function loadPlaylists(keepSelection = false) {
  const prev = state.playlistCurrent;
  try {
    const data = await api.get(EP.playlistNames);
    state.playlists = (data && data.names) || [];
  } catch (err) {
    state.playlists = [];
    toast(`歌单获取失败：${err.message}`);
  }

  const sel = $("pl-select");
  sel.replaceChildren();
  for (const name of state.playlists) {
    const opt = el("option", null, name);
    opt.value = name;
    sel.append(opt);
  }
  state.playlistCurrent =
    keepSelection && state.playlists.includes(prev)
      ? prev
      : state.playlists[0] || "";
  sel.value = state.playlistCurrent;
  renderPlaylist();
}

async function renderPlaylist() {
  const name = state.playlistCurrent;
  if (!name) {
    $("pl-items").replaceChildren();
    return;
  }
  let songs = [];
  try {
    const data = await api.get(EP.playlistMusics, { name });
    songs = (data && (data.musics || data.music_list || data.list)) || [];
    if (!Array.isArray(songs)) songs = [];
  } catch (err) {
    toast(`歌单内容获取失败：${err.message}`);
  }
  renderList($("pl-items"), songs.slice(0, libShown), {
    onPlay: (song) => playFromList(name, song),
    onDelete: async (song) => {
      await api
        .post(EP.playlistDelMusic, { name, music_list: [song] })
        .then(() => {
          toast(`已移除：${song}`);
          renderPlaylist();
        })
        .catch((err) => toast(`移除失败：${err.message}`));
    },
    current: state.playing.cur_music,
  });
  $("pl-more").hidden = songs.length <= libShown;
}

function setupPlaylists() {
  $("pl-select").addEventListener("change", (e) => {
    state.playlistCurrent = e.target.value;
    libShown = PAGE_SIZE;
    renderPlaylist();
  });
  $("pl-add").addEventListener("click", async () => {
    const name = $("pl-new-name").value.trim();
    if (!name) return toast("请输入歌单名称");
    try {
      await api.post(EP.playlistAdd, { name });
      $("pl-new-name").value = "";
      toast(`已创建：${name}`);
      await loadPlaylists();
      state.playlistCurrent = name;
      $("pl-select").value = name;
      renderPlaylist();
    } catch (err) {
      toast(`创建失败：${err.message}`);
    }
  });
  $("pl-del").addEventListener("click", async () => {
    const name = state.playlistCurrent;
    if (!name) return;
    if (!confirm(`确定删除歌单「${name}」？`)) return;
    try {
      await api.post(EP.playlistDelete, { name });
      toast(`已删除：${name}`);
      await loadPlaylists();
    } catch (err) {
      toast(`删除失败：${err.message}`);
    }
  });
  $("pl-rename").addEventListener("click", async () => {
    const oldname = state.playlistCurrent;
    if (!oldname) return;
    const newname = prompt("新名称", oldname);
    if (!newname || newname === oldname) return;
    try {
      await api.post(EP.playlistRename, { oldname, newname });
      toast("已重命名");
      await loadPlaylists();
    } catch (err) {
      toast(`重命名失败：${err.message}`);
    }
  });
  $("pl-more").addEventListener("click", () => {
    libShown += PAGE_SIZE;
    renderPlaylist();
  });
}

/* ------------------------------------------------------------------ *
 * 登录（扫码）
 * ------------------------------------------------------------------ */

// 扫码后由服务端在后台轮询登录结果并写入 conf/auth.json（主登录链路
// auth.py 正是从这个文件取 passToken），前端只需展示二维码 + 倒计时，
// 用户确认后重试拉一次设备列表即可判断是否生效。
const QR_FALLBACK_EXPIRE = 120;

let qrCountdown = null;

function stopQrCountdown() {
  clearInterval(qrCountdown);
  qrCountdown = null;
}

function setQrStatus(text) {
  $("qr-status").textContent = text;
}

function showQrImage(url) {
  const img = $("qr-image");
  const holder = $("qr-placeholder");
  if (url) {
    img.src = url;
    img.hidden = false;
    holder.hidden = true;
  } else {
    img.removeAttribute("src");
    img.hidden = true;
    holder.hidden = false;
  }
}

function startQrCountdown(seconds) {
  stopQrCountdown();
  let remain = Number(seconds) > 0 ? Number(seconds) : QR_FALLBACK_EXPIRE;
  const tick = () => {
    if (remain <= 0) {
      stopQrCountdown();
      showQrImage("");
      $("qr-placeholder").textContent = "二维码已过期，请重新获取";
      setQrStatus("二维码已过期");
      return;
    }
    setQrStatus(`请用米家 App 扫码，二维码 ${remain} 秒后过期`);
    remain -= 1;
  };
  tick();
  qrCountdown = setInterval(tick, 1000);
}

async function fetchQrcode() {
  stopQrCountdown();
  showQrImage("");
  $("qr-placeholder").textContent = "正在生成二维码…";
  setQrStatus("");
  try {
    const data = await api.get(EP.qrcode);
    if (!data || data.success === false) {
      $("qr-placeholder").textContent = "二维码生成失败";
      setQrStatus((data && data.message) || "请稍后重试");
      return;
    }
    if (data.already_logged_in) {
      $("qr-placeholder").textContent = "已登录，无需扫码";
      setQrStatus(data.message || "已登录");
      await loadDevices(true);
      renderLogin();
      return;
    }
    showQrImage(data.qrcode_url);
    startQrCountdown(data.expire_seconds);
  } catch (err) {
    $("qr-placeholder").textContent = "二维码生成失败";
    setQrStatus(err.message);
  }
}

/** 用户点「我已完成扫码」：重试拉设备列表，拿到设备即视为登录生效。 */
async function recheckLogin(attempts = 5) {
  for (let i = 0; i < attempts; i += 1) {
    setQrStatus(`正在确认登录…（${i + 1}/${attempts}）`);
    await loadDevices(true);
    if (state.devices.length) {
      stopQrCountdown();
      showQrImage("");
      $("qr-placeholder").textContent = "登录成功";
      setQrStatus("");
      renderLogin();
      toast(`登录成功，已发现 ${state.devices.length} 台设备`);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  setQrStatus("仍未检测到设备：请确认手机上已点确认，或稍后再点一次。");
}

function renderLogin() {
  const count = state.devices.length;
  $("login-state").textContent = count
    ? `已登录，发现 ${count} 台设备`
    : "未检测到设备：请扫码登录，或检查账号与网络";
  const ul = $("login-devices");
  ul.replaceChildren();
  const frag = document.createDocumentFragment();
  for (const d of state.devices) {
    const li = el("li");
    li.append(el("span", "title", d.name));
    li.append(el("span", "meta", d.hardware || ""));
    frag.append(li);
  }
  ul.append(frag);
}

async function loadLogin() {
  renderLogin();
  if (!state.devices.length) {
    await loadDevices(true);
    renderLogin();
  }
}

function setupLogin() {
  $("qr-fetch").addEventListener("click", fetchQrcode);
  $("qr-recheck").addEventListener("click", () => recheckLogin());
}

/* ------------------------------------------------------------------ *
 * 设置
 * ------------------------------------------------------------------ */

// 这些不进表单：回显是脱敏值或体积过大，提交回去会破坏配置
const NEVER_SUBMIT = new Set([
  "account", "device_list", "devices", "device_id_did", "cookie",
  "key_word_dict", "key_match_order", "user_key_word_dict",
  "music_list_json", "custom_play_list_json", "music_list_url",
  "crontab_json", "enable_config_example",
]);
// 脱敏字段：未修改时不提交
const SENSITIVE = new Set(["password", "httpauth_password", "ha_token"]);

const GROUP_LABELS = [
  [/^ha_|^enable_ha/, "Home Assistant"],
  [/^(cast_|dlna_port|enable_cast)/, "投送 (DLNA / AirPlay)"],
  [/^(music_path|download_path|temp_path|conf_path|cache_|exclude_|ignore_|music_path_depth|recently_)/, "目录与缓存"],
  [/^(keywords_|key_|play_type_|stop_tts|search_prompt|fuzzy_|enable_fuzzy|enable_multi|multi_result)/, "语音口令"],
  [/^(edge_tts|tts_)/, "语音合成"],
  [/^(hostname|port|public_port|disable_httpauth|httpauth_)/, "网络与鉴权"],
  [/^(proxy|loudnorm|ffmpeg|get_duration|convert_|remove_id3|enable_save_tag|auto_convert)/, "转码与网络代理"],
  [/^(enable_auto_disconnect|auto_disconnect)/, "播完断开"],
];

function groupOf(key) {
  for (const [re, label] of GROUP_LABELS) if (re.test(key)) return label;
  return "其它";
}

function isSimple(value) {
  return (
    typeof value === "boolean" ||
    typeof value === "number" ||
    typeof value === "string"
  );
}

async function loadSettings() {
  const box = $("setting-form");
  box.replaceChildren(el("p", "hint", "加载中…"));
  try {
    const data = await api.get(EP.setting);
    state.settings = data && typeof data === "object" ? data : {};
  } catch (err) {
    state.settings = {};
    box.replaceChildren(el("p", "hint", `设置加载失败：${err.message}`));
    return;
  }
  state.dirty.clear();
  renderSettings();
}

function renderSettings() {
  const box = $("setting-form");
  box.replaceChildren();
  const kw = $("setting-filter").value.trim().toLowerCase();

  let shown = 0;
  for (const group of new Set(Object.keys(state.settings).map(groupOf))) {
    const entries = Object.entries(state.settings).filter(
      ([k, v]) =>
        groupOf(k) === group &&
        !NEVER_SUBMIT.has(k) &&
        isSimple(v) &&
        String(v).length <= 200 &&
        (!kw || k.toLowerCase().includes(kw))
    );
    if (!entries.length) continue;

    const fieldset = el("div", "fieldset");
    fieldset.append(el("h3", null, group));

    // Home Assistant 组：语音正则规则不在配置表单里，给一个直达编辑页的按钮
    if (group === "Home Assistant") {
      const link = el(
        "a",
        "btn",
        "编辑语音规则（正则表达式）→"
      );
      link.href = "/static/ha.html";
      link.target = "_blank";
      link.rel = "noopener";
      const note = el(
        "p",
        "hint",
        "正则规则（你说的话 → HA 动作 + 回话）保存在 conf/ha_rules.json，" +
          "在规则编辑页里可视化增删改，保存后 5 秒内自动生效。"
      );
      fieldset.append(link, note);
    }

    for (const [key, value] of entries) {
      fieldset.append(buildField(key, value));
      shown += 1;
    }
    box.append(fieldset);
  }
  $("setting-count").textContent = `显示 ${shown} 项`;
}

function buildField(key, value) {
  const row = el("div", "field");
  row.dataset.key = key;

  const label = el("label", null, key);
  label.htmlFor = `set-${key}`;
  row.append(label);

  const control = el("div", "control");
  let input;

  if (typeof value === "boolean") {
    input = el("input");
    input.type = "checkbox";
    input.checked = value;
    input.addEventListener("change", () => markDirty(key, input.checked, row));
  } else if (SENSITIVE.has(key)) {
    input = el("input");
    input.type = "password";
    input.placeholder = "******（不修改）";
    input.value = "";
    input.addEventListener("input", () => {
      if (input.value === "") {
        state.dirty.delete(key);
        row.classList.remove("is-dirty");
      } else {
        markDirty(key, input.value, row);
      }
    });
  } else if (typeof value === "number") {
    input = el("input");
    input.type = "number";
    input.value = value;
    input.addEventListener("change", () => markDirty(key, Number(input.value), row));
  } else {
    input = el("input");
    input.type = "text";
    input.value = value;
    input.addEventListener("change", () => markDirty(key, input.value, row));
  }

  input.id = `set-${key}`;
  control.append(input);
  row.append(control);
  return row;
}

function markDirty(key, value, row) {
  if (value === state.settings[key]) {
    state.dirty.delete(key);
    row.classList.remove("is-dirty");
  } else {
    state.dirty.set(key, value);
    row.classList.add("is-dirty");
  }
}

async function saveSettings() {
  if (!state.dirty.size) return toast("没有改动");
  const payload = Object.fromEntries(state.dirty);
  try {
    await api.post(EP.settingSave, payload);
    toast(`已保存 ${Object.keys(payload).length} 项`);
    await loadSettings();
  } catch (err) {
    toast(`保存失败：${err.message}`);
  }
}

function setupSettings() {
  $("setting-save").addEventListener("click", saveSettings);
  $("setting-reload").addEventListener("click", loadSettings);
  let t = null;
  $("setting-filter").addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(renderSettings, 150);
  });
}

/* ------------------------------------------------------------------ *
 * 视图切换 / 主题 / 启动
 * ------------------------------------------------------------------ */

const VIEW_INIT = {
  library: () => loadLibrary(),
  playlist: () => loadPlaylists(true),
  login: () => loadLogin(),
  setting: () => (state.settings ? renderSettings() : loadSettings()),
};

function switchView(view) {
  state.view = view;
  // 离开登录页就停掉二维码倒计时，别让它在后台跑
  if (view !== "login") stopQrCountdown();
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("is-active", tab.dataset.view === view);
  }
  for (const section of document.querySelectorAll(".view")) {
    section.classList.toggle("is-active", section.id === `view-${view}`);
  }
  location.hash = view;
  VIEW_INIT[view]?.();
}

function setupTheme() {
  const saved = localStorage.getItem("xm_theme");
  if (saved) document.documentElement.dataset.theme = saved;
  $("theme-toggle").addEventListener("click", () => {
    const cur =
      document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("xm_theme", next);
  });
}

async function showVersion() {
  try {
    const data = await api.get(EP.version);
    if (data?.version) document.title = `XiaoMusic ${data.version}`;
  } catch {
    /* 忽略 */
  }
}

async function main() {
  setupTheme();
  setupTransport();
  setupVolume();
  setupDeviceSelect();
  setupLibrary();
  setupPlaylists();
  setupLogin();
  setupSettings();

  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  }

  // 标签页切回来时立刻补一次状态，并继续轮询
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      poll(true);
      refreshVolume();
    }
  });

  await loadDevices(true);
  await Promise.all([refreshVolume(), poll(true)]);
  await showVersion();

  // 一台设备都没发现，多半是没登录 —— 直接把人带到登录页
  const initial = (location.hash || "").replace("#", "");
  if (!state.devices.length && !initial) {
    switchView("login");
    return;
  }
  switchView(initial || "now");
}

main();
