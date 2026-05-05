const state = {
  albums: [],
  currentAlbumId: "",
  currentFolderId: "",
  uploading: false,
  pollTimer: 0,
  lastUpload: null,
  touchStart: null,
};

const $ = (selector) => document.querySelector(selector);

const albumForm = $("#albumForm");
const albumName = $("#albumName");
const albumList = $("#albumList");
const currentAlbumTitle = $("#currentAlbumTitle");
const stats = $("#stats");
const emptyState = $("#emptyState");
const albumPanel = $("#albumPanel");
const uploadForm = $("#uploadForm");
const photosInput = $("#photos");
const selectedFiles = $("#selectedFiles");
const uploadStatus = $("#uploadStatus");
const copyShareLink = $("#copyShareLink");
const shareLinkStatus = $("#shareLinkStatus");
const reanalyzeButton = $("#reanalyzeButton");
const allPhotos = $("#allPhotos");
const folders = $("#folders");
const folderDetail = $("#folderDetail");
const photoViewer = $("#photoViewer");
const viewerImage = $("#viewerImage");
const viewerMeta = $("#viewerMeta");
const closeViewer = $("#closeViewer");

function pathPart(value) {
  return encodeURIComponent(value);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return response.json();
}

function formatDate(seconds) {
  return new Date(seconds * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function loadAlbums(selectFirst = true) {
  const payload = await api("/api/albums");
  state.albums = payload.albums;
  if (!state.currentAlbumId && selectFirst && state.albums[0]) {
    state.currentAlbumId = state.albums[0].id;
  }
  render();
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
  if (folder.id === "group-photo" || folder.id === "no-face") {
    return photos[0];
  }
  return photos.find((photo) => photoFolderIds(photo).length === 1) || photos[0];
}

function folderCoverUrl(folder, photo) {
  if (!photo) return "";
  if (folder.id === "group-photo" || folder.id === "no-face") {
    return photo.coverUrl || photo.cardUrl || photo.url;
  }
  return photo.faceUrl || photo.coverUrl || photo.cardUrl || photo.url;
}

function backToFolderList() {
  if (!state.currentFolderId) return;
  state.currentFolderId = "";
  render();
}

function render() {
  albumList.innerHTML = "";
  state.albums.forEach((album) => {
    const item = document.createElement("div");
    item.className = `album-item${album.id === state.currentAlbumId ? " active" : ""}`;
    item.innerHTML = `
      <button class="album-select" type="button" aria-label="打开 ${escapeHtml(album.name)}">
        <strong>${escapeHtml(album.name)}</strong>
        <span>${album.photos.length} 张朋友视角 · ${album.contributors.length} 位参与者</span>
      </button>
      <button class="album-delete" type="button" aria-label="删除 ${escapeHtml(album.name)}">删</button>
    `;
    item.querySelector(".album-select").addEventListener("click", () => {
      state.currentAlbumId = album.id;
      state.currentFolderId = "";
      render();
    });
    item.querySelector(".album-delete").addEventListener("click", () => {
      deleteAlbum(album.id).catch((error) => alert(error.message));
    });
    albumList.appendChild(item);
  });

  const album = getCurrentAlbum();
  if (!album) {
    currentAlbumTitle.textContent = "先开一个朋友照片局吧";
    stats.innerHTML = "";
    emptyState.classList.remove("hidden");
    albumPanel.classList.add("hidden");
    return;
  }

  currentAlbumTitle.textContent = album.name;
  emptyState.classList.add("hidden");
  albumPanel.classList.remove("hidden");
  stats.innerHTML = `
    <span class="stat">${album.photos.length} 张朋友视角</span>
    <span class="stat">${album.folders.length} 个可下载小相册</span>
    <span class="stat">${album.contributors.length} 位参与者</span>
  `;
  updateUploadProgress(album);
  updatePolling(album);
  const selectedFolder = album.folders.find((folder) => folder.id === state.currentFolderId);
  if (selectedFolder) {
    renderFolderDetail(album, selectedFolder);
  } else {
    renderFolders(album);
  }
}

function renderFolders(album) {
  uploadForm.classList.remove("hidden");
  allPhotos.classList.remove("hidden");
  folders.classList.remove("hidden");
  folderDetail.classList.add("hidden");
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
    const previewPhotos = photos.filter((photo) => !coverPhoto || photo.id !== coverPhoto.id).slice(0, 4);
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
          <a href="/api/albums/${pathPart(album.id)}/folders/${pathPart(folder.id)}/download" aria-label="下载 ${escapeHtml(folderName)}">
            <button class="secondary icon-button" type="button" aria-label="下载 ${escapeHtml(folderName)}">↓</button>
          </a>
          <button class="secondary danger delete-folder icon-button" type="button" data-folder-id="${escapeHtml(folder.id)}" aria-label="删除 ${escapeHtml(folderName)}">删</button>
        </div>
      </div>
      ${
        coverPhoto
          ? `
            <figure class="folder-cover">
              <img src="${folderCoverUrl(folder, coverPhoto)}" alt="${escapeHtml(coverPhoto.originalName)}" loading="lazy" decoding="async" />
              <figcaption>
                <strong>${escapeHtml(coverPhoto.originalName)}</strong>
                <span>${escapeHtml(coverPhoto.uploader)}</span>
              </figcaption>
            </figure>
          `
          : ""
      }
      <div class="thumbs">
        ${previewPhotos
          .map(
            (photo) => `
              <figure class="photo">
                <img src="${photo.tinyUrl || photo.cardUrl || photo.url}" alt="${escapeHtml(photo.originalName)}" loading="lazy" decoding="async" />
                <span>${escapeHtml(photo.uploader)}</span>
              </figure>
            `,
          )
          .join("")}
      </div>
      <button class="open-folder" type="button" data-folder-id="${escapeHtml(folder.id)}">认领看看</button>
    `;
    folders.appendChild(section);
  });

  folders.querySelectorAll(".delete-folder").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteFolder(album.id, button.dataset.folderId).catch((error) => alert(error.message));
    });
  });
}

function renderFolderDetail(album, folder) {
  uploadForm.classList.add("hidden");
  allPhotos.classList.add("hidden");
  folders.classList.add("hidden");
  folderDetail.classList.remove("hidden");

  const photos = album.photos.filter((photo) => photoInFolder(photo, folder.id));
  const mergeTargets = album.folders.filter((item) => item.id !== folder.id);
  const photoMoveTargets = album.folders.filter((item) => item.id !== folder.id);
  folderDetail.innerHTML = `
    <div class="detail-toolbar">
      <button id="backToFolders" class="secondary" type="button">返回</button>
      <div class="detail-title">
        <div class="rename-row">
          <input id="folderNameInput" value="${escapeHtml(folderDisplayName(folder))}" maxlength="40" aria-label="相册昵称" />
          <button id="saveFolderName" class="secondary" type="button">保存昵称</button>
        </div>
        <p>${photos.length} 张照片 · 这里可能藏着朋友拍到的你</p>
      </div>
      <a href="/api/albums/${pathPart(album.id)}/folders/${pathPart(folder.id)}/download">
        <button type="button" aria-label="下载文件夹">下载</button>
      </a>
      <button id="deleteCurrentFolder" class="secondary danger" type="button" aria-label="删除文件夹">删</button>
    </div>
    <div class="correction-panel">
      <div>
        <strong>帮照片池纠个错</strong>
        <span>同一个人被拆开时可以合并；不是人物的照片可以标记为其他。</span>
      </div>
      <div class="correction-actions">
        <select id="mergeTarget" ${mergeTargets.length ? "" : "disabled"}>
          <option value="">选择要合并到的文件夹</option>
          ${mergeTargets.map((target) => `<option value="${escapeHtml(target.id)}">${escapeHtml(folderDisplayName(target))}</option>`).join("")}
        </select>
        <button id="mergeFolder" class="secondary" type="button" ${mergeTargets.length ? "" : "disabled"}>合并</button>
        <button id="markNoFace" class="secondary danger" type="button" ${folder.id === "no-face" ? "disabled" : ""}>标记为其他</button>
      </div>
      <span id="correctionStatus"></span>
    </div>
    <div class="detail-grid">
      ${photos
        .map(
          (photo) => `
            <article class="detail-photo-card">
              <button class="detail-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">
                <img src="${photo.cardUrl || photo.url}" alt="${escapeHtml(photo.originalName)}" loading="lazy" decoding="async" />
                <span>
                  <strong>${escapeHtml(photo.originalName)}</strong>
                  <small>${escapeHtml(photo.uploader)} · ${formatDate(photo.createdAt)}</small>
                </span>
              </button>
              <div class="photo-correction">
                <select data-photo-target="${escapeHtml(photo.id)}">
                  <option value="">移动到...</option>
                  ${photoMoveTargets
                    .map((target) => `<option value="${escapeHtml(target.id)}">${escapeHtml(target.name)}</option>`)
                    .join("")}
                </select>
                <button class="secondary move-photo icon-button" type="button" data-photo-id="${escapeHtml(photo.id)}" aria-label="移动照片">移</button>
                <button class="secondary danger delete-photo icon-button" type="button" data-photo-id="${escapeHtml(photo.id)}" aria-label="删除照片">删</button>
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;

  $("#backToFolders").addEventListener("click", () => {
    backToFolderList();
  });

  $("#saveFolderName").addEventListener("click", () => {
    $("#saveFolderName").disabled = true;
    renameCurrentFolder(album.id, folder.id).catch((error) => {
      $("#correctionStatus").textContent = error.message;
      $("#saveFolderName").disabled = false;
    });
  });

  $("#folderNameInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      $("#saveFolderName").disabled = true;
      renameCurrentFolder(album.id, folder.id).catch((error) => {
        $("#correctionStatus").textContent = error.message;
        $("#saveFolderName").disabled = false;
      });
    }
  });

  $("#mergeFolder").addEventListener("click", () => {
    mergeCurrentFolder(album.id, folder.id).catch((error) => {
      $("#correctionStatus").textContent = error.message;
    });
  });

  $("#markNoFace").addEventListener("click", () => {
    markCurrentFolderNoFace(album.id, folder.id).catch((error) => {
      $("#correctionStatus").textContent = error.message;
    });
  });

  $("#deleteCurrentFolder").addEventListener("click", () => {
    deleteFolder(album.id, folder.id).catch((error) => {
      $("#correctionStatus").textContent = error.message;
    });
  });

  folderDetail.querySelectorAll(".detail-photo").forEach((button) => {
    button.addEventListener("click", () => {
      const photo = photos.find((item) => item.id === button.dataset.photoId);
      if (photo) openPhotoViewer(photo);
    });
  });

  folderDetail.querySelectorAll(".move-photo").forEach((button) => {
    button.addEventListener("click", () => {
      movePhotoToFolder(album.id, button.dataset.photoId).catch((error) => {
        $("#correctionStatus").textContent = error.message;
      });
    });
  });

  folderDetail.querySelectorAll(".delete-photo").forEach((button) => {
    button.addEventListener("click", () => {
      deletePhoto(album.id, button.dataset.photoId).catch((error) => {
        $("#correctionStatus").textContent = error.message;
      });
    });
  });
}

function renderAllPhotos(album) {
  if (!album.photos.length) {
    allPhotos.innerHTML = "";
    return;
  }

  const sortedPhotos = [...album.photos].sort((a, b) => b.createdAt - a.createdAt);
  allPhotos.innerHTML = `
    <div class="section-heading">
      <h3>全员底片池</h3>
      <p>${sortedPhotos.length} 张原始上传，点开看大图</p>
    </div>
    <div class="all-photo-grid">
      ${sortedPhotos
        .map(
          (photo) => `
            <article class="album-photo-card">
              <button class="album-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">
                <img src="${photo.cardUrl || photo.url}" alt="${escapeHtml(photo.originalName)}" loading="lazy" decoding="async" />
                <span>
                  <strong>${escapeHtml(photo.originalName)}</strong>
                  <small>${escapeHtml([photoStatusText(photo) || photoDisplayFolderNames(photo).join(" / "), photo.uploader].filter(Boolean).join(" · "))}</small>
                </span>
              </button>
              <button class="delete-photo-badge" type="button" data-photo-id="${escapeHtml(photo.id)}" aria-label="删除照片">删</button>
            </article>
          `,
        )
        .join("")}
    </div>
  `;

  allPhotos.querySelectorAll(".album-photo").forEach((button) => {
    button.addEventListener("click", () => {
      const photo = album.photos.find((item) => item.id === button.dataset.photoId);
      if (photo) openPhotoViewer(photo);
    });
  });
  allPhotos.querySelectorAll(".delete-photo-badge").forEach((badge) => {
    badge.addEventListener("click", () => {
      deletePhoto(album.id, badge.dataset.photoId).catch((error) => alert(error.message));
    });
  });
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
    $("#correctionStatus").textContent = "请选择要移动到的文件夹";
    return;
  }
  $("#correctionStatus").textContent = "正在把照片送回正确的小相册...";
  const payload = await api(`/api/albums/${pathPart(albumId)}/photos/${pathPart(photoId)}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ targetFolderId }),
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
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
  if (photoViewer.open && viewerImage.src.includes(photo.url)) {
    photoViewer.close();
  }
  render();
}

function openPhotoViewer(photo) {
  viewerImage.src = photo.url;
  viewerImage.alt = photo.originalName;
  viewerMeta.textContent = `${photo.originalName} · ${photo.uploader} · ${formatDate(photo.createdAt)}`;
  if (typeof photoViewer.showModal === "function") {
    photoViewer.showModal();
  } else {
    photoViewer.setAttribute("open", "");
  }
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
  albumName.value = "";
  render();
}

async function uploadPhotos(event) {
  event.preventDefault();
  const album = getCurrentAlbum();
  const files = Array.from(photosInput.files || []);
  if (!album || !files.length) return;

  state.uploading = true;
  uploadStatus.textContent = `正在接收 ${files.length} 张朋友视角，先入库，后分组`;
  uploadForm.querySelector("button[type='submit']").disabled = true;
  const form = new FormData();
  form.append("uploader", $("#uploader").value.trim() || "访客");
  for (const file of files) {
    form.append("photos", file);
  }

  try {
    const payload = await api(`/api/albums/${pathPart(album.id)}/upload`, {
      method: "POST",
      body: form,
    });
    state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
    state.lastUpload = {
      albumId: payload.album.id,
      photoIds: (payload.photos || []).map((photo) => photo.id),
    };
    photosInput.value = "";
    selectedFiles.textContent = defaultSelectedFilesText();
    uploadStatus.textContent = `收到 ${payload.queued || files.length} 张，已经放进照片池，后台开始分人`;
    render();
  } finally {
    state.uploading = false;
    uploadForm.querySelector("button[type='submit']").disabled = false;
  }
}

async function reanalyzeCurrentAlbum() {
  const album = getCurrentAlbum();
  if (!album || !album.photos.length) return;
  uploadStatus.textContent = "正在把整本照片池重新分一遍人...";
  reanalyzeButton.disabled = true;
  try {
    const payload = await api(`/api/albums/${pathPart(album.id)}/reanalyze`, {
      method: "POST",
    });
    state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
    state.currentFolderId = "";
    uploadStatus.textContent = "重新分组完成，可以看看每个人的照片包是否顺眼";
    render();
  } finally {
    reanalyzeButton.disabled = false;
    setTimeout(() => {
      uploadStatus.textContent = "";
    }, 2200);
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

copyShareLink.addEventListener("click", async () => {
  const url = window.location.href;
  try {
    await navigator.clipboard.writeText(url);
    shareLinkStatus.textContent = "已复制。发给同行朋友，让大家一起上传";
  } catch {
    shareLinkStatus.textContent = "复制失败，可以直接复制浏览器地址栏链接";
  }
  setTimeout(() => {
    shareLinkStatus.textContent = "同一 Wi-Fi 下打开更方便";
  }, 2600);
});

folders.addEventListener("click", (event) => {
  if (event.target.closest("a")) return;
  const folder = event.target.closest(".folder");
  if (!folder) return;
  state.currentFolderId = folder.dataset.folderId;
  render();
});

folders.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const folder = event.target.closest(".folder");
  if (!folder) return;
  event.preventDefault();
  state.currentFolderId = folder.dataset.folderId;
  render();
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
  if (Math.abs(dx) >= 80 && Math.abs(dy) <= 70) {
    backToFolderList();
  }
});

closeViewer.addEventListener("click", () => {
  photoViewer.close();
});

photoViewer.addEventListener("click", (event) => {
  if (event.target === photoViewer) {
    photoViewer.close();
  }
});

albumForm.addEventListener("submit", (event) => {
  createAlbum(event).catch((error) => alert(error.message));
});

uploadForm.addEventListener("submit", (event) => {
  uploadPhotos(event).catch((error) => {
    uploadStatus.textContent = error.message;
  });
});

reanalyzeButton.addEventListener("click", () => {
  reanalyzeCurrentAlbum().catch((error) => {
    uploadStatus.textContent = error.message;
    reanalyzeButton.disabled = false;
  });
});

loadAlbums().catch((error) => {
  stats.innerHTML = `<span class="stat">${escapeHtml(error.message)}</span>`;
});
