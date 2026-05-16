const state = {
  albums: [],
  token: localStorage.getItem("picmeToken") || "",
  currentUser: null,
  authMode: "login",
  currentAlbumId: "",
  currentFolderId: "",
  uploading: false,
  pollTimer: 0,
  lastUpload: null,
  touchStart: null,
  uploadExpanded: false,
  allPhotosOpen: false,
  myPhotosOpen: false,
  allPhotosLimit: 12,
  photoGridColumns: 3,
  photoGridZoomScale: 1,
  photoGridPinch: null,
  selectionMode: false,
  selectedPhotoIds: [],
  selectionScope: "",
  viewerToken: 0,
  viewerPhotoId: "",
  viewerPhotos: [],
  viewerIndex: -1,
  viewerTouchStart: null,
};

const $ = (selector) => document.querySelector(selector);
const AUTH_TOKEN_KEY = "picmeToken";
let avatarPreviewUrl = "";

const authView = $("#authView");
const appShell = $("#appShell");
const loginPanel = $('[data-auth-panel="login"]');
const registerPanel = $('[data-auth-panel="register"]');
const loginForm = $("#loginForm");
const loginUsername = $("#loginUsername");
const loginPassword = $("#loginPassword");
const loginButton = $("#loginButton");
const loginStatus = $("#loginStatus");
const showRegister = $("#showRegister");
const showLogin = $("#showLogin");
const registerToLogin = $("#registerToLogin");
const registerForm = $("#registerForm");
const registerAvatar = $("#registerAvatar");
const avatarPreview = $("#avatarPreview");
const registerNickname = $("#registerNickname");
const registerUsername = $("#registerUsername");
const registerPassword = $("#registerPassword");
const registerPasswordConfirm = $("#registerPasswordConfirm");
const registerButton = $("#registerButton");
const registerStatus = $("#registerStatus");
const albumForm = $("#albumForm");
const albumName = $("#albumName");
const openCreateAlbum = $("#openCreateAlbum");
const createAlbumDialog = $("#createAlbumDialog");
const cancelCreateAlbum = $("#cancelCreateAlbum");
const albumList = $("#albumList");
const sidebar = $(".sidebar");
const albumContextName = $("#albumContextName");
const backToHomeButton = $("#backToHome");
const subalbumAlbumName = $("#subalbumAlbumName");
const mobileBackToFolders = $("#mobileBackToFolders");
const topbar = $(".topbar");
const currentAlbumTitle = $("#currentAlbumTitle");
const stats = $("#stats");
const emptyState = $("#emptyState");
const homeAlbums = $("#homeAlbums");
const albumPanel = $("#albumPanel");
const myPhotosPanel = $("#myPhotosPanel");
const uploadForm = $("#uploadForm");
const toggleUploadForm = $("#toggleUploadForm");
const photosInput = $("#photos");
const selectedFiles = $("#selectedFiles");
const uploadStatus = $("#uploadStatus");
const allPhotos = $("#allPhotos");
const folders = $("#folders");
const folderDetail = $("#folderDetail");
const photoViewer = $("#photoViewer");
const viewerImage = $("#viewerImage");
const viewerVideo = $("#viewerVideo");
const viewerMeta = $("#viewerMeta");
const viewerDownload = $("#viewerDownload");
const viewerDelete = $("#viewerDelete");
const viewerFilmstrip = $("#viewerFilmstrip");
const viewerLivePlay = $("#viewerLivePlay");
const closeViewer = $("#closeViewer");

function pathPart(value) {
  return encodeURIComponent(value);
}

function authHeaders(extra = {}) {
  return state.token ? { ...extra, Authorization: `Bearer ${state.token}` } : extra;
}

function setAuthSession(payload) {
  state.token = payload.token || "";
  state.currentUser = payload.user || null;
  if (state.token) {
    localStorage.setItem(AUTH_TOKEN_KEY, state.token);
  }
  applyCurrentUserDefaults();
}

function clearAuthSession() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  state.token = "";
  state.currentUser = null;
  state.albums = [];
  state.currentAlbumId = "";
  state.currentFolderId = "";
  state.allPhotosOpen = false;
  state.myPhotosOpen = false;
  state.uploadExpanded = false;
  state.authMode = "login";
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = 0;
  }
  renderAuth();
}

function applyCurrentUserDefaults() {
  if (!state.currentUser || !$("#uploader")) return;
  const nickname = state.currentUser.nickname || state.currentUser.username || "";
  if (nickname && !$("#uploader").value.trim()) {
    $("#uploader").value = nickname;
  }
}

function renderAuth() {
  const loggedIn = Boolean(state.token && state.currentUser);
  authView.classList.toggle("hidden", loggedIn);
  appShell.classList.toggle("hidden", !loggedIn);
  openCreateAlbum.classList.toggle("hidden", !loggedIn || Boolean(state.currentAlbumId));
  loginPanel.classList.toggle("hidden", state.authMode !== "login");
  registerPanel.classList.toggle("hidden", state.authMode !== "register");
  if (!loggedIn) {
    emptyState.classList.add("hidden");
    homeAlbums.classList.add("hidden");
    albumPanel.classList.add("hidden");
  }
}

async function api(path, options = {}) {
  const headers = authHeaders(options.headers || {});
  const requestOptions = { ...options, headers };
  if (requestOptions.body instanceof FormData && requestOptions.headers["Content-Type"]) {
    delete requestOptions.headers["Content-Type"];
  }
  const response = await fetch(path, requestOptions);
  if (response.status === 401) {
    clearAuthSession();
    throw new Error("登录已过期，请重新登录");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return response.json();
}

async function authApi(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return response.json();
}

function requiresAlbumAuth(url) {
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.origin === window.location.origin && parsed.pathname.startsWith("/api/albums");
  } catch {
    return false;
  }
}

async function downloadWithAuth(url, fallbackName) {
  const response = await fetch(url, { headers: authHeaders() });
  if (response.status === 401) {
    clearAuthSession();
    throw new Error("登录已过期，请重新登录");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `下载失败：${response.status}`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fallbackName || "";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1200);
}

function formatDate(seconds) {
  return new Date(seconds * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function loadAlbums() {
  const payload = await api("/api/albums");
  state.albums = payload.albums;
  applyCurrentUserDefaults();
  render();
}

async function loadCurrentUser() {
  if (!state.token) return false;
  try {
    const payload = await api("/api/me");
    state.currentUser = payload.user;
    applyCurrentUserDefaults();
    renderAuth();
    return true;
  } catch (error) {
    return false;
  }
}

function validateRegisterForm() {
  const username = registerUsername.value.trim();
  const nickname = registerNickname.value.trim();
  const password = registerPassword.value;
  const passwordConfirm = registerPasswordConfirm.value;
  if (!nickname) return "请填写昵称";
  if (!/^[A-Za-z0-9_]{5,20}$/.test(username)) return "登录账号需要 5-20 位字母、数字或下划线";
  if (password.length < 6 || password.length > 20) return "密码需要 6-20 位";
  if (password !== passwordConfirm) return "两次输入的密码不一致";
  return "";
}

async function login(event) {
  event.preventDefault();
  loginStatus.textContent = "";
  loginButton.disabled = true;
  try {
    const payload = await authApi("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: loginUsername.value.trim(),
        password: loginPassword.value,
      }),
    });
    setAuthSession(payload);
    renderAuth();
    await loadAlbums();
  } catch (error) {
    loginStatus.textContent = error.message;
  } finally {
    loginButton.disabled = false;
  }
}

async function register(event) {
  event.preventDefault();
  registerStatus.textContent = "";
  const validationError = validateRegisterForm();
  if (validationError) {
    registerStatus.textContent = validationError;
    return;
  }

  const form = new FormData();
  form.append("username", registerUsername.value.trim());
  form.append("nickname", registerNickname.value.trim());
  form.append("password", registerPassword.value);
  if (registerAvatar.files && registerAvatar.files[0]) {
    form.append("avatar", registerAvatar.files[0]);
  }

  registerButton.disabled = true;
  try {
    const payload = await authApi("/api/auth/register", {
      method: "POST",
      body: form,
    });
    setAuthSession(payload);
    if (payload.warning) {
      uploadStatus.textContent = payload.warning;
    }
    renderAuth();
    await loadAlbums();
  } catch (error) {
    registerStatus.textContent = error.message;
  } finally {
    registerButton.disabled = false;
  }
}

async function refreshCurrentAlbum() {
  if (!state.currentAlbumId) return;
  const payload = await api(`/api/albums/${pathPart(state.currentAlbumId)}`);
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  render();
}

function getCurrentAlbum() {
  return state.albums.find((album) => album.id === state.currentAlbumId);
}

function photoFolderIds(photo) {
  return Array.isArray(photo.folderIds) && photo.folderIds.length ? photo.folderIds : photo.folderId ? [photo.folderId] : [];
}

function photoFolderNames(photo) {
  return Array.isArray(photo.folderNames) && photo.folderNames.length ? photo.folderNames : photo.folderName ? [photo.folderName] : [];
}

function photoInFolder(photo, folderId) {
  return photoFolderIds(photo).includes(folderId);
}

function defaultSelectedFilesText() {
  return "手机上可以一次多选；上传后先入库，再在后台生成预览和人物小相册";
}

function albumProcessingCounts(album, photos = album.photos) {
  const queued = photos.filter((photo) => photo.status === "queued").length;
  const preparing = photos.filter((photo) => photo.status === "preparing").length;
  const processing = photos.filter((photo) => photo.status === "processing").length;
  const failed = photos.filter((photo) => photo.status === "failed").length;
  return { queued, preparing, processing, failed, active: queued + preparing + processing };
}

function photoStatusText(photo) {
  if (photo.status === "queued") return "等待识别";
  if (photo.status === "preparing") return "生成预览图";
  if (photo.status === "processing") return "识别中";
  if (photo.status === "failed") return "识别失败";
  return "";
}

function uploadBatchPhotos(album) {
  if (!album || !state.lastUpload || state.lastUpload.albumId !== album.id) return [];
  const ids = new Set(state.lastUpload.photoIds);
  return album.photos.filter((photo) => ids.has(photo.id));
}

function photoResultSummary(photos, prefix = "这次上传已整理好") {
  if (!photos.length) return "";
  const readyPhotos = photos.filter((photo) => !photoStatusText(photo));
  if (!readyPhotos.length) return "";
  const personPhotoIds = new Set();
  let groupCount = 0;
  let otherCount = 0;
  readyPhotos.forEach((photo) => {
    const ids = photoFolderIds(photo);
    if (ids.includes("group-photo")) groupCount += 1;
    if (ids.includes("no-face")) otherCount += 1;
    if (ids.some((id) => id && id !== "group-photo" && id !== "no-face" && id !== "pending")) {
      personPhotoIds.add(photo.id);
    }
  });
  return `${prefix}：人物照片 ${personPhotoIds.size} 张，合照 ${groupCount} 张，其他 ${otherCount} 张`;
}

function updateUploadProgress(album) {
  if (state.uploading || !album) return;
  const batchPhotos = uploadBatchPhotos(album);
  const targetPhotos = batchPhotos.length ? batchPhotos : album.photos;
  const counts = albumProcessingCounts(album, targetPhotos);
  if (counts.active) {
    const prefix = batchPhotos.length ? "这次上传正在整理" : "照片池正在开工";
    uploadStatus.textContent = `${prefix}：${counts.preparing} 张做预览，${counts.processing} 张认人，${counts.queued} 张排队`;
  } else if (counts.failed) {
    const summary = photoResultSummary(targetPhotos);
    uploadStatus.textContent = `${summary || "基本整理好了"}，有 ${counts.failed} 张需要稍后手动看一眼`;
  } else if (batchPhotos.length) {
    uploadStatus.textContent = photoResultSummary(batchPhotos);
  } else {
    uploadStatus.textContent = "";
  }
}

function updatePolling(album) {
  const shouldPoll = album && albumProcessingCounts(album).active > 0;
  if (shouldPoll && !state.pollTimer) {
    state.pollTimer = window.setInterval(() => {
      refreshCurrentAlbum().catch((error) => {
        uploadStatus.textContent = error.message;
      });
    }, 1600);
  }
  if (!shouldPoll && state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = 0;
  }
}

function folderDisplayName(folder) {
  return folder.id === "no-face" || folder.name === "未识别人脸" ? "其他" : folder.name;
}

function photoDisplayFolderNames(photo) {
  return photoFolderIds(photo).map((folderId, index) => {
    const name = photoFolderNames(photo)[index] || "";
    return folderId === "no-face" || name === "未识别人脸" ? "其他" : name;
  });
}

function sortedFolders(album) {
  return [...album.folders].sort((a, b) => {
    if (a.id === "no-face" && b.id !== "no-face") return 1;
    if (b.id === "no-face" && a.id !== "no-face") return -1;
    if (a.id === "group-photo" && b.id !== "group-photo") return -1;
    if (b.id === "group-photo" && a.id !== "group-photo") return 1;
    return (a.createdAt || 0) - (b.createdAt || 0);
  });
}

function pickFolderCoverPhoto(folder, photos) {
  if (folder.coverPhotoId) {
    return photos.find((photo) => photo.id === folder.coverPhotoId) || photos[0];
  }
  if (folder.id === "group-photo" || folder.id === "no-face") {
    return photos[0];
  }
  return photos.find((photo) => photoFolderIds(photo).length === 1) || photos[0];
}

function folderCoverUrl(folder, photo) {
  if (folder.coverUrl) return folder.coverUrl;
  if (!photo) return "";
  if (folder.id === "group-photo" || folder.id === "no-face") {
    return photo.coverUrl || photo.cardUrl || photo.url;
  }
  return photo.faceUrl || photo.coverUrl || photo.cardUrl || photo.url;
}

function photoPreviewSrc(photo) {
  const name = (photo.storedName || photo.originalName || "").toLowerCase();
  if (photo.type === "live_photo" || name.endsWith(".heic") || name.endsWith(".heif")) {
    return photo.previewUrl || photo.cardUrl || photo.coverUrl || photo.url;
  }
  return photo.cardUrl || photo.coverUrl || photo.url;
}

function photoViewerSrc(photo) {
  const name = (photo.storedName || photo.originalName || "").toLowerCase();
  if (photo.type === "live_photo" || name.endsWith(".heic") || name.endsWith(".heif")) {
    return photo.previewUrl || photo.coverUrl || photo.cardUrl || photo.url;
  }
  return photo.url || photo.coverUrl || photo.cardUrl;
}

function renderPhotoMedia(photo, imageClass = "") {
  const isLive = photo.type === "live_photo" && photo.videoUrl;
  return `
    <span class="photo-media ${isLive ? "live-photo-media" : ""}">
      <img class="${imageClass}" src="${photoPreviewSrc(photo)}" alt="${escapeHtml(photo.originalName)}" loading="eager" decoding="async" />
      ${
        isLive
          ? `
            <video class="live-photo-video" src="${escapeHtml(photo.videoUrl)}" muted playsinline preload="metadata"></video>
            <button class="live-photo-badge" type="button" aria-label="播放 Live Photo">Live</button>
          `
          : ""
      }
    </span>
  `;
}

function renderDownloadActions(photo) {
  return `
    <a class="secondary image-download" href="${escapeHtml(photoDownloadUrl(photo))}" aria-label="${
      photo.type === "live_photo" ? "下载完整 Live Photo" : "下载静态图"
    }">↓</a>
  `;
}

function photoDownloadUrl(photo) {
  return photo.type === "live_photo" && photo.downloadLiveUrl ? photo.downloadLiveUrl : photo.downloadImageUrl || photo.url;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function touchDistance(touches) {
  const dx = touches[0].clientX - touches[1].clientX;
  const dy = touches[0].clientY - touches[1].clientY;
  return Math.hypot(dx, dy);
}

function photoGridMetrics(grid, scale = state.photoGridZoomScale) {
  const width = grid.clientWidth || grid.getBoundingClientRect().width || window.innerWidth;
  const spacing = Number(grid.dataset.spacing || 1);
  const baseColumns = clamp(state.photoGridColumns || 3, 2, 6);
  const clampedScale = clamp(scale || 1, 0.5, 1.75);
  const baseTileSide = (width - (baseColumns - 1) * spacing) / baseColumns;
  const rawTileSide = Math.max(48, baseTileSide * clampedScale);
  const displayColumns = clamp(Math.round((width + spacing) / (rawTileSide + spacing)), 2, 6);
  const tileSide = Math.min(width, rawTileSide);
  return { width, spacing, displayColumns, tileSide };
}

function layoutPhotoGrid(grid, scale = state.photoGridZoomScale) {
  if (!grid) return;
  const tiles = Array.from(grid.querySelectorAll(".photo-library-tile"));
  const { spacing, displayColumns, tileSide } = photoGridMetrics(grid, scale);
  const rows = Math.ceil(tiles.length / displayColumns);
  grid.style.height = `${rows * tileSide + Math.max(0, rows - 1) * spacing}px`;
  grid.dataset.displayColumns = String(displayColumns);
  grid.classList.toggle("compact-grid", displayColumns >= 5);
  tiles.forEach((tile, index) => {
    const row = Math.floor(index / displayColumns);
    const column = index % displayColumns;
    tile.style.width = `${tileSide}px`;
    tile.style.height = `${tileSide}px`;
    tile.style.transform = `translate3d(${column * (tileSide + spacing)}px, ${row * (tileSide + spacing)}px, 0)`;
  });
}

function layoutPhotoGrids() {
  document.querySelectorAll(".photo-library-grid").forEach((grid) => layoutPhotoGrid(grid));
}

function resetPhotoSelection() {
  state.selectionMode = false;
  state.selectedPhotoIds = [];
  state.selectionScope = "";
}

function selectionScopeFor(album, mode) {
  return `${album.id}:${mode}:${mode === "detail" ? state.currentFolderId : "all"}`;
}

function selectedPhotoSet() {
  return new Set(state.selectedPhotoIds);
}

function selectedPhotosFrom(photos) {
  const selected = selectedPhotoSet();
  return photos.filter((photo) => selected.has(photo.id));
}

function isCurrentSelectionScope(scope) {
  return state.selectionMode && state.selectionScope === scope;
}

function toggleSelection(scope, photoId) {
  if (!isCurrentSelectionScope(scope)) {
    state.selectionMode = true;
    state.selectionScope = scope;
    state.selectedPhotoIds = [];
  }
  if (state.selectedPhotoIds.includes(photoId)) {
    state.selectedPhotoIds = state.selectedPhotoIds.filter((id) => id !== photoId);
  } else {
    state.selectedPhotoIds = [...state.selectedPhotoIds, photoId];
  }
}

function renderSelectionHeader(photos, scope) {
  const active = isCurrentSelectionScope(scope);
  const allSelected = active && photos.length > 0 && photos.every((photo) => state.selectedPhotoIds.includes(photo.id));
  return `
    <div class="icloud-selection-toolbar">
      <button class="secondary select-all-photos" type="button"${active ? "" : " disabled"}>${allSelected ? "取消全选" : "全选"}</button>
      <button class="secondary toggle-selection-mode" type="button">${active ? "取消" : "选择"}</button>
    </div>
  `;
}

function renderSelectionBar(photos, scope, canMove) {
  if (!isCurrentSelectionScope(scope)) return "";
  const count = selectedPhotosFrom(photos).length;
  return `
    <div class="icloud-selection-bar">
      <strong>已选择 ${count} 项</strong>
      <div class="selection-actions">
        <button class="secondary danger delete-selected" type="button" ${count ? "" : "disabled"} aria-label="删除所选">⌫</button>
        <button class="secondary more-selected" type="button" ${count ? "" : "disabled"} aria-label="更多操作">•••</button>
      </div>
      <div class="selection-sheet hidden">
        <button class="download-selected" type="button">下载 ${count} 个项目</button>
        ${canMove ? `<button class="move-selected" type="button">移动到...</button>` : ""}
        <button class="danger delete-selected" type="button">删除 ${count} 个项目</button>
      </div>
    </div>
  `;
}

function renderPhotoGrid(container, photos, options = {}) {
  const {
    album,
    photoMoveTargets = [],
    mode = "detail",
    allPhotos = photos,
  } = options;
  const articleClass = mode === "all" ? "album-photo-card" : "detail-photo-card";
  const buttonClass = mode === "all" ? "album-photo" : "detail-photo";
  const scope = selectionScopeFor(album, mode);
  const activeSelection = isCurrentSelectionScope(scope);
  const selectedIds = selectedPhotoSet();
  container.innerHTML = `
    ${renderSelectionHeader(photos, scope)}
    <div class="photo-library-grid" data-spacing="1">
      ${photos
        .map(
          (photo) => `
            <article class="photo-library-tile ${articleClass} ${photoMoveTargets.length ? "has-move" : ""} ${
              photo.type === "live_photo" ? "live-photo-card" : ""
            } ${activeSelection ? "selection-mode" : ""} ${selectedIds.has(photo.id) ? "is-selected" : ""}">
              <button class="${buttonClass} photo-library-button" type="button" data-photo-id="${escapeHtml(photo.id)}">
                ${renderPhotoMedia(photo)}
                <span class="photo-selection-check" aria-hidden="true">✓</span>
              </button>
            </article>
          `,
        )
        .join("")}
    </div>
    ${renderSelectionBar(photos, scope, Boolean(photoMoveTargets.length))}
  `;

  const grid = container.querySelector(".photo-library-grid");
  layoutPhotoGrid(grid);
  bindPhotoGridZoom(grid);
  bindPhotoGridActions(container, album, photos, allPhotos, Boolean(photoMoveTargets.length), scope);
  bindLivePhotoPlayback(container);
}

function bindPhotoGridActions(container, album, photos, viewerPhotos, canMove, scope) {
  container.querySelectorAll(".photo-library-button").forEach((button) => {
    button.addEventListener("click", () => {
      const photo = photos.find((item) => item.id === button.dataset.photoId);
      if (!photo) return;
      if (isCurrentSelectionScope(scope)) {
        toggleSelection(scope, photo.id);
        render();
      } else {
        openPhotoViewer(photo, viewerPhotos);
      }
    });
  });

  if (canMove) {
    container.querySelectorAll(".move-photo").forEach((button) => {
      button.addEventListener("click", () => {
        movePhotoToFolder(album.id, button.dataset.photoId).catch((error) => alert(error.message));
      });
    });
  }

  container.querySelectorAll(".delete-photo").forEach((button) => {
    button.addEventListener("click", () => {
      deletePhoto(album.id, button.dataset.photoId).catch((error) => alert(error.message));
    });
  });

  const toggleSelectionButton = container.querySelector(".toggle-selection-mode");
  if (toggleSelectionButton) {
    toggleSelectionButton.addEventListener("click", () => {
      if (isCurrentSelectionScope(scope)) {
        resetPhotoSelection();
      } else {
        state.selectionMode = true;
        state.selectionScope = scope;
        state.selectedPhotoIds = [];
      }
      render();
    });
  }

  const selectAllButton = container.querySelector(".select-all-photos");
  if (selectAllButton) {
    selectAllButton.addEventListener("click", () => {
      const allIds = photos.map((photo) => photo.id);
      const allSelected = allIds.every((id) => state.selectedPhotoIds.includes(id));
      state.selectedPhotoIds = allSelected ? [] : allIds;
      render();
    });
  }

  container.querySelectorAll(".more-selected").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const sheet = container.querySelector(".selection-sheet");
      if (sheet) sheet.classList.toggle("hidden");
    });
  });

  container.querySelectorAll(".download-selected").forEach((button) => {
    button.addEventListener("click", () => {
      downloadSelectedPhotos(album.id, selectedPhotosFrom(photos)).catch((error) => alert(error.message));
    });
  });

  container.querySelectorAll(".delete-selected").forEach((button) => {
    button.addEventListener("click", () => {
      deleteSelectedPhotos(album.id, selectedPhotosFrom(photos)).catch((error) => alert(error.message));
    });
  });

  container.querySelectorAll(".move-selected").forEach((button) => {
    button.addEventListener("click", () => {
      moveSelectedPhotos(album, selectedPhotosFrom(photos)).catch((error) => alert(error.message));
    });
  });

  container.onclick = (event) => {
    if (event.target.closest(".selection-sheet")) return;
    const sheet = container.querySelector(".selection-sheet");
    if (sheet) sheet.classList.add("hidden");
  };
}

function bindPhotoGridZoom(grid) {
  if (!grid || grid.dataset.zoomBound === "true") return;
  grid.dataset.zoomBound = "true";

  grid.addEventListener(
    "touchstart",
    (event) => {
      if (event.touches.length !== 2) return;
      state.touchStart = null;
      state.photoGridPinch = {
        grid,
        startDistance: touchDistance(event.touches),
        startScale: state.photoGridZoomScale || 1,
      };
      grid.classList.add("is-pinching");
      event.preventDefault();
    },
    { passive: false },
  );

  grid.addEventListener(
    "touchmove",
    (event) => {
      if (!state.photoGridPinch || state.photoGridPinch.grid !== grid || event.touches.length !== 2) return;
      const nextScale = clamp((state.photoGridPinch.startScale * touchDistance(event.touches)) / state.photoGridPinch.startDistance, 0.5, 1.75);
      state.photoGridZoomScale = nextScale;
      layoutPhotoGrids();
      event.preventDefault();
    },
    { passive: false },
  );

  grid.addEventListener(
    "touchend",
    (event) => {
      if (!state.photoGridPinch || state.photoGridPinch.grid !== grid || event.touches.length >= 2) return;
      const targetColumns = clamp(Math.round(state.photoGridColumns / state.photoGridZoomScale), 2, 6);
      state.photoGridColumns = targetColumns;
      state.photoGridZoomScale = 1;
      state.photoGridPinch = null;
      grid.classList.remove("is-pinching");
      layoutPhotoGrids();
      event.preventDefault();
    },
    { passive: false },
  );

  grid.addEventListener(
    "touchcancel",
    () => {
      if (!state.photoGridPinch || state.photoGridPinch.grid !== grid) return;
      state.photoGridZoomScale = 1;
      state.photoGridPinch = null;
      grid.classList.remove("is-pinching");
      layoutPhotoGrids();
    },
    { passive: true },
  );
}

function backToFolderList() {
  if (!state.currentFolderId) return;
  resetPhotoSelection();
  state.currentFolderId = "";
  state.allPhotosOpen = false;
  state.myPhotosOpen = false;
  render();
}

function returnToHome() {
  resetPhotoSelection();
  state.currentAlbumId = "";
  state.currentFolderId = "";
  state.allPhotosOpen = false;
  state.myPhotosOpen = false;
  state.uploadExpanded = false;
  render();
}

function renderPrimaryAlbumNav() {
  albumList.innerHTML = "";
  if (!state.currentAlbumId || !state.currentFolderId) {
    albumList.classList.add("hidden");
    return;
  }
}

function renderHomeAlbums() {
  homeAlbums.innerHTML = "";
  if (!state.albums.length) {
    homeAlbums.classList.add("hidden");
    emptyState.classList.remove("hidden");
    return;
  }

  emptyState.classList.add("hidden");
  homeAlbums.classList.remove("hidden");
  homeAlbums.insertAdjacentHTML("beforeend", `<div class="section-heading"><h3>相册</h3><p>${state.albums.length} 个一级相册</p></div>`);
  state.albums.forEach((album) => {
    const folderPreviews = sortedFolders(album)
      .map((folder) => {
        const folderPhotos = album.photos.filter((photo) => photoInFolder(photo, folder.id)).sort((a, b) => b.createdAt - a.createdAt);
        const coverPhoto = pickFolderCoverPhoto(folder, folderPhotos);
        return { folder, photo: coverPhoto, coverUrl: folderCoverUrl(folder, coverPhoto) };
      })
      .filter((item) => item.coverUrl)
      .slice(0, 8);
    const card = document.createElement("section");
    card.className = "home-album-card";
    card.innerHTML = `
      <button class="home-album-open" type="button" aria-label="进入 ${escapeHtml(album.name)}">
        <span class="home-album-faces ${folderPreviews.length ? "" : "empty-cover"}">
          ${
            folderPreviews.length
              ? folderPreviews
                  .map(
                    ({ folder, coverUrl }) => `
                      <span class="home-face">
                        <img src="${coverUrl}" alt="${escapeHtml(folderDisplayName(folder))}" loading="lazy" decoding="async" />
                        <small>${escapeHtml(folderDisplayName(folder))}</small>
                      </span>
                    `,
                  )
                  .join("")
              : "<i>暂无子相册</i>"
          }
        </span>
        <span class="home-album-meta">
          <strong>${escapeHtml(album.name)}</strong>
          <small>${album.photos.length} 张朋友视角 · ${album.contributors.length} 位参与者</small>
        </span>
      </button>
      <button class="home-album-rename" type="button" aria-label="重命名 ${escapeHtml(album.name)}">名</button>
      <button class="home-album-delete" type="button" aria-label="删除 ${escapeHtml(album.name)}">删</button>
    `;
    card.querySelector(".home-album-open").addEventListener("click", () => {
      resetPhotoSelection();
      state.currentAlbumId = album.id;
      state.currentFolderId = "";
      state.allPhotosOpen = false;
      state.myPhotosOpen = false;
      state.uploadExpanded = false;
      render();
    });
    card.querySelector(".home-album-delete").addEventListener("click", () => {
      deleteAlbum(album.id).catch((error) => alert(error.message));
    });
    card.querySelector(".home-album-rename").addEventListener("click", () => {
      const name = window.prompt("给这个相册换个名字", album.name);
      if (name === null) return;
      renameAlbum(album.id, name).catch((error) => alert(error.message));
    });
    homeAlbums.appendChild(card);
  });
}

function renderFolderNav(album, selectedFolder) {
  albumList.classList.remove("hidden");
  subalbumAlbumName.textContent = album.name;
  albumList.innerHTML = "";

  const orderedFolders = sortedFolders(album).sort((a, b) => {
    if (a.id === selectedFolder.id) return -1;
    if (b.id === selectedFolder.id) return 1;
    return 0;
  });

  orderedFolders.forEach((folder) => {
    const folderName = folderDisplayName(folder);
    const count = album.photos.filter((photo) => photoInFolder(photo, folder.id)).length;
    const item = document.createElement("div");
    item.className = `album-item subalbum-item${folder.id === selectedFolder.id ? " active" : ""}`;
    item.innerHTML = `
      <button class="album-select" type="button" aria-label="切换到 ${escapeHtml(folderName)}">
        <strong>${escapeHtml(folderName)}</strong>
        <span>${count} 张照片</span>
      </button>
    `;
    item.querySelector(".album-select").addEventListener("click", () => {
      resetPhotoSelection();
      state.currentFolderId = folder.id;
      render();
    });
    albumList.appendChild(item);
  });
}

function render() {
  renderAuth();
  if (!state.token || !state.currentUser) return;
  renderPrimaryAlbumNav();

  const album = getCurrentAlbum();
  if (!album) {
    openCreateAlbum.classList.remove("hidden");
    sidebar.classList.remove("album-mode", "subalbum-mode");
    topbar.classList.remove("folder-summary-topbar");
    currentAlbumTitle.textContent = "请选择或创建一个相册";
    stats.innerHTML = "";
    renderHomeAlbums();
    albumPanel.classList.add("hidden");
    return;
  }

  openCreateAlbum.classList.add("hidden");
  emptyState.classList.add("hidden");
  homeAlbums.classList.add("hidden");
  albumPanel.classList.remove("hidden");
  updateUploadProgress(album);
  updatePolling(album);
  const selectedFolder = album.folders.find((folder) => folder.id === state.currentFolderId);
  if (selectedFolder) {
    const selectedCount = album.photos.filter((photo) => photoInFolder(photo, selectedFolder.id)).length;
    topbar.classList.add("folder-summary-topbar");
    currentAlbumTitle.textContent = `${selectedCount} 张照片`;
    stats.innerHTML = "";
    sidebar.classList.remove("album-mode");
    sidebar.classList.add("subalbum-mode");
    renderFolderNav(album, selectedFolder);
    renderFolderDetail(album, selectedFolder);
  } else {
    topbar.classList.remove("folder-summary-topbar");
    currentAlbumTitle.textContent = album.name;
    stats.innerHTML = `
      <span class="stat">${album.photos.length} 张朋友视角</span>
      <span class="stat">${album.folders.length} 个可下载小相册</span>
      <span class="stat">${album.contributors.length} 位参与者</span>
    `;
    albumContextName.textContent = album.name;
    sidebar.classList.remove("subalbum-mode");
    sidebar.classList.add("album-mode");
    renderFolders(album);
  }
}

function renderFolders(album) {
  if (state.myPhotosOpen) {
    uploadForm.classList.add("hidden");
    toggleUploadForm.classList.add("hidden");
    folders.classList.add("hidden");
    allPhotos.classList.add("hidden");
    myPhotosPanel.classList.remove("hidden");
    folderDetail.classList.remove("hidden");
    renderMyPhotosDetail(album);
    return;
  }

  if (state.allPhotosOpen) {
    uploadForm.classList.add("hidden");
    toggleUploadForm.classList.add("hidden");
    folders.classList.add("hidden");
    myPhotosPanel.classList.add("hidden");
    folderDetail.classList.add("hidden");
    allPhotos.classList.remove("hidden");
    renderAllPhotos(album);
    return;
  }

  toggleUploadForm.classList.remove("hidden");
  uploadForm.classList.toggle("hidden", !state.uploadExpanded);
  toggleUploadForm.textContent = state.uploadExpanded ? "收起上传" : "上传照片";
  allPhotos.classList.remove("hidden");
  folders.classList.remove("hidden");
  myPhotosPanel.classList.remove("hidden");
  folderDetail.classList.add("hidden");
  renderMyPhotosCard(album);
  renderAllPhotos(album);

  if (!album.folders.length) {
    folders.innerHTML = `
      <section class="empty">
        <div>
          <h3>还没有照片</h3>
          <p>把这个页面发给同行朋友，大家各自把手机里的照片倒进来。等照片池热闹起来，就能按人物打包下载。</p>
        </div>
      </section>
    `;
    folders.insertAdjacentElement("afterend", toggleUploadForm);
    toggleUploadForm.insertAdjacentElement("afterend", uploadForm);
    uploadForm.insertAdjacentElement("afterend", allPhotos);
    return;
  }

  folders.innerHTML = "";
  folders.insertAdjacentHTML(
    "beforeend",
    `<div class="section-heading"><h3>按人打包带走</h3><p>${album.folders.length} 个可下载小相册</p></div>`,
  );
  sortedFolders(album).forEach((folder) => {
    const folderName = folderDisplayName(folder);
    const photos = album.photos
      .filter((photo) => photoInFolder(photo, folder.id))
      .sort((a, b) => b.createdAt - a.createdAt);
    const coverPhoto = pickFolderCoverPhoto(folder, photos);
    const section = document.createElement("section");
    section.className = "folder";
    section.dataset.folderId = folder.id;
    section.tabIndex = 0;
    section.setAttribute("role", "button");
    section.setAttribute("aria-label", `查看 ${folderName}`);
    section.innerHTML = `
      <div class="folder-header">
        <div class="folder-title">
          <h3>${escapeHtml(folderName)}</h3>
          <p>${photos.length} 张 · 最近 ${formatDate(Math.max(...photos.map((photo) => photo.createdAt)))}</p>
        </div>
        <div class="folder-actions">
          <button class="secondary rename-folder icon-button" type="button" data-folder-id="${escapeHtml(folder.id)}" data-folder-name="${escapeHtml(folderName)}" aria-label="重命名 ${escapeHtml(folderName)}">名</button>
          <button class="secondary download-folder icon-button" type="button" data-folder-id="${escapeHtml(folder.id)}" data-folder-name="${escapeHtml(folderName)}" aria-label="下载 ${escapeHtml(folderName)}">↓</button>
          <button class="secondary danger delete-folder icon-button" type="button" data-folder-id="${escapeHtml(folder.id)}" aria-label="删除 ${escapeHtml(folderName)}">删</button>
        </div>
      </div>
      ${
        coverPhoto
          ? `
            <figure class="folder-cover">
              <img src="${folderCoverUrl(folder, coverPhoto)}" alt="${escapeHtml(coverPhoto.originalName)}" loading="lazy" decoding="async" />
              <figcaption>
                <strong>${escapeHtml(coverPhoto.uploader)}</strong>
                <span>${formatDate(coverPhoto.createdAt)}</span>
              </figcaption>
            </figure>
          `
          : ""
      }
      <button class="open-folder" type="button" data-folder-id="${escapeHtml(folder.id)}">认领看看</button>
    `;
    folders.appendChild(section);
  });

  folders.insertAdjacentElement("afterend", toggleUploadForm);
  toggleUploadForm.insertAdjacentElement("afterend", uploadForm);
  uploadForm.insertAdjacentElement("afterend", allPhotos);

  folders.querySelectorAll(".rename-folder").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const currentName = button.dataset.folderName || "";
      const name = window.prompt("给这个小相册换个名字", currentName);
      if (name === null) return;
      renameFolderById(album.id, button.dataset.folderId, name).catch((error) => alert(error.message));
    });
  });

  folders.querySelectorAll(".delete-folder").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteFolder(album.id, button.dataset.folderId).catch((error) => alert(error.message));
    });
  });

  folders.querySelectorAll(".download-folder").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const folderName = button.dataset.folderName || "小相册";
      downloadWithAuth(`/api/albums/${pathPart(album.id)}/folders/${pathPart(button.dataset.folderId)}/download`, `PicMe-${folderName}.zip`).catch((error) =>
        alert(error.message),
      );
    });
  });
}

function renderFolderDetail(album, folder) {
  uploadForm.classList.add("hidden");
  toggleUploadForm.classList.add("hidden");
  allPhotos.classList.add("hidden");
  folders.classList.add("hidden");
  myPhotosPanel.classList.add("hidden");
  folderDetail.classList.remove("hidden");

  const photos = album.photos.filter((photo) => photoInFolder(photo, folder.id));
  const photoMoveTargets = album.folders.filter((item) => item.id !== folder.id);
  renderPhotoGrid(folderDetail, photos, {
    album,
    photoMoveTargets,
    mode: "detail",
    allPhotos: photos,
  });
}

function myPhotoIds(album) {
  return new Set(Array.isArray(album.myPhotoIds) ? album.myPhotoIds : []);
}

function myPhotos(album) {
  const ids = myPhotoIds(album);
  if (!ids.size) return [];
  return album.photos.filter((photo) => ids.has(photo.id)).sort((a, b) => b.createdAt - a.createdAt);
}

function renderMyPhotosCard(album) {
  const photos = myPhotos(album);
  const count = typeof album.myPhotoCount === "number" ? album.myPhotoCount : photos.length;
  const cover = album.myCoverUrl || (photos[0] ? photoPreviewSrc(photos[0]) : "");
  const user = state.currentUser || {};
  const avatar = user.avatarUrl || "";
  myPhotosPanel.innerHTML = `
    <button id="openMyPhotos" class="my-photos-card" type="button">
      <span class="my-photos-avatar">
        ${
          avatar
            ? `<img src="${escapeHtml(avatar)}" alt="${escapeHtml(user.nickname || user.username || "我")}" loading="lazy" decoding="async" />`
            : `<span class="avatar-person"></span>`
        }
      </span>
      <span class="my-photos-copy">
        <strong>我的照片</strong>
        <small>${count ? `已为你匹配 ${count} 张照片` : user.hasFaceProfile ? "暂时还没匹配到你的照片" : "上传带人脸头像后，会优先推荐你的照片"}</small>
      </span>
      <span class="my-photos-cover ${cover ? "" : "empty"}">
        ${cover ? `<img src="${escapeHtml(cover)}" alt="我的照片封面" loading="lazy" decoding="async" />` : "PicMe"}
      </span>
    </button>
  `;
  $("#openMyPhotos").addEventListener("click", () => {
    resetPhotoSelection();
    state.myPhotosOpen = true;
    state.allPhotosOpen = false;
    state.uploadExpanded = false;
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function renderMyPhotosDetail(album) {
  const photos = myPhotos(album);
  const expectedCount = typeof album.myPhotoCount === "number" ? album.myPhotoCount : photos.length;
  myPhotosPanel.classList.add("hidden");
  if (!photos.length) {
    folderDetail.innerHTML = `
      <div class="detail-toolbar all-photos-toolbar">
        <button id="backFromMyPhotos" class="secondary" type="button">返回相册</button>
        <div class="detail-title">
          <h3>我的照片</h3>
          <p>${expectedCount ? "匹配结果还在同步中" : "当前相册暂时没有匹配到你的照片"}</p>
        </div>
      </div>
      <section class="empty my-photos-empty">
        <div>
          <h3>还没有专属照片</h3>
          <p>${state.currentUser && state.currentUser.hasFaceProfile ? "等朋友继续上传，系统识别后会自动把你放到这里。" : "注册时上传一张带人脸的头像，系统会用它帮你推荐关联照片。"}</p>
        </div>
      </section>
    `;
    $("#backFromMyPhotos").addEventListener("click", () => {
      resetPhotoSelection();
      state.myPhotosOpen = false;
      render();
    });
    return;
  }

  folderDetail.innerHTML = `
    <div class="detail-toolbar all-photos-toolbar">
      <button id="backFromMyPhotos" class="secondary" type="button">返回相册</button>
      <div class="detail-title">
        <h3>我的照片</h3>
        <p>已为你匹配 ${photos.length} 张照片</p>
      </div>
    </div>
    <div id="myPhotosGridMount"></div>
  `;
  $("#backFromMyPhotos").addEventListener("click", () => {
    resetPhotoSelection();
    state.myPhotosOpen = false;
    render();
  });
  renderPhotoGrid($("#myPhotosGridMount"), photos, {
    album,
    mode: "all",
    allPhotos: photos,
  });
}

function renderAllPhotos(album) {
  if (!album.photos.length) {
    allPhotos.innerHTML = `
      <button class="all-photos-entry" type="button" disabled>
        <strong>查看所有照片</strong>
        <span>照片池还是空的</span>
      </button>
    `;
    return;
  }

  const sortedPhotos = [...album.photos].sort((a, b) => b.createdAt - a.createdAt);
  if (!state.allPhotosOpen) {
    allPhotos.innerHTML = `
      <button id="openAllPhotos" class="all-photos-entry" type="button">
        <strong>查看所有照片</strong>
        <span>${sortedPhotos.length} 张原始上传，点开看大图</span>
      </button>
    `;
    $("#openAllPhotos").addEventListener("click", () => {
      resetPhotoSelection();
      state.allPhotosOpen = true;
      state.myPhotosOpen = false;
      state.allPhotosLimit = 12;
      state.uploadExpanded = false;
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    return;
  }

  const visiblePhotos = sortedPhotos.slice(0, state.allPhotosLimit);
  const hasMore = visiblePhotos.length < sortedPhotos.length;
  allPhotos.innerHTML = `
    <div class="detail-toolbar all-photos-toolbar">
      <button id="backFromAllPhotos" class="secondary" type="button">返回</button>
      <div class="detail-title">
        <h3>所有照片</h3>
        <p>已显示 ${visiblePhotos.length} / ${sortedPhotos.length} 张，向下滑继续加载</p>
      </div>
    </div>
    <div id="allPhotosGridMount"></div>
    ${
      hasMore
        ? `<button id="loadMorePhotos" class="secondary load-more-photos" type="button">再看 ${Math.min(12, sortedPhotos.length - visiblePhotos.length)} 张</button>`
        : `<p class="photo-end">已经到底啦</p>`
    }
  `;

  $("#backFromAllPhotos").addEventListener("click", () => {
    resetPhotoSelection();
    state.allPhotosOpen = false;
    render();
  });
  const loadMorePhotos = $("#loadMorePhotos");
  if (loadMorePhotos) {
    loadMorePhotos.addEventListener("click", () => {
      loadMoreAllPhotos();
    });
  }
  renderPhotoGrid($("#allPhotosGridMount"), visiblePhotos, {
    album,
    mode: "all",
    allPhotos: sortedPhotos,
  });
}

function loadMoreAllPhotos() {
  const album = getCurrentAlbum();
  if (!album || !state.allPhotosOpen) return;
  if (state.allPhotosLimit >= album.photos.length) return;
  state.allPhotosLimit = Math.min(state.allPhotosLimit + 12, album.photos.length);
  render();
}

async function deleteAlbum(albumId) {
  const album = state.albums.find((item) => item.id === albumId);
  if (!album) return;
  const message =
    `确定删除一级相册“${album.name}”吗？\n\n` +
    `这个操作会物理删除该相册内的 ${album.photos.length} 张照片、缩略图和下载缓存，删除后无法从页面恢复。`;
  if (!window.confirm(message)) return;
  await api(`/api/albums/${pathPart(albumId)}`, {
    method: "DELETE",
  });
  state.albums = state.albums.filter((item) => item.id !== albumId);
  if (state.currentAlbumId === albumId) {
    state.currentAlbumId = state.albums[0] ? state.albums[0].id : "";
    state.currentFolderId = "";
  }
  render();
}

async function renameAlbum(albumId, name) {
  const nextName = (name || "").trim();
  if (!nextName) {
    throw new Error("名称不能为空");
  }
  const payload = await api(`/api/albums/${pathPart(albumId)}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: nextName }),
  });
  state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
  render();
}

async function deleteFolder(albumId, folderId) {
  const album = state.albums.find((item) => item.id === albumId);
  const folder = album ? album.folders.find((item) => item.id === folderId) : null;
  if (!folder) return;
  const photos = album.photos.filter((photo) => photoInFolder(photo, folderId));
  const sharedCount = photos.filter((photo) => photoFolderIds(photo).length > 1).length;
  const onlyCount = photos.length - sharedCount;
  const message =
    `确定删除子相册“${folder.name}”吗？\n\n` +
    `仅属于这个子相册的 ${onlyCount} 张照片会被物理删除。\n` +
    `同时属于其他子相册的 ${sharedCount} 张照片只会从这里移除，直到不属于任何子相册时才会删除文件。`;
  if (!window.confirm(message)) return;
  const payload = await api(`/api/albums/${pathPart(albumId)}/folders/${pathPart(folderId)}`, {
    method: "DELETE",
  });
  state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
  if (state.currentFolderId === folderId) {
    state.currentFolderId = "";
  }
  render();
}

async function renameFolderById(albumId, folderId, name) {
  const nextName = (name || "").trim();
  if (!nextName) {
    throw new Error("名称不能为空");
  }
  const payload = await api(`/api/albums/${pathPart(albumId)}/folders/${pathPart(folderId)}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: nextName }),
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  render();
}

async function mergeCurrentFolder(albumId, sourceFolderId) {
  const targetFolderId = $("#mergeTarget").value;
  if (!targetFolderId) {
    $("#correctionStatus").textContent = "请选择目标文件夹";
    return;
  }
  $("#correctionStatus").textContent = "正在合并...";
  const payload = await api(`/api/albums/${pathPart(albumId)}/folders/${pathPart(sourceFolderId)}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ targetFolderId }),
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  state.currentFolderId = targetFolderId;
  render();
}

async function markCurrentFolderNoFace(albumId, sourceFolderId) {
  $("#correctionStatus").textContent = "正在标记...";
  const payload = await api(`/api/albums/${pathPart(albumId)}/folders/${pathPart(sourceFolderId)}/mark-no-face`, {
    method: "POST",
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  const noFaceFolder = payload.album.folders.find((folder) => folder.id === "no-face" || folder.name === "其他" || folder.name === "未识别人脸");
  state.currentFolderId = noFaceFolder ? noFaceFolder.id : "";
  render();
}

async function renameCurrentFolder(albumId, folderId) {
  const name = $("#folderNameInput").value.trim();
  if (!name) {
    $("#correctionStatus").textContent = "昵称不能为空";
    return;
  }
  $("#correctionStatus").textContent = "正在保存昵称...";
  const payload = await api(`/api/albums/${pathPart(albumId)}/folders/${pathPart(folderId)}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  state.currentFolderId = folderId;
  render();
}

async function movePhotoToFolder(albumId, photoId) {
  const select = folderDetail.querySelector(`[data-photo-target="${CSS.escape(photoId)}"]`);
  const targetFolderId = select ? select.value : "";
  if (!targetFolderId) {
    alert("请选择要移动到的文件夹");
    return;
  }
  const payload = await api(`/api/albums/${pathPart(albumId)}/photos/${pathPart(photoId)}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ targetFolderId }),
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  render();
}

function updateAlbumFromPayload(payload) {
  if (!payload || !payload.album) return;
  state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
}

async function downloadSelectedPhotos(albumId, photos) {
  if (!photos.length) return;
  const response = await fetch(`/api/albums/${pathPart(albumId)}/photos/download-selected`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ photoIds: photos.map((photo) => photo.id) }),
  });
  if (response.status === 401) {
    clearAuthSession();
    throw new Error("登录已过期，请重新登录");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `下载失败：${response.status}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `PicMe-${photos.length}项.zip`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1200);
}

async function deleteSelectedPhotos(albumId, photos) {
  if (!photos.length) return;
  if (!window.confirm(`确定删除选中的 ${photos.length} 张照片吗？`)) return;
  const payload = await api(`/api/albums/${pathPart(albumId)}/photos/delete-selected`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ photoIds: photos.map((photo) => photo.id) }),
  });
  updateAlbumFromPayload(payload);
  resetPhotoSelection();
  if (photoViewer.open && photos.some((photo) => photo.id === state.viewerPhotoId)) {
    photoViewer.close();
  }
  const currentAlbum = getCurrentAlbum();
  if (currentAlbum && state.currentFolderId && !currentAlbum.folders.some((folder) => folder.id === state.currentFolderId)) {
    state.currentFolderId = "";
  }
  render();
}

async function moveSelectedPhotos(album, photos) {
  if (!state.currentFolderId || !photos.length) return;
  const targets = album.folders.filter((folder) => folder.id !== state.currentFolderId);
  if (!targets.length) {
    alert("暂无可移动到的小相册");
    return;
  }
  const choice = window.prompt(
    `移动到哪个小相册？\n${targets.map((folder, index) => `${index + 1}. ${folderDisplayName(folder)}`).join("\n")}\n请输入序号`,
  );
  if (choice === null) return;
  const target = targets[Number(choice) - 1];
  if (!target) {
    alert("没有找到这个小相册");
    return;
  }
  let latestAlbum = album;
  for (const photo of photos) {
    const payload = await api(`/api/albums/${pathPart(album.id)}/photos/${pathPart(photo.id)}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targetFolderId: target.id }),
    });
    latestAlbum = payload.album;
  }
  state.albums = state.albums.map((item) => (item.id === latestAlbum.id ? latestAlbum : item));
  resetPhotoSelection();
  render();
}

async function deletePhoto(albumId, photoId) {
  const album = state.albums.find((item) => item.id === albumId);
  const photo = album ? album.photos.find((item) => item.id === photoId) : null;
  if (!photo) return;
  if (!window.confirm(`确定删除照片“${photo.originalName}”吗？`)) return;
  const payload = await api(`/api/albums/${pathPart(albumId)}/photos/${pathPart(photoId)}`, {
    method: "DELETE",
  });
  state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
  const currentAlbum = getCurrentAlbum();
  if (currentAlbum && state.currentFolderId && !currentAlbum.folders.some((folder) => folder.id === state.currentFolderId)) {
    state.currentFolderId = "";
  }
  if (photoViewer.open && state.viewerPhotoId === photo.id) {
    photoViewer.close();
  }
  render();
}

function openPhotoViewer(photo, photos = []) {
  const viewerPhotos = photos.length ? photos : [photo];
  const viewerIndex = Math.max(0, viewerPhotos.findIndex((item) => item.id === photo.id));
  state.viewerPhotos = viewerPhotos;
  state.viewerIndex = viewerIndex;
  showViewerPhoto(viewerPhotos[viewerIndex] || photo);
}

function showViewerPhoto(photo) {
  const token = state.viewerToken + 1;
  state.viewerToken = token;
  state.viewerPhotoId = photo.id;
  photoViewer.classList.add("loading");
  viewerImage.removeAttribute("src");
  viewerImage.alt = "";
  viewerVideo.pause();
  viewerVideo.removeAttribute("src");
  viewerVideo.load();
  viewerVideo.classList.add("hidden");
  viewerLivePlay.classList.add("hidden");
  photoViewer.classList.remove("live-playing");
  viewerMeta.textContent = "正在打开原图...";
  viewerDownload.href = photoDownloadUrl(photo);
  viewerDownload.setAttribute("download", "");
  viewerDelete.dataset.photoId = photo.id;
  renderViewerFilmstrip();
  if (photo.type === "live_photo" && photo.downloadLiveUrl) {
    viewerVideo.src = photo.videoUrl;
    viewerVideo.classList.remove("hidden");
    viewerLivePlay.classList.remove("hidden");
  } else {
    viewerDownload.href = photoDownloadUrl(photo);
  }
  if (!photoViewer.open && typeof photoViewer.showModal === "function") {
    photoViewer.showModal();
  } else if (!photoViewer.open) {
    photoViewer.setAttribute("open", "");
  }

  const nextImage = new Image();
  nextImage.onload = () => {
    if (state.viewerToken !== token) return;
    viewerImage.src = photoViewerSrc(photo);
    viewerImage.alt = photo.originalName;
    viewerMeta.textContent = "";
    renderViewerFilmstrip();
    photoViewer.classList.remove("loading");
    if (photo.type === "live_photo" && photo.videoUrl) {
      playViewerLive();
    }
  };
  nextImage.onerror = () => {
    if (state.viewerToken !== token) return;
    viewerMeta.textContent = "原图加载失败，请稍后再试";
    photoViewer.classList.remove("loading");
  };
  nextImage.src = photoViewerSrc(photo);
}

function renderViewerFilmstrip() {
  if (!viewerFilmstrip) return;
  viewerFilmstrip.innerHTML = state.viewerPhotos
    .map(
      (photo, index) => `
        <button class="viewer-thumb ${index === state.viewerIndex ? "active" : ""}" type="button" data-index="${index}" aria-label="查看 ${escapeHtml(photo.originalName)}">
          <img src="${photoPreviewSrc(photo)}" alt="" loading="lazy" decoding="async" />
        </button>
      `,
    )
    .join("");
  viewerFilmstrip.querySelectorAll(".viewer-thumb").forEach((button) => {
    button.addEventListener("click", () => {
      const nextIndex = Number(button.dataset.index);
      const photo = state.viewerPhotos[nextIndex];
      if (!photo) return;
      state.viewerIndex = nextIndex;
      showViewerPhoto(photo);
    });
  });
  const active = viewerFilmstrip.querySelector(".viewer-thumb.active");
  if (active) {
    active.scrollIntoView({ inline: "center", block: "nearest" });
  }
}

function bindLivePhotoPlayback(root) {
  root.querySelectorAll(".live-photo-card").forEach((card) => {
    const video = card.querySelector(".live-photo-video");
    const badge = card.querySelector(".live-photo-badge");
    if (!video || !badge || card.dataset.liveBound === "1") return;
    card.dataset.liveBound = "1";

    const stop = () => {
      video.pause();
      video.currentTime = 0;
      card.classList.remove("live-playing");
    };

    const play = () => {
      card.classList.add("live-playing");
      video.currentTime = 0;
      video.play().catch(() => {
        card.classList.remove("live-playing");
      });
    };

    badge.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (card.classList.contains("live-playing")) {
        stop();
      } else {
        play();
      }
    });
    video.addEventListener("ended", stop);
  });
}

function stopViewerLive() {
  if (viewerVideo.classList.contains("hidden")) return;
  viewerVideo.pause();
  viewerVideo.currentTime = 0;
  photoViewer.classList.remove("live-playing");
}

function playViewerLive() {
  if (viewerVideo.classList.contains("hidden")) return;
  photoViewer.classList.add("live-playing");
  viewerVideo.currentTime = 0;
  viewerVideo.play().catch(() => {
    photoViewer.classList.remove("live-playing");
  });
}

function toggleViewerLivePlayback() {
  if (photoViewer.classList.contains("live-playing")) {
    stopViewerLive();
  } else {
    playViewerLive();
  }
}

function showAdjacentViewerPhoto(direction) {
  if (!state.viewerPhotos.length) return;
  const nextIndex = state.viewerIndex + direction;
  if (nextIndex < 0 || nextIndex >= state.viewerPhotos.length) return;
  state.viewerIndex = nextIndex;
  showViewerPhoto(state.viewerPhotos[nextIndex]);
}

async function createAlbum(event) {
  event.preventDefault();
  const name = albumName.value.trim() || "共享相册";
  const payload = await api("/api/albums", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  state.albums.unshift(payload.album);
  state.currentAlbumId = payload.album.id;
  state.currentFolderId = "";
  state.myPhotosOpen = false;
  albumName.value = "";
  if (createAlbumDialog.open) {
    createAlbumDialog.close();
  }
  render();
}

function uploadClientFileId(index) {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`;
}

function uploadClientAssetId(file) {
  const stem = file.name.replace(/\.[^.]+$/, "").toLowerCase();
  return stem || uploadClientFileId(0);
}

async function legacyUploadPhotos(album, files, uploader) {
  const form = new FormData();
  form.append("uploader", uploader);
  for (const file of files) {
    form.append("photos", file);
  }
  return api(`/api/albums/${pathPart(album.id)}/upload`, {
    method: "POST",
    body: form,
  });
}

async function directUploadPhotos(album, files, uploader) {
  const uploadFiles = files.map((file, index) => ({
    clientFileId: uploadClientFileId(index),
    clientAssetId: uploadClientAssetId(file),
    name: file.name,
    mimeType: file.type || "application/octet-stream",
    fileSize: file.size,
    lastModified: file.lastModified || 0,
  }));
  let init;
  try {
    init = await api(`/api/albums/${pathPart(album.id)}/uploads/init`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uploader, files: uploadFiles }),
    });
  } catch (error) {
    error.allowLegacyFallback = true;
    throw error;
  }
  const filesById = new Map(uploadFiles.map((item, index) => [item.clientFileId, files[index]]));
  const resources = init.uploads.flatMap((upload) => [upload.image, upload.video].filter(Boolean));
  let completed = 0;
  for (const resource of resources) {
    const file = filesById.get(resource.clientFileId);
    if (!file) continue;
    uploadStatus.textContent = `正在直传 OSS：${completed + 1}/${resources.length}`;
    let response;
    try {
      response = await fetch(resource.uploadUrl, {
        method: "PUT",
        headers: resource.headers || {},
        body: file,
      });
    } catch (error) {
      error.allowLegacyFallback = completed === 0;
      throw error;
    }
    if (!response.ok) {
      const error = new Error(`OSS 上传失败：${response.status}`);
      error.allowLegacyFallback = completed === 0;
      throw error;
    }
    completed += 1;
  }
  return api(`/api/albums/${pathPart(album.id)}/uploads/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uploader, uploads: init.uploads }),
  });
}

async function uploadPhotos(event) {
  event.preventDefault();
  const album = getCurrentAlbum();
  const files = Array.from(photosInput.files || []);
  if (!album || !files.length) return;

  state.uploading = true;
  uploadStatus.textContent = `正在准备 ${files.length} 张朋友视角`;
  uploadForm.querySelector("button[type='submit']").disabled = true;
  const uploader = $("#uploader").value.trim() || (state.currentUser && (state.currentUser.nickname || state.currentUser.username)) || "访客";

  try {
    let payload;
    try {
      payload = await directUploadPhotos(album, files, uploader);
    } catch (error) {
      if (!error.allowLegacyFallback) {
        throw error;
      }
      console.warn("Direct OSS upload unavailable, fallback to server upload", error);
      uploadStatus.textContent = `直传不可用，切换服务器上传`;
      payload = await legacyUploadPhotos(album, files, uploader);
    }
    state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
    state.lastUpload = {
      albumId: payload.album.id,
      photoIds: (payload.photos || []).map((photo) => photo.id),
    };
    photosInput.value = "";
    selectedFiles.textContent = defaultSelectedFilesText();
    uploadStatus.textContent = `收到 ${payload.queued || files.length} 张，已经放进照片池，后台开始分人${
      payload.ignored ? `；${payload.ignored} 个文件未匹配到照片` : ""
    }`;
    render();
  } finally {
    state.uploading = false;
    uploadForm.querySelector("button[type='submit']").disabled = false;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

photosInput.addEventListener("change", () => {
  const count = photosInput.files.length;
  selectedFiles.textContent = count ? `已选好 ${count} 张，准备加入这次出游照片池` : defaultSelectedFilesText();
});

loginForm.addEventListener("submit", (event) => {
  login(event).catch((error) => {
    loginStatus.textContent = error.message;
  });
});

registerForm.addEventListener("submit", (event) => {
  register(event).catch((error) => {
    registerStatus.textContent = error.message;
  });
});

showRegister.addEventListener("click", () => {
  state.authMode = "register";
  loginStatus.textContent = "";
  registerStatus.textContent = "";
  renderAuth();
  registerNickname.focus();
});

showLogin.addEventListener("click", () => {
  state.authMode = "login";
  renderAuth();
  loginUsername.focus();
});

registerToLogin.addEventListener("click", () => {
  state.authMode = "login";
  renderAuth();
  loginUsername.focus();
});

registerAvatar.addEventListener("change", () => {
  const file = registerAvatar.files && registerAvatar.files[0];
  if (avatarPreviewUrl) {
    URL.revokeObjectURL(avatarPreviewUrl);
    avatarPreviewUrl = "";
  }
  if (!file) {
    avatarPreview.style.backgroundImage = "";
    avatarPreview.classList.remove("has-image");
    return;
  }
  avatarPreviewUrl = URL.createObjectURL(file);
  avatarPreview.style.backgroundImage = `url("${avatarPreviewUrl}")`;
  avatarPreview.classList.add("has-image");
});

folders.addEventListener("click", (event) => {
  if (event.target.closest("a")) return;
  const folder = event.target.closest(".folder");
  if (!folder) return;
  resetPhotoSelection();
  state.currentFolderId = folder.dataset.folderId;
  render();
});

folders.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const folder = event.target.closest(".folder");
  if (!folder) return;
  event.preventDefault();
  resetPhotoSelection();
  state.currentFolderId = folder.dataset.folderId;
  render();
});

backToHomeButton.addEventListener("click", returnToHome);

toggleUploadForm.addEventListener("click", () => {
  state.uploadExpanded = !state.uploadExpanded;
  render();
  if (state.uploadExpanded) {
    uploadForm.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

mobileBackToFolders.addEventListener("click", backToFolderList);

albumPanel.addEventListener("touchstart", (event) => {
  if (!state.currentAlbumId || state.currentFolderId || event.touches.length !== 1) return;
  const touch = event.touches[0];
  state.touchStart = { x: touch.clientX, y: touch.clientY };
});

albumPanel.addEventListener("touchend", (event) => {
  if (!state.currentAlbumId || state.currentFolderId || !state.touchStart || event.changedTouches.length !== 1) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - state.touchStart.x;
  const dy = touch.clientY - state.touchStart.y;
  const startedNearLeftEdge = state.touchStart.x < 45;
  state.touchStart = null;
  if (Math.abs(dy) > 70) return;
  if (state.myPhotosOpen && (dx <= -80 || (startedNearLeftEdge && dx >= 80))) {
    state.myPhotosOpen = false;
    render();
    return;
  }
  if (state.allPhotosOpen && (dx <= -80 || (startedNearLeftEdge && dx >= 80))) {
    state.allPhotosOpen = false;
    render();
    return;
  }
  if (dx <= -80 || (startedNearLeftEdge && dx >= 80)) {
    returnToHome();
  }
});

folderDetail.addEventListener("touchstart", (event) => {
  if (!state.currentFolderId || event.touches.length !== 1) return;
  const touch = event.touches[0];
  state.touchStart = { x: touch.clientX, y: touch.clientY };
});

folderDetail.addEventListener("touchend", (event) => {
  if (!state.currentFolderId || !state.touchStart || event.changedTouches.length !== 1) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - state.touchStart.x;
  const dy = touch.clientY - state.touchStart.y;
  state.touchStart = null;
  if (dx <= -80 && Math.abs(dy) <= 70) {
    backToFolderList();
  }
});

closeViewer.addEventListener("click", () => {
  photoViewer.close();
});

viewerLivePlay.addEventListener("click", (event) => {
  event.preventDefault();
  event.stopPropagation();
  toggleViewerLivePlayback();
});

viewerDelete.addEventListener("click", () => {
  const album = getCurrentAlbum();
  const photoId = viewerDelete.dataset.photoId || state.viewerPhotoId;
  if (!album || !photoId) return;
  deletePhoto(album.id, photoId).catch((error) => alert(error.message));
});

viewerDownload.addEventListener("click", (event) => {
  const url = viewerDownload.getAttribute("href") || "";
  if (!requiresAlbumAuth(url)) return;
  event.preventDefault();
  const photo = state.viewerPhotos.find((item) => item.id === state.viewerPhotoId);
  downloadWithAuth(url, photo ? photo.originalName : "PicMe-photo").catch((error) => alert(error.message));
});

viewerVideo.addEventListener("ended", () => {
  stopViewerLive();
});

photoViewer.addEventListener("touchstart", (event) => {
  if (!photoViewer.open || event.touches.length !== 1) return;
  const touch = event.touches[0];
  state.viewerTouchStart = { x: touch.clientX, y: touch.clientY };
});

photoViewer.addEventListener("touchend", (event) => {
  if (!photoViewer.open || !state.viewerTouchStart || event.changedTouches.length !== 1) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - state.viewerTouchStart.x;
  const dy = touch.clientY - state.viewerTouchStart.y;
  state.viewerTouchStart = null;
  if (Math.abs(dx) < 60 || Math.abs(dy) > 80) return;
  showAdjacentViewerPhoto(dx < 0 ? 1 : -1);
});

photoViewer.addEventListener("click", (event) => {
  if (event.target === photoViewer) {
    photoViewer.close();
  }
});

photoViewer.addEventListener("close", () => {
  state.viewerToken += 1;
  state.viewerPhotoId = "";
  state.viewerPhotos = [];
  state.viewerIndex = -1;
  state.viewerTouchStart = null;
  photoViewer.classList.remove("loading");
  stopViewerLive();
  viewerVideo.removeAttribute("src");
  viewerVideo.load();
});

window.addEventListener("keydown", (event) => {
  if (!photoViewer.open) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    showAdjacentViewerPhoto(-1);
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    showAdjacentViewerPhoto(1);
  }
});

albumForm.addEventListener("submit", (event) => {
  createAlbum(event).catch((error) => alert(error.message));
});

openCreateAlbum.addEventListener("click", () => {
  if (typeof createAlbumDialog.showModal === "function") {
    createAlbumDialog.showModal();
  } else {
    createAlbumDialog.setAttribute("open", "");
  }
  albumName.focus();
});

cancelCreateAlbum.addEventListener("click", () => {
  albumName.value = "";
  createAlbumDialog.close();
});

createAlbumDialog.addEventListener("click", (event) => {
  if (event.target === createAlbumDialog) {
    createAlbumDialog.close();
  }
});

uploadForm.addEventListener("submit", (event) => {
  uploadPhotos(event).catch((error) => {
    uploadStatus.textContent = error.message;
  });
});

window.addEventListener("scroll", () => {
  if (!state.allPhotosOpen) return;
  const remaining = document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
  if (remaining < 420) {
    loadMoreAllPhotos();
  }
});

window.addEventListener("resize", () => {
  layoutPhotoGrids();
});

async function boot() {
  renderAuth();
  if (!state.token) return;
  const loadedUser = await loadCurrentUser();
  if (!loadedUser) return;
  await loadAlbums();
}

boot().catch((error) => {
  stats.innerHTML = `<span class="stat">${escapeHtml(error.message)}</span>`;
});
