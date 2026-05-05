const state = {
  albums: [],
  currentAlbumId: "",
  currentFolderId: "",
  uploading: false,
  pollTimer: 0,
  lastUpload: null,
  touchStart: null,
  uploadExpanded: false,
  allPhotosOpen: false,
  allPhotosLimit: 12,
  viewerToken: 0,
  viewerPhotoId: "",
  viewerPhotos: [],
  viewerIndex: -1,
  viewerTouchStart: null,
};

const $ = (selector) => document.querySelector(selector);

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

async function loadAlbums() {
  const payload = await api("/api/albums");
  state.albums = payload.albums;
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
  state.allPhotosOpen = false;
  render();
}

function returnToHome() {
  state.currentAlbumId = "";
  state.currentFolderId = "";
  state.allPhotosOpen = false;
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
        return { folder, photo: coverPhoto };
      })
      .filter((item) => item.photo)
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
                    ({ folder, photo }) => `
                      <span class="home-face">
                        <img src="${folderCoverUrl(folder, photo)}" alt="${escapeHtml(folderDisplayName(folder))}" loading="lazy" decoding="async" />
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
      state.currentAlbumId = album.id;
      state.currentFolderId = "";
      state.allPhotosOpen = false;
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
      state.currentFolderId = folder.id;
      render();
    });
    albumList.appendChild(item);
  });
}

function render() {
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
  if (state.allPhotosOpen) {
    uploadForm.classList.add("hidden");
    toggleUploadForm.classList.add("hidden");
    folders.classList.add("hidden");
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
}

function renderFolderDetail(album, folder) {
  uploadForm.classList.add("hidden");
  toggleUploadForm.classList.add("hidden");
  allPhotos.classList.add("hidden");
  folders.classList.add("hidden");
  folderDetail.classList.remove("hidden");

  const photos = album.photos.filter((photo) => photoInFolder(photo, folder.id));
  const photoMoveTargets = album.folders.filter((item) => item.id !== folder.id);
  folderDetail.innerHTML = `
    <div class="detail-grid masonry">
      ${photos
        .map(
          (photo, index) => `
            <article class="detail-photo-card">
              <button class="detail-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">
                <img src="${photo.cardUrl || photo.url}" alt="${escapeHtml(photo.originalName)}" loading="${index < 6 ? "eager" : "lazy"}" decoding="async" />
                <span>
                  <strong>${escapeHtml(photo.uploader)}</strong>
                  <small>${formatDate(photo.createdAt)}</small>
                </span>
              </button>
              <button class="photo-menu-toggle" type="button" data-photo-id="${escapeHtml(photo.id)}" aria-label="更多操作">...</button>
              <div class="photo-correction">
                <select data-photo-target="${escapeHtml(photo.id)}" aria-label="移动照片到其他相册">
                  <option value="">移到...</option>
                  ${photoMoveTargets
                    .map((target) => `<option value="${escapeHtml(target.id)}">${escapeHtml(folderDisplayName(target))}</option>`)
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

  folderDetail.querySelectorAll(".detail-photo").forEach((button) => {
    button.addEventListener("click", () => {
      const photo = photos.find((item) => item.id === button.dataset.photoId);
      if (photo) openPhotoViewer(photo, photos);
    });
  });

  folderDetail.querySelectorAll(".photo-menu-toggle").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const card = button.closest(".detail-photo-card");
      const isOpen = card.classList.contains("menu-open");
      folderDetail.querySelectorAll(".detail-photo-card.menu-open").forEach((item) => {
        item.classList.remove("menu-open");
      });
      if (!isOpen) card.classList.add("menu-open");
    });
  });

  folderDetail.querySelectorAll(".photo-correction").forEach((panel) => {
    panel.addEventListener("click", (event) => {
      event.stopPropagation();
    });
  });

  folderDetail.querySelectorAll(".move-photo").forEach((button) => {
    button.addEventListener("click", () => {
      movePhotoToFolder(album.id, button.dataset.photoId).catch((error) => alert(error.message));
    });
  });

  folderDetail.querySelectorAll(".delete-photo").forEach((button) => {
    button.addEventListener("click", () => {
      deletePhoto(album.id, button.dataset.photoId).catch((error) => alert(error.message));
    });
  });

  folderDetail.onclick = (event) => {
    if (event.target.closest(".photo-menu-toggle") || event.target.closest(".photo-correction")) return;
    folderDetail.querySelectorAll(".detail-photo-card.menu-open").forEach((item) => {
      item.classList.remove("menu-open");
    });
  };
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
      state.allPhotosOpen = true;
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
    <div class="all-photo-grid masonry">
      ${visiblePhotos
        .map(
          (photo) => `
            <article class="album-photo-card">
              <button class="album-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">
                <img src="${photo.cardUrl || photo.url}" alt="${escapeHtml(photo.originalName)}" loading="lazy" decoding="async" />
                <span>
                  <strong>${escapeHtml(photo.uploader)}</strong>
                  <small>${formatDate(photo.createdAt)}</small>
                </span>
              </button>
              <button class="delete-photo-badge" type="button" data-photo-id="${escapeHtml(photo.id)}" aria-label="删除照片">删</button>
            </article>
          `,
        )
        .join("")}
    </div>
    ${
      hasMore
        ? `<button id="loadMorePhotos" class="secondary load-more-photos" type="button">再看 ${Math.min(12, sortedPhotos.length - visiblePhotos.length)} 张</button>`
        : `<p class="photo-end">已经到底啦</p>`
    }
  `;

  $("#backFromAllPhotos").addEventListener("click", () => {
    state.allPhotosOpen = false;
    render();
  });
  const loadMorePhotos = $("#loadMorePhotos");
  if (loadMorePhotos) {
    loadMorePhotos.addEventListener("click", () => {
      loadMoreAllPhotos();
    });
  }
  allPhotos.querySelectorAll(".album-photo").forEach((button) => {
    button.addEventListener("click", () => {
      const photo = album.photos.find((item) => item.id === button.dataset.photoId);
      if (photo) openPhotoViewer(photo, sortedPhotos);
    });
  });
  allPhotos.querySelectorAll(".delete-photo-badge").forEach((badge) => {
    badge.addEventListener("click", () => {
      deletePhoto(album.id, badge.dataset.photoId).catch((error) => alert(error.message));
    });
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
  viewerMeta.textContent = "正在打开原图...";
  if (!photoViewer.open && typeof photoViewer.showModal === "function") {
    photoViewer.showModal();
  } else if (!photoViewer.open) {
    photoViewer.setAttribute("open", "");
  }

  const nextImage = new Image();
  nextImage.onload = () => {
    if (state.viewerToken !== token) return;
    viewerImage.src = photo.url;
    viewerImage.alt = photo.originalName;
    viewerMeta.textContent = `${photo.originalName} · ${photo.uploader} · ${formatDate(photo.createdAt)}`;
    photoViewer.classList.remove("loading");
  };
  nextImage.onerror = () => {
    if (state.viewerToken !== token) return;
    viewerMeta.textContent = "原图加载失败，请稍后再试";
    photoViewer.classList.remove("loading");
  };
  nextImage.src = photo.url;
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
  albumName.value = "";
  if (createAlbumDialog.open) {
    createAlbumDialog.close();
  }
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

loadAlbums().catch((error) => {
  stats.innerHTML = `<span class="stat">${escapeHtml(error.message)}</span>`;
});
