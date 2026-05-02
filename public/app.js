const state = {
  albums: [],
  currentAlbumId: "",
  currentFolderId: "",
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
const reanalyzeButton = $("#reanalyzeButton");
const allPhotos = $("#allPhotos");
const folders = $("#folders");
const folderDetail = $("#folderDetail");
const photoViewer = $("#photoViewer");
const viewerImage = $("#viewerImage");
const viewerMeta = $("#viewerMeta");
const closeViewer = $("#closeViewer");

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
  const payload = await api(`/api/albums/${state.currentAlbumId}`);
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

function pickFolderCoverPhoto(folder, photos) {
  if (folder.id === "group-photo" || folder.id === "no-face") {
    return photos[0];
  }
  return photos.find((photo) => photoFolderIds(photo).length === 1) || photos[0];
}

function render() {
  albumList.innerHTML = "";
  state.albums.forEach((album) => {
    const button = document.createElement("button");
    button.className = `album-item${album.id === state.currentAlbumId ? " active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <strong>${escapeHtml(album.name)}</strong>
      <span>${album.photos.length} 张照片 · ${album.contributors.length} 位上传者</span>
    `;
    button.addEventListener("click", () => {
      state.currentAlbumId = album.id;
      state.currentFolderId = "";
      render();
    });
    albumList.appendChild(button);
  });

  const album = getCurrentAlbum();
  if (!album) {
    currentAlbumTitle.textContent = "请选择或创建一个相册";
    stats.innerHTML = "";
    emptyState.classList.remove("hidden");
    albumPanel.classList.add("hidden");
    return;
  }

  currentAlbumTitle.textContent = album.name;
  emptyState.classList.add("hidden");
  albumPanel.classList.remove("hidden");
  stats.innerHTML = `
    <span class="stat">${album.photos.length} 张照片</span>
    <span class="stat">${album.folders.length} 个人物文件夹</span>
    <span class="stat">${album.contributors.length} 位协作者</span>
  `;
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
          <p>上传后系统会自动创建人物文件夹。多个浏览器或多台设备访问同一个局域网地址即可协作上传。</p>
        </div>
      </section>
    `;
    return;
  }

  folders.innerHTML = "";
  folders.insertAdjacentHTML(
    "beforeend",
    `<div class="section-heading"><h3>人物分类文件夹</h3><p>${album.folders.length} 个文件夹</p></div>`,
  );
  album.folders.forEach((folder) => {
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
    section.setAttribute("aria-label", `查看 ${folder.name}`);
    section.innerHTML = `
      <div class="folder-header">
        <div class="folder-title">
          <h3>${escapeHtml(folder.name)}</h3>
          <p>${photos.length} 张 · 最近 ${formatDate(Math.max(...photos.map((photo) => photo.createdAt)))}</p>
        </div>
        <a href="/api/albums/${album.id}/folders/${folder.id}/download" aria-label="下载 ${escapeHtml(folder.name)}">
          <button class="secondary" type="button">下载</button>
        </a>
      </div>
      ${
        coverPhoto
          ? `
            <figure class="folder-cover">
              <img src="${coverPhoto.url}" alt="${escapeHtml(coverPhoto.originalName)}" loading="lazy" />
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
                <img src="${photo.url}" alt="${escapeHtml(photo.originalName)}" loading="lazy" />
                <span>${escapeHtml(photo.uploader)}</span>
              </figure>
            `,
          )
          .join("")}
      </div>
      <button class="open-folder" type="button" data-folder-id="${escapeHtml(folder.id)}">查看全部</button>
    `;
    folders.appendChild(section);
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
        <h3>${escapeHtml(folder.name)}</h3>
        <p>${photos.length} 张照片 · 在线查看</p>
      </div>
      <a href="/api/albums/${album.id}/folders/${folder.id}/download">
        <button type="button">下载文件夹</button>
      </a>
    </div>
    <div class="correction-panel">
      <div>
        <strong>识别纠错</strong>
        <span>同一个人被拆开时可合并；误识别人物时可标记为未识别人脸。</span>
      </div>
      <div class="correction-actions">
        <select id="mergeTarget" ${mergeTargets.length ? "" : "disabled"}>
          <option value="">选择要合并到的文件夹</option>
          ${mergeTargets.map((target) => `<option value="${escapeHtml(target.id)}">${escapeHtml(target.name)}</option>`).join("")}
        </select>
        <button id="mergeFolder" class="secondary" type="button" ${mergeTargets.length ? "" : "disabled"}>合并</button>
        <button id="markNoFace" class="secondary danger" type="button" ${folder.id === "no-face" ? "disabled" : ""}>标记为未识别人脸</button>
      </div>
      <span id="correctionStatus"></span>
    </div>
    <div class="detail-grid">
      ${photos
        .map(
          (photo) => `
            <article class="detail-photo-card">
              <button class="detail-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">
                <img src="${photo.url}" alt="${escapeHtml(photo.originalName)}" loading="lazy" />
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
                <button class="secondary move-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">移动</button>
                <button class="secondary reclassify-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">重新识别</button>
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;

  $("#backToFolders").addEventListener("click", () => {
    state.currentFolderId = "";
    render();
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

  folderDetail.querySelectorAll(".reclassify-photo").forEach((button) => {
    button.addEventListener("click", () => {
      reclassifyPhoto(album.id, button.dataset.photoId).catch((error) => {
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
      <h3>全部照片</h3>
      <p>${sortedPhotos.length} 张上传照片</p>
    </div>
    <div class="all-photo-grid">
      ${sortedPhotos
        .map(
          (photo) => `
            <button class="album-photo" type="button" data-photo-id="${escapeHtml(photo.id)}">
              <img src="${photo.url}" alt="${escapeHtml(photo.originalName)}" loading="lazy" />
              <span>
                <strong>${escapeHtml(photo.originalName)}</strong>
                <small>${escapeHtml(photoFolderNames(photo).join(" / "))} · ${escapeHtml(photo.uploader)}</small>
              </span>
            </button>
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
}

async function mergeCurrentFolder(albumId, sourceFolderId) {
  const targetFolderId = $("#mergeTarget").value;
  if (!targetFolderId) {
    $("#correctionStatus").textContent = "请选择目标文件夹";
    return;
  }
  $("#correctionStatus").textContent = "正在合并...";
  const payload = await api(`/api/albums/${albumId}/folders/${sourceFolderId}/merge`, {
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
  const payload = await api(`/api/albums/${albumId}/folders/${sourceFolderId}/mark-no-face`, {
    method: "POST",
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  const noFaceFolder = payload.album.folders.find((folder) => folder.id === "no-face" || folder.name === "未识别人脸");
  state.currentFolderId = noFaceFolder ? noFaceFolder.id : "";
  render();
}

async function movePhotoToFolder(albumId, photoId) {
  const select = folderDetail.querySelector(`[data-photo-target="${CSS.escape(photoId)}"]`);
  const targetFolderId = select ? select.value : "";
  if (!targetFolderId) {
    $("#correctionStatus").textContent = "请选择要移动到的文件夹";
    return;
  }
  $("#correctionStatus").textContent = "正在移动照片...";
  const payload = await api(`/api/albums/${albumId}/photos/${photoId}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ targetFolderId }),
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  render();
}

async function reclassifyPhoto(albumId, photoId) {
  $("#correctionStatus").textContent = "正在重新识别...";
  const payload = await api(`/api/albums/${albumId}/photos/${photoId}/reclassify`, {
    method: "POST",
  });
  state.albums = state.albums.map((album) => (album.id === payload.album.id ? payload.album : album));
  const updatedAlbum = payload.album;
  const movedPhoto = updatedAlbum.photos.find((photo) => photo.id === photoId);
  state.currentFolderId = movedPhoto ? photoFolderIds(movedPhoto)[0] : state.currentFolderId;
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

  uploadStatus.textContent = "上传中，服务端正在识别人脸...";
  const form = new FormData();
  form.append("uploader", $("#uploader").value.trim() || "访客");
  for (const file of files) {
    form.append("photos", file);
  }

  await api(`/api/albums/${album.id}/upload`, {
    method: "POST",
    body: form,
  });
  photosInput.value = "";
  selectedFiles.textContent = "上传后自动进行人脸识别";
  uploadStatus.textContent = "已完成人脸识别整理";
  await refreshCurrentAlbum();
  setTimeout(() => {
    uploadStatus.textContent = "";
  }, 1800);
}

async function reanalyzeCurrentAlbum() {
  const album = getCurrentAlbum();
  if (!album || !album.photos.length) return;
  uploadStatus.textContent = "正在使用高精度模型重新分析相册...";
  reanalyzeButton.disabled = true;
  try {
    const payload = await api(`/api/albums/${album.id}/reanalyze`, {
      method: "POST",
    });
    state.albums = state.albums.map((item) => (item.id === payload.album.id ? payload.album : item));
    state.currentFolderId = "";
    uploadStatus.textContent = "已完成高精度重新分析";
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
  selectedFiles.textContent = count ? `已选择 ${count} 张照片` : "上传后自动进行人脸识别";
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
