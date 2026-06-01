package com.sharephotos.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.MediaController;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.VideoView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

public class MainActivity extends Activity {
    private static final int REQUEST_PICK_FILES = 1001;
    private static final int REQUEST_PICK_AVATAR = 1002;
    private static final String PRODUCTION_BASE_URL = "https://picme.me";
    private static final String PREFS = "picme-auth";
    private static final String CACHE_ALBUMS = "cache.albums";
    private static final String CACHE_USER = "cache.user";
    private static final int TEAL = Color.rgb(0, 128, 112);
    private static final int AQUA = Color.rgb(28, 194, 199);
    private static final int PRIMARY = Color.rgb(7, 22, 30);
    private static final int SECONDARY = Color.rgb(120, 134, 140);

    private SharedPreferences prefs;
    private LinearLayout root;
    private TextView statusText;
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText inviteCodeInput;
    private EditText uploadAlbumIdInput;
    private EditText uploaderInput;
    private EditText registerUsernameInput;
    private EditText registerNicknameInput;
    private EditText registerPasswordInput;
    private JSONArray albums = new JSONArray();
    private JSONObject currentUser;
    private String selectedAlbumId = "";
    private JSONObject currentAlbum;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        restoreCachedSessionData();
        if (hasLocalSession()) {
            showHome();
            loadAlbums();
            loadMe();
        } else {
            showLogin();
        }
        handleJoinIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleJoinIntent(intent);
    }

    private void showLogin() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackground(softBackground());
        root = vertical();
        root.setPadding(dp(28), dp(74), dp(28), dp(40));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setMinimumHeight(getResources().getDisplayMetrics().heightPixels);
        root.setBackground(softBackground());
        scroll.addView(root, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        addCenteredBrand(root, dp(82), 38, 17);
        spacer(dp(58));

        TextView title = text("登录", 40, PRIMARY, true);
        title.setGravity(Gravity.LEFT);
        root.addView(title, matchWrap());
        spacer(dp(22));

        usernameInput = field("  登录账号", false);
        passwordInput = field("  密码", true);
        root.addView(usernameInput, fieldParams());
        root.addView(passwordInput, fieldParams());

        TextView forgot = text("忘记密码？", 17, AQUA, true);
        forgot.setGravity(Gravity.RIGHT);
        LinearLayout.LayoutParams forgotParams = matchWrap();
        forgotParams.setMargins(0, 0, dp(4), dp(34));
        root.addView(forgot, forgotParams);

        Button login = primaryButton("登录");
        login.setOnClickListener(v -> login());
        LinearLayout.LayoutParams loginParams = matchWrap();
        loginParams.height = dp(68);
        loginParams.setMargins(0, 0, 0, dp(46));
        root.addView(login, loginParams);

        root.addView(dividerWithText("还没有账号？"), matchWrap());
        spacer(dp(22));

        Button createAccount = outlineButton("创建新账号");
        createAccount.setOnClickListener(v -> showRegisterDialog());
        LinearLayout.LayoutParams createParams = matchWrap();
        createParams.height = dp(64);
        root.addView(createAccount, createParams);

        statusText = text("准备好收朋友视角了", 14, SECONDARY, false);
        statusText.setGravity(Gravity.CENTER);
        statusText.setPadding(0, dp(26), 0, 0);
        root.addView(statusText, matchWrap());
        setContentView(scroll);
    }

    private void showHome() {
        FrameLayout frame = new FrameLayout(this);
        frame.setBackground(softBackground());
        ScrollView scroll = new ScrollView(this);
        root = vertical();
        root.setPadding(dp(22), dp(58), dp(22), dp(118));
        scroll.addView(root);
        frame.addView(scroll);

        LinearLayout top = horizontal();
        top.setGravity(Gravity.CENTER_VERTICAL);
        ImageView logo = new ImageView(this);
        logo.setImageResource(getResources().getIdentifier("picme_logo", "drawable", getPackageName()));
        top.addView(logo, new LinearLayout.LayoutParams(dp(58), dp(58)));
        LinearLayout brandBlock = vertical();
        LinearLayout brandRow = horizontal();
        brandRow.setGravity(Gravity.CENTER_VERTICAL);
        brandRow.addView(text("识我", 28, PRIMARY, true));
        TextView picme = text(" PicMe", 28, Color.rgb(97, 134, 220), true);
        brandRow.addView(picme);
        brandBlock.addView(brandRow, matchWrap());
        TextView slogan = text("自动找到属于你的旅行照片", 18, SECONDARY, true);
        brandBlock.addView(slogan, matchWrap());
        LinearLayout.LayoutParams brandParams = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        brandParams.setMargins(dp(14), 0, dp(12), 0);
        top.addView(brandBlock, brandParams);
        ImageView avatar = capsuleImage();
        avatar.setOnClickListener(v -> showProfileDialog());
        loadImageInto(currentUser == null ? "" : currentUser.optString("avatarUrl", ""), avatar);
        top.addView(avatar, new LinearLayout.LayoutParams(dp(58), dp(58)));
        root.addView(top, matchWrap());
        spacer(dp(40));

        TextView title = text("相册", 46, Color.BLACK, true);
        root.addView(title, matchWrap());
        statusText = text("正在同步你的相册", 15, SECONDARY, false);
        root.addView(statusText, matchWrap());
        spacer(dp(26));

        renderAlbums();

        Button joinButton = floatingButton("▣");
        joinButton.setTextSize(24);
        joinButton.setOnClickListener(v -> showJoinDialog(inviteCodeInput == null ? "" : inviteCodeInput.getText().toString()));
        FrameLayout.LayoutParams joinParams = new FrameLayout.LayoutParams(dp(64), dp(64), Gravity.BOTTOM | Gravity.RIGHT);
        joinParams.setMargins(0, 0, dp(24), dp(104));
        frame.addView(joinButton, joinParams);

        Button createButton = primaryButton("+  创建新相册");
        createButton.setOnClickListener(v -> showCreateAlbumDialog());
        FrameLayout.LayoutParams createParams = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(64), Gravity.BOTTOM);
        createParams.setMargins(dp(28), 0, dp(28), dp(22));
        frame.addView(createButton, createParams);

        setContentView(frame);
    }

    private void renderAlbums() {
        if (root == null) return;
        while (root.getChildCount() > 4) {
            root.removeViewAt(4);
        }
        if (albums.length() == 0) {
            LinearLayout empty = card();
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(dp(24), dp(52), dp(24), dp(52));
            TextView icon = text("▧", 54, AQUA, true);
            icon.setGravity(Gravity.CENTER);
            TextView title = text("暂无相册", 28, PRIMARY, true);
            title.setGravity(Gravity.CENTER);
            TextView hint = text("点下面的创建新相册，先开一个朋友照片局。", 16, SECONDARY, false);
            hint.setGravity(Gravity.CENTER);
            empty.addView(icon, matchWrap());
            empty.addView(title, matchWrap());
            empty.addView(hint, matchWrap());
            root.addView(empty, matchWrap());
            return;
        }
        TextView count = text(albums.length() + " 个一级相册", 19, SECONDARY, true);
        root.addView(count, matchWrap());
        for (int i = 0; i < albums.length(); i++) {
            JSONObject album = albums.optJSONObject(i);
            if (album != null) root.addView(albumCard(album), matchWrap());
        }
    }

    private View albumCard(JSONObject album) {
        LinearLayout card = card();
        card.setPadding(dp(22), dp(22), dp(22), dp(24));
        card.setOnClickListener(v -> {
            selectedAlbumId = album.optString("id");
            uploadAlbumIdInput = null;
            showAlbumDetail(album);
        });

        HorizontalScrollView scroller = new HorizontalScrollView(this);
        scroller.setHorizontalScrollBarEnabled(false);
        LinearLayout faces = horizontal();
        JSONArray folders = album.optJSONArray("folders");
        if (folders != null) {
            for (int i = 0; i < Math.min(6, folders.length()); i++) {
                JSONObject folder = folders.optJSONObject(i);
                if (folder == null) continue;
                LinearLayout item = vertical();
                item.setGravity(Gravity.CENTER);
                ImageView image = capsuleImage();
                String cover = folder.optString("coverUrl", "");
                if (cover.isEmpty()) cover = firstPhotoCover(album, folder);
                loadImageInto(cover, image);
                LinearLayout.LayoutParams imageParams = new LinearLayout.LayoutParams(dp(78), dp(96));
                imageParams.setMargins(0, 0, dp(8), 0);
                item.addView(image, imageParams);
                TextView name = text(folder.optString("name", "人物"), 14, SECONDARY, true);
                name.setGravity(Gravity.CENTER);
                item.addView(name, new LinearLayout.LayoutParams(dp(88), ViewGroup.LayoutParams.WRAP_CONTENT));
                faces.addView(item);
            }
        }
        scroller.addView(faces);
        card.addView(scroller, matchWrap());
        spacer(card, dp(18));

        TextView name = text(album.optString("name", "未命名相册"), 34, Color.BLACK, true);
        card.addView(name, matchWrap());
        String meta = safeArray(album, "photos").length() + " 张朋友视角 · " + safeArray(album, "contributors").length() + " 位参与者";
        TextView metaView = text(meta, 19, SECONDARY, true);
        metaView.setPadding(0, dp(10), 0, 0);
        card.addView(metaView, matchWrap());
        return card;
    }

    private void showAlbumDetail(JSONObject album) {
        selectedAlbumId = album.optString("id");
        currentAlbum = album;
        FrameLayout frame = new FrameLayout(this);
        frame.setBackground(softBackground());
        ScrollView scroll = new ScrollView(this);
        LinearLayout content = vertical();
        content.setPadding(dp(22), dp(56), dp(22), dp(118));
        scroll.addView(content);
        frame.addView(scroll);

        LinearLayout header = horizontal();
        header.setGravity(Gravity.CENTER_VERTICAL);
        Button back = ghostButton("‹ 返回");
        back.setTextSize(20);
        back.setOnClickListener(v -> showHome());
        header.addView(back);
        TextView date = text("PicMe 相册", 18, PRIMARY, true);
        date.setGravity(Gravity.CENTER);
        header.addView(date, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button share = ghostButton("分享");
        share.setOnClickListener(v -> shareAlbum(album));
        header.addView(share);
        content.addView(header, matchWrap());

        TextView title = text(album.optString("name", "未命名相册"), 38, Color.BLACK, true);
        content.addView(title, matchWrap());
        spacer(content, dp(14));
        LinearLayout stats = horizontal();
        stats.addView(statPill(safeArray(album, "photos").length() + " 张朋友视角"));
        stats.addView(statPill(safeArray(album, "folders").length() + " 个小相册"));
        stats.addView(statPill(safeArray(album, "contributors").length() + " 位参与者"));
        content.addView(stats, matchWrap());

        addTabRow(content, album);
        addSectionTitle(content, "我的照片", myPhotoCount(album) + " 张由头像匹配到的照片");
        LinearLayout myGrid = photoGrid(myPhotos(album), 6);
        content.addView(myGrid, matchWrap());

        addSectionTitle(content, "人物小相册", "按人脸自动整理");
        HorizontalScrollView folderScroller = new HorizontalScrollView(this);
        folderScroller.setHorizontalScrollBarEnabled(false);
        LinearLayout foldersRow = horizontal();
        JSONArray folders = album.optJSONArray("folders");
        if (folders != null) {
            for (int i = 0; i < folders.length(); i++) {
                JSONObject folder = folders.optJSONObject(i);
                if (folder == null) continue;
                LinearLayout item = vertical();
                item.setGravity(Gravity.CENTER);
                ImageView image = capsuleImage();
                String cover = folder.optString("coverUrl", "");
                if (cover.isEmpty()) cover = firstPhotoCover(album, folder);
                loadImageInto(cover, image);
                item.addView(image, new LinearLayout.LayoutParams(dp(74), dp(98)));
                TextView name = text(folder.optString("name", "人物"), 14, SECONDARY, true);
                name.setGravity(Gravity.CENTER);
                item.addView(name, new LinearLayout.LayoutParams(dp(88), ViewGroup.LayoutParams.WRAP_CONTENT));
                item.setOnClickListener(v -> showFolderDialog(album, folder));
                foldersRow.addView(item);
            }
        }
        folderScroller.addView(foldersRow);
        content.addView(folderScroller, matchWrap());

        addSectionTitle(content, "全部照片", "缩略图优先，原图按需下载");
        content.addView(photoGrid(safeArray(album, "photos"), 60), matchWrap());

        Button upload = primaryButton("+  上传照片");
        upload.setOnClickListener(v -> showAlbumActions(album));
        FrameLayout.LayoutParams uploadParams = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(64), Gravity.BOTTOM);
        uploadParams.setMargins(dp(28), 0, dp(28), dp(22));
        frame.addView(upload, uploadParams);
        setContentView(frame);
    }

    private void showAlbumActions(JSONObject album) {
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(8), dp(18), dp(8));
        uploadAlbumIdInput = field("相册 ID", false);
        uploadAlbumIdInput.setText(album.optString("id"));
        uploaderInput = field("上传者，不填则使用账号", false);
        if (currentUser != null) uploaderInput.setText(currentUser.optString("nickname"));
        panel.addView(text(album.optString("name", "相册"), 24, PRIMARY, true), matchWrap());
        panel.addView(uploadAlbumIdInput, matchWrap());
        panel.addView(uploaderInput, matchWrap());
        Button upload = primaryButton("选择照片 / 视频并直传 OSS");
        upload.setOnClickListener(v -> pickFiles());
        panel.addView(upload, matchWrap());
        new AlertDialog.Builder(this)
                .setView(panel)
                .setNegativeButton("关闭", null)
                .show();
    }

    private void showRegisterDialog() {
        LinearLayout panel = vertical();
        panel.setPadding(dp(22), dp(18), dp(22), dp(8));
        addCenteredBrand(panel, dp(62), 27, 14);
        spacer(panel, dp(20));
        TextView title = text("创建新账号", 30, PRIMARY, true);
        panel.addView(title, matchWrap());

        registerNicknameInput = field("  昵称（显示在相册中）", false);
        registerUsernameInput = field("  登录账号", false);
        registerPasswordInput = field("  密码", true);
        panel.addView(registerNicknameInput, fieldParams());
        panel.addView(registerUsernameInput, fieldParams());
        panel.addView(registerPasswordInput, fieldParams());

        Button create = primaryButton("创建并登录");
        create.setOnClickListener(v -> register());
        LinearLayout.LayoutParams createParams = matchWrap();
        createParams.height = dp(60);
        createParams.setMargins(0, dp(12), 0, 0);
        panel.addView(create, createParams);

        new AlertDialog.Builder(this)
                .setView(panel)
                .setNegativeButton("关闭", null)
                .show();
    }

    private void addTabRow(LinearLayout content, JSONObject album) {
        LinearLayout tabs = horizontal();
        tabs.setGravity(Gravity.CENTER);
        String[] labels = {
                "我的照片\n" + myPhotoCount(album),
                "人物小相册\n" + safeArray(album, "folders").length(),
                "全部照片\n" + safeArray(album, "photos").length()
        };
        for (int i = 0; i < labels.length; i++) {
            TextView tab = text(labels[i], 16, i == 0 ? Color.WHITE : PRIMARY, true);
            tab.setGravity(Gravity.CENTER);
            tab.setPadding(dp(8), dp(12), dp(8), dp(12));
            tab.setBackground(round(i == 0 ? TEAL : Color.WHITE, dp(14), Color.rgb(218, 246, 241), dp(1)));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(72), 1);
            params.setMargins(i == 0 ? 0 : dp(6), dp(18), i == labels.length - 1 ? 0 : dp(6), dp(10));
            tabs.addView(tab, params);
        }
        content.addView(tabs, matchWrap());
    }

    private void showProfileDialog() {
        LinearLayout panel = vertical();
        panel.setPadding(dp(20), dp(12), dp(20), dp(8));
        ImageView avatar = capsuleImage();
        loadImageInto(currentUser == null ? "" : currentUser.optString("avatarUrl", ""), avatar);
        panel.addView(avatar, new LinearLayout.LayoutParams(dp(86), dp(86)));

        TextView title = text(currentUser == null ? "我的资料" : currentUser.optString("nickname", "我的资料"), 25, PRIMARY, true);
        title.setGravity(Gravity.CENTER);
        panel.addView(title, matchWrap());

        EditText nickname = field("昵称", false);
        if (currentUser != null) nickname.setText(currentUser.optString("nickname", ""));
        panel.addView(nickname, matchWrap());

        Button saveNickname = primaryButton("保存昵称");
        saveNickname.setOnClickListener(v -> updateNickname(nickname.getText().toString()));
        panel.addView(saveNickname, matchWrap());

        Button uploadAvatar = ghostButton("更换头像");
        uploadAvatar.setOnClickListener(v -> pickAvatar());
        panel.addView(uploadAvatar, matchWrap());

        Button logoutButton = ghostButton("退出登录");
        logoutButton.setOnClickListener(v -> logout());
        panel.addView(logoutButton, matchWrap());

        new AlertDialog.Builder(this)
                .setView(panel)
                .setNegativeButton("关闭", null)
                .show();
    }

    private TextView statPill(String value) {
        TextView pill = text(value, 14, PRIMARY, true);
        pill.setGravity(Gravity.CENTER);
        pill.setPadding(dp(12), dp(10), dp(12), dp(10));
        pill.setBackground(round(Color.WHITE, dp(18), Color.TRANSPARENT, 0));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        params.setMargins(0, dp(8), dp(8), dp(8));
        pill.setLayoutParams(params);
        return pill;
    }

    private void addSectionTitle(LinearLayout content, String title, String subtitle) {
        spacer(content, dp(18));
        TextView header = text(title, 26, Color.BLACK, true);
        content.addView(header, matchWrap());
        TextView sub = text(subtitle, 15, SECONDARY, true);
        content.addView(sub, matchWrap());
    }

    private void showFolderDialog(JSONObject album, JSONObject folder) {
        LinearLayout panel = vertical();
        panel.setPadding(dp(12), dp(6), dp(12), dp(6));
        panel.addView(text(folder.optString("name", "小相册"), 24, PRIMARY, true), matchWrap());
        panel.addView(photoGrid(folderPhotos(album, folder), 30), matchWrap());
        new AlertDialog.Builder(this)
                .setView(panel)
                .setNegativeButton("关闭", null)
                .show();
    }

    private LinearLayout photoGrid(JSONArray photos, int limit) {
        LinearLayout wrapper = vertical();
        if (photos == null || photos.length() == 0) {
            TextView empty = text("暂时还没有照片", 15, SECONDARY, false);
            empty.setPadding(0, dp(12), 0, dp(12));
            wrapper.addView(empty, matchWrap());
            return wrapper;
        }
        LinearLayout row = null;
        int count = Math.min(limit, photos.length());
        for (int i = 0; i < count; i++) {
            if (i % 3 == 0) {
                row = horizontal();
                wrapper.addView(row, matchWrap());
            }
            JSONObject photo = photos.optJSONObject(i);
            FrameLayout cell = new FrameLayout(this);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(126), 1);
            params.setMargins(dp(1), dp(1), dp(1), dp(1));
            cell.setLayoutParams(params);
            ImageView image = new ImageView(this);
            image.setScaleType(ImageView.ScaleType.CENTER_CROP);
            image.setBackground(placeholderDrawable());
            cell.addView(image, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            if (photo != null) {
                loadImageInto(bestPhotoURL(photo), image);
                if ("live_photo".equals(photo.optString("type"))) {
                    TextView badge = text("◎ LIVE", 12, Color.WHITE, true);
                    badge.setGravity(Gravity.CENTER);
                    badge.setBackground(round(Color.argb(145, 0, 0, 0), dp(16), Color.TRANSPARENT, 0));
                    FrameLayout.LayoutParams badgeParams = new FrameLayout.LayoutParams(dp(72), dp(30), Gravity.LEFT | Gravity.BOTTOM);
                    badgeParams.setMargins(dp(8), 0, 0, dp(8));
                    cell.addView(badge, badgeParams);
                }
                final int photoIndex = i;
                cell.setOnClickListener(v -> showPhotoViewer(photos, photoIndex));
            }
            row.addView(cell);
        }
        return wrapper;
    }

    private void showPhotoPreview(JSONObject photo) {
        JSONArray single = new JSONArray();
        single.put(photo);
        showPhotoViewer(single, 0);
    }

    private void showPhotoViewer(final JSONArray photos, final int startIndex) {
        if (photos == null || photos.length() == 0) return;
        final int index = Math.max(0, Math.min(startIndex, photos.length() - 1));
        final JSONObject photo = photos.optJSONObject(index);
        if (photo == null) return;

        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(Color.BLACK);
        LinearLayout content = vertical();
        content.setGravity(Gravity.CENTER_HORIZONTAL);
        frame.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout header = horizontal();
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(12), dp(18), dp(12), dp(8));
        Button back = ghostButton("‹ 返回");
        back.setOnClickListener(v -> {
            JSONObject album = currentAlbum != null ? currentAlbum : findAlbumById(selectedAlbumId);
            if (album != null) showAlbumDetail(album);
            else showHome();
        });
        header.addView(back);
        TextView counter = text((index + 1) + " / " + photos.length(), 16, Color.WHITE, true);
        counter.setGravity(Gravity.CENTER);
        header.addView(counter, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button close = ghostButton("关闭");
        close.setOnClickListener(v -> showHome());
        header.addView(close);
        content.addView(header, matchWrap());

        ImageView image = new ImageView(this);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        loadImageInto(photo.optString("previewUrl", photo.optString("imageUrl", bestPhotoURL(photo))), image);
        content.addView(image, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        addSwipeNavigation(image, photos, index);

        LinearLayout actions = horizontal();
        actions.setGravity(Gravity.CENTER);
        Button previous = ghostButton("上一张");
        previous.setEnabled(index > 0);
        previous.setOnClickListener(v -> showPhotoViewer(photos, index - 1));
        Button next = ghostButton("下一张");
        next.setEnabled(index < photos.length() - 1);
        next.setOnClickListener(v -> showPhotoViewer(photos, index + 1));
        actions.addView(previous, new LinearLayout.LayoutParams(0, dp(46), 1));
        actions.addView(next, new LinearLayout.LayoutParams(0, dp(46), 1));
        content.addView(actions, matchWrap());

        if ("live_photo".equals(photo.optString("type"))) {
            Button live = primaryButton("◎  播放 Live Photo");
            live.setOnClickListener(v -> playLiveVideo(photo, frame));
            LinearLayout.LayoutParams liveParams = matchWrap();
            liveParams.setMargins(dp(28), dp(8), dp(28), dp(18));
            content.addView(live, liveParams);
        }
        setContentView(frame);
    }

    private void addSwipeNavigation(View target, JSONArray photos, int index) {
        final float[] downX = new float[1];
        target.setOnTouchListener((view, event) -> {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                downX[0] = event.getX();
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_UP) {
                float delta = event.getX() - downX[0];
                if (Math.abs(delta) > dp(56)) {
                    if (delta < 0 && index < photos.length() - 1) showPhotoViewer(photos, index + 1);
                    if (delta > 0 && index > 0) showPhotoViewer(photos, index - 1);
                    return true;
                }
            }
            return true;
        });
    }

    private void playLiveVideo(JSONObject photo, FrameLayout frame) {
        TextView loading = text("正在加载 Live Photo...", 18, Color.WHITE, true);
        loading.setGravity(Gravity.CENTER);
        frame.addView(loading, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        new Thread(() -> {
            try {
                String videoUrl = liveVideoURL(photo);
                if (videoUrl.isEmpty()) throw new IllegalStateException("没有可播放的视频资源");
                runOnUiThread(() -> {
                    frame.removeView(loading);
                    VideoView video = new VideoView(this);
                    video.setVideoURI(Uri.parse(absoluteURL(videoUrl)));
                    MediaController controller = new MediaController(this);
                    controller.setAnchorView(video);
                    video.setMediaController(controller);
                    video.setOnPreparedListener(MediaPlayer::start);
                    frame.addView(video, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
                    video.start();
                });
            } catch (final Exception error) {
                runOnUiThread(() -> {
                    frame.removeView(loading);
                    if (statusText != null) statusText.setText("Live Photo 预览失败：" + error.getMessage());
                });
            }
        }).start();
    }

    private String liveVideoURL(JSONObject photo) throws Exception {
        String direct = photo.optString("videoUrl", "");
        if (!direct.isEmpty()) return direct;
        String manifestPath = photo.optString("downloadLiveUrl", "");
        if (manifestPath.isEmpty()) return "";
        JSONObject manifest = requestJson("GET", manifestPath, null, true, true);
        JSONObject video = manifest.optJSONObject("video");
        return video == null ? "" : video.optString("url", "");
    }

    private void shareAlbum(final JSONObject album) {
        statusText.setText("正在生成分享链接...");
        new Thread(() -> {
            try {
                JSONObject response = requestJson("POST", "/api/albums/" + album.optString("id") + "/invite", new JSONObject(), true, true);
                JSONObject invite = response.optJSONObject("invite");
                final String shareUrl = invite == null ? "" : invite.optString("shareUrl", "");
                runOnUiThread(() -> {
                    Intent intent = new Intent(Intent.ACTION_SEND);
                    intent.setType("text/plain");
                    intent.putExtra(Intent.EXTRA_TEXT, "加入 PicMe 相册：" + album.optString("name") + "\n" + shareUrl);
                    startActivity(Intent.createChooser(intent, "分享相册"));
                    statusText.setText("分享链接已生成");
                });
            } catch (final Exception error) {
                showError("分享失败", error);
            }
        }).start();
    }

    private int myPhotoCount(JSONObject album) {
        if (album.has("myPhotoCount")) return album.optInt("myPhotoCount");
        return safeArray(album, "myPhotoIds").length();
    }

    private JSONArray myPhotos(JSONObject album) {
        JSONArray idsArray = safeArray(album, "myPhotoIds");
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < idsArray.length(); i++) ids.add(idsArray.optString(i));
        if (ids.isEmpty()) return new JSONArray();
        JSONArray result = new JSONArray();
        JSONArray photos = safeArray(album, "photos");
        for (int i = 0; i < photos.length(); i++) {
            JSONObject photo = photos.optJSONObject(i);
            if (photo != null && ids.contains(photo.optString("id"))) result.put(photo);
        }
        return result;
    }

    private JSONArray folderPhotos(JSONObject album, JSONObject folder) {
        JSONArray idsArray = safeArray(folder, "photoIds");
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < idsArray.length(); i++) ids.add(idsArray.optString(i));
        JSONArray result = new JSONArray();
        JSONArray photos = safeArray(album, "photos");
        for (int i = 0; i < photos.length(); i++) {
            JSONObject photo = photos.optJSONObject(i);
            if (photo != null && ids.contains(photo.optString("id"))) result.put(photo);
        }
        return result;
    }

    private String bestPhotoURL(JSONObject photo) {
        String[] keys = {"thumbnailUrl", "tinyUrl", "coverUrl", "previewUrl", "imageUrl"};
        for (String key : keys) {
            String value = photo.optString(key, "");
            if (!value.isEmpty()) return value;
        }
        return "";
    }

    private JSONArray safeArray(JSONObject object, String key) {
        JSONArray array = object == null ? null : object.optJSONArray(key);
        return array == null ? new JSONArray() : array;
    }

    private JSONObject findAlbumById(String albumId) {
        if (albumId == null || albumId.isEmpty()) return null;
        for (int i = 0; i < albums.length(); i++) {
            JSONObject album = albums.optJSONObject(i);
            if (album != null && albumId.equals(album.optString("id"))) return album;
        }
        return null;
    }

    private void showCreateAlbumDialog() {
        EditText name = field("例如：重庆周末小队", false);
        name.setPadding(dp(16), dp(12), dp(16), dp(12));
        new AlertDialog.Builder(this)
                .setTitle("这次出游叫什么")
                .setView(name)
                .setNegativeButton("取消", null)
                .setPositiveButton("创建", (dialog, which) -> createAlbum(name.getText().toString()))
                .show();
    }

    private void showJoinDialog(String preset) {
        inviteCodeInput = field("相册码或分享链接", false);
        inviteCodeInput.setText(inviteCodeFrom(preset));
        new AlertDialog.Builder(this)
                .setTitle("加入相册")
                .setMessage("扫描微信里的分享链接后会自动带入相册码，也可以手动输入。")
                .setView(inviteCodeInput)
                .setNegativeButton("取消", null)
                .setPositiveButton("申请加入", (dialog, which) -> requestJoinFromInput())
                .show();
    }

    private void handleJoinIntent(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data == null) return;
        String code = inviteCodeFrom(data.toString());
        if (!code.isEmpty()) {
            if (hasLocalSession()) {
                showJoinDialog(code);
            } else {
                showLogin();
                statusText.setText("已识别相册码：" + code + "，登录后可申请加入。");
                inviteCodeInput = field("相册码或分享链接", false);
                inviteCodeInput.setText(code);
            }
        }
    }

    private void login() {
        final String username = usernameInput.getText().toString().trim();
        final String password = passwordInput.getText().toString();
        if (username.isEmpty() || password.isEmpty()) {
            statusText.setText("请填写账号和密码");
            return;
        }
        statusText.setText("正在登录...");
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("username", username);
                body.put("password", password);
                JSONObject response = requestJson("POST", "/api/auth/login", body, false, false);
                saveTokens(response);
                currentUser = response.optJSONObject("user");
                cacheCurrentUser();
                runOnUiThread(() -> {
                    showHome();
                    statusText.setText("欢迎回来，" + (currentUser == null ? username : currentUser.optString("nickname", username)));
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError("登录失败", error);
            }
        }).start();
    }

    private void register() {
        final String username = registerUsernameInput == null ? "" : registerUsernameInput.getText().toString().trim();
        final String nickname = registerNicknameInput == null ? "" : registerNicknameInput.getText().toString().trim();
        final String password = registerPasswordInput == null ? "" : registerPasswordInput.getText().toString();
        if (username.isEmpty() || nickname.isEmpty() || password.isEmpty()) {
            statusText.setText("请填写昵称、账号和密码");
            return;
        }
        statusText.setText("正在创建账号...");
        new Thread(() -> {
            try {
                JSONObject response = registerRequest(username, nickname, password);
                saveTokens(response);
                currentUser = response.optJSONObject("user");
                cacheCurrentUser();
                runOnUiThread(() -> {
                    showHome();
                    statusText.setText("欢迎加入 PicMe，" + nickname);
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError("创建账号失败", error);
            }
        }).start();
    }

    private void logout() {
        prefs.edit().clear().apply();
        albums = new JSONArray();
        selectedAlbumId = "";
        currentUser = null;
        showLogin();
        statusText.setText("已退出登录");
    }

    private void loadMe() {
        new Thread(() -> {
            try {
                JSONObject response = requestJson("GET", "/api/me", null, true, true);
                currentUser = response.optJSONObject("user");
                cacheCurrentUser();
            } catch (Exception ignored) {
            }
        }).start();
    }

    private void loadAlbums() {
        if (statusText != null) statusText.setText("正在同步相册...");
        new Thread(() -> {
            try {
                final JSONObject response = requestJson("GET", "/api/albums", null, true, true);
                albums = response.optJSONArray("albums");
                if (albums == null) albums = new JSONArray();
                if (albums.length() > 0) selectedAlbumId = albums.optJSONObject(0).optString("id");
                cacheAlbums();
                runOnUiThread(() -> {
                    renderAlbums();
                    statusText.setText(albums.length() == 0 ? "暂无相册" : "已同步 " + albums.length() + " 个相册");
                });
            } catch (final Exception error) {
                showError("读取相册失败", error);
            }
        }).start();
    }

    private void createAlbum(final String rawName) {
        final String name = rawName == null ? "" : rawName.trim();
        if (name.isEmpty()) {
            statusText.setText("先给这次出游起个名字");
            return;
        }
        statusText.setText("正在创建相册...");
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("name", name);
                requestJson("POST", "/api/albums", body, true, true);
                runOnUiThread(() -> {
                    statusText.setText("已创建 " + name);
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError("创建失败", error);
            }
        }).start();
    }

    private void updateNickname(final String rawNickname) {
        final String nickname = rawNickname == null ? "" : rawNickname.trim();
        if (nickname.isEmpty()) {
            statusText.setText("昵称不能为空");
            return;
        }
        statusText.setText("正在保存昵称...");
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("nickname", nickname);
                JSONObject response = requestJson("POST", "/api/me/profile", body, true, true);
                currentUser = response.optJSONObject("user");
                cacheCurrentUser();
                runOnUiThread(() -> {
                    showHome();
                    statusText.setText("昵称已更新");
                });
            } catch (final Exception error) {
                showError("保存昵称失败", error);
            }
        }).start();
    }

    private void requestJoinFromInput() {
        final String code = inviteCodeFrom(inviteCodeInput == null ? "" : inviteCodeInput.getText().toString());
        if (code.isEmpty()) {
            statusText.setText("请填写相册码或分享链接");
            return;
        }
        statusText.setText("正在提交加入申请...");
        new Thread(() -> {
            try {
                requestJson("GET", "/api/invites/" + code, null, true, true);
                requestJson("POST", "/api/invites/" + code + "/request", new JSONObject(), true, true);
                runOnUiThread(() -> statusText.setText("已提交加入申请，等待相册管理员审批"));
            } catch (final Exception error) {
                showError("申请加入失败", error);
            }
        }).start();
    }

    private void pickFiles() {
        if (selectedAlbumId.isEmpty() && uploadAlbumIdInput != null) {
            selectedAlbumId = uploadAlbumIdInput.getText().toString().trim();
        }
        if (selectedAlbumId.isEmpty()) {
            statusText.setText("请先选择一个相册");
            return;
        }
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"image/*", "video/*", "application/octet-stream"});
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(intent, REQUEST_PICK_FILES);
    }

    private void pickAvatar() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        startActivityForResult(intent, REQUEST_PICK_AVATAR);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_PICK_AVATAR && resultCode == RESULT_OK && data != null && data.getData() != null) {
            statusText.setText("头像已选择，正在上传识别...");
            final Uri avatarUri = data.getData();
            new Thread(() -> {
                try {
                    uploadAvatar(avatarUri, true);
                    runOnUiThread(() -> {
                        showHome();
                        statusText.setText("头像已更新，后台正在匹配你的照片");
                        loadAlbums();
                    });
                } catch (final Exception error) {
                    showError("头像上传失败", error);
                }
            }).start();
            return;
        }
        if (requestCode != REQUEST_PICK_FILES || resultCode != RESULT_OK || data == null) return;
        final List<Uri> uris = new ArrayList<>();
        if (data.getClipData() != null) {
            for (int i = 0; i < data.getClipData().getItemCount(); i++) {
                uris.add(data.getClipData().getItemAt(i).getUri());
            }
        } else if (data.getData() != null) {
            uris.add(data.getData());
        }
        statusText.setText("正在准备直传 " + uris.size() + " 个文件...");
        new Thread(() -> {
            try {
                directUpload(uris);
                runOnUiThread(() -> {
                    statusText.setText("上传完成，后台开始整理");
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError("上传失败", error);
            }
        }).start();
    }

    private void directUpload(List<Uri> uris) throws Exception {
        String uploader = uploaderInput == null ? "" : uploaderInput.getText().toString().trim();
        if (uploader.isEmpty() && currentUser != null) uploader = currentUser.optString("nickname");
        if (uploader.isEmpty()) uploader = "Android";
        Map<String, Uri> uriById = new HashMap<>();
        JSONArray files = new JSONArray();
        for (int i = 0; i < uris.size(); i++) {
            Uri uri = uris.get(i);
            String name = displayName(uri);
            String clientFileId = "android-" + i + "-" + UUID.randomUUID();
            uriById.put(clientFileId, uri);
            JSONObject item = new JSONObject();
            item.put("clientFileId", clientFileId);
            item.put("clientAssetId", assetIdFromName(name));
            item.put("name", name);
            item.put("mimeType", contentType(uri, name));
            item.put("fileSize", fileSize(uri));
            files.put(item);
        }
        JSONObject initBody = new JSONObject();
        initBody.put("files", files);
        JSONObject init = requestJson("POST", "/api/albums/" + selectedAlbumId + "/uploads/init", initBody, true, true);
        JSONArray uploads = init.optJSONArray("uploads");
        if (uploads == null || uploads.length() == 0) throw new IllegalStateException("没有可上传的文件");
        for (int i = 0; i < uploads.length(); i++) {
            JSONObject upload = uploads.getJSONObject(i);
            putSignedResource(upload.getJSONObject("image"), uriById);
            if (!upload.isNull("video")) putSignedResource(upload.getJSONObject("video"), uriById);
        }
        JSONObject completeBody = new JSONObject();
        completeBody.put("uploader", uploader);
        completeBody.put("uploads", uploads);
        requestJson("POST", "/api/albums/" + selectedAlbumId + "/uploads/complete", completeBody, true, true);
    }

    private void uploadAvatar(Uri uri, boolean retryRefresh) throws Exception {
        String boundary = "PicMeBoundary" + UUID.randomUUID();
        HttpURLConnection connection = (HttpURLConnection) new URL(PRODUCTION_BASE_URL + "/api/me/avatar").openConnection();
        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        String token = prefs.getString("accessToken", "");
        if (!token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);

        OutputStream output = connection.getOutputStream();
        String filename = displayName(uri);
        String mimeType = contentType(uri, filename);
        output.write(("--" + boundary + "\r\n").getBytes("UTF-8"));
        output.write(("Content-Disposition: form-data; name=\"avatar\"; filename=\"" + filename + "\"\r\n").getBytes("UTF-8"));
        output.write(("Content-Type: " + mimeType + "\r\n\r\n").getBytes("UTF-8"));
        InputStream input = getContentResolver().openInputStream(uri);
        if (input == null) throw new IllegalStateException("无法读取头像文件");
        byte[] buffer = new byte[1024 * 64];
        int read;
        while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
        input.close();
        output.write(("\r\n--" + boundary + "--\r\n").getBytes("UTF-8"));
        output.flush();
        output.close();

        int code = connection.getResponseCode();
        String text = readAll(code >= 400 ? connection.getErrorStream() : connection.getInputStream(), "");
        if (code == 401 && retryRefresh && refreshTokens()) {
            uploadAvatar(uri, false);
            return;
        }
        if (code < 200 || code >= 300) throw new IllegalStateException(text.isEmpty() ? ("请求失败：" + code) : text);
        JSONObject response = text.isEmpty() ? new JSONObject() : new JSONObject(text);
        currentUser = response.optJSONObject("user");
        cacheCurrentUser();
    }

    private JSONObject registerRequest(String username, String nickname, String password) throws Exception {
        String boundary = "PicMeBoundary" + UUID.randomUUID();
        HttpURLConnection connection = (HttpURLConnection) new URL(PRODUCTION_BASE_URL + "/api/auth/register").openConnection();
        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        OutputStream output = connection.getOutputStream();
        writeFormField(output, boundary, "username", username);
        writeFormField(output, boundary, "nickname", nickname);
        writeFormField(output, boundary, "password", password);
        output.write(("--" + boundary + "--\r\n").getBytes("UTF-8"));
        output.flush();
        output.close();
        int code = connection.getResponseCode();
        String text = readAll(code >= 400 ? connection.getErrorStream() : connection.getInputStream(), "");
        if (code < 200 || code >= 300) throw new IllegalStateException(text.isEmpty() ? ("请求失败：" + code) : text);
        return text.isEmpty() ? new JSONObject() : new JSONObject(text);
    }

    private void writeFormField(OutputStream output, String boundary, String name, String value) throws Exception {
        output.write(("--" + boundary + "\r\n").getBytes("UTF-8"));
        output.write(("Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n").getBytes("UTF-8"));
        output.write((value + "\r\n").getBytes("UTF-8"));
    }

    private void putSignedResource(JSONObject resource, Map<String, Uri> uriById) throws Exception {
        Uri uri = uriById.get(resource.optString("clientFileId"));
        if (uri == null) throw new IllegalStateException("找不到本地文件：" + resource.optString("originalName"));
        HttpURLConnection connection = (HttpURLConnection) new URL(resource.getString("uploadUrl")).openConnection();
        connection.setRequestMethod("PUT");
        connection.setDoOutput(true);
        JSONObject headers = resource.optJSONObject("headers");
        if (headers != null) {
            JSONArray names = headers.names();
            if (names != null) {
                for (int i = 0; i < names.length(); i++) {
                    String key = names.getString(i);
                    connection.setRequestProperty(key, headers.optString(key));
                }
            }
        }
        String mimeType = resource.optString("mimeType");
        if (!mimeType.isEmpty()) connection.setRequestProperty("Content-Type", mimeType);
        OutputStream output = connection.getOutputStream();
        InputStream input = getContentResolver().openInputStream(uri);
        if (input == null) throw new IllegalStateException("无法读取 " + resource.optString("originalName"));
        byte[] buffer = new byte[1024 * 64];
        int read;
        while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
        input.close();
        output.flush();
        output.close();
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) throw new IllegalStateException(readAll(connection.getErrorStream(), "OSS 上传失败：" + code));
    }

    private JSONObject requestJson(String method, String path, JSONObject body, boolean auth, boolean retryRefresh) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(PRODUCTION_BASE_URL + path).openConnection();
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept", "application/json");
        if (auth) {
            String token = prefs.getString("accessToken", "");
            if (!token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);
        }
        if (body != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            OutputStream output = connection.getOutputStream();
            output.write(body.toString().getBytes("UTF-8"));
            output.close();
        }
        int code = connection.getResponseCode();
        String text = readAll(code >= 400 ? connection.getErrorStream() : connection.getInputStream(), "");
        if (code == 401 && auth && retryRefresh && refreshTokens()) return requestJson(method, path, body, true, false);
        if (code < 200 || code >= 300) throw new IllegalStateException(text.isEmpty() ? ("请求失败：" + code) : text);
        return text.isEmpty() ? new JSONObject() : new JSONObject(text);
    }

    private boolean refreshTokens() {
        String refreshToken = prefs.getString("refreshToken", "");
        if (refreshToken.isEmpty()) return false;
        try {
            JSONObject body = new JSONObject();
            body.put("refreshToken", refreshToken);
            JSONObject response = requestJson("POST", "/api/auth/refresh", body, false, false);
            saveTokens(response);
            return true;
        } catch (Exception ignored) {
            prefs.edit().remove("accessToken").remove("refreshToken").apply();
            return false;
        }
    }

    private void saveTokens(JSONObject response) {
        SharedPreferences.Editor editor = prefs.edit();
        if (response.has("accessToken")) editor.putString("accessToken", response.optString("accessToken"));
        if (response.has("refreshToken")) editor.putString("refreshToken", response.optString("refreshToken"));
        if (response.has("token")) editor.putString("accessToken", response.optString("token"));
        editor.apply();
    }

    private boolean hasLocalSession() {
        return !prefs.getString("accessToken", "").isEmpty() || !prefs.getString("refreshToken", "").isEmpty();
    }

    private void restoreCachedSessionData() {
        try {
            String cachedAlbums = prefs.getString(CACHE_ALBUMS, "");
            if (!cachedAlbums.isEmpty()) albums = new JSONArray(cachedAlbums);
        } catch (Exception ignored) {
            albums = new JSONArray();
        }
        try {
            String cachedUser = prefs.getString(CACHE_USER, "");
            if (!cachedUser.isEmpty()) currentUser = new JSONObject(cachedUser);
        } catch (Exception ignored) {
            currentUser = null;
        }
        if (albums.length() > 0 && selectedAlbumId.isEmpty()) {
            JSONObject first = albums.optJSONObject(0);
            if (first != null) selectedAlbumId = first.optString("id");
        }
    }

    private void cacheAlbums() {
        prefs.edit().putString(CACHE_ALBUMS, albums.toString()).apply();
    }

    private void cacheCurrentUser() {
        if (currentUser != null) prefs.edit().putString(CACHE_USER, currentUser.toString()).apply();
    }

    private String firstPhotoCover(JSONObject album, JSONObject folder) {
        JSONArray photoIds = folder.optJSONArray("photoIds");
        JSONArray photos = album.optJSONArray("photos");
        if (photoIds == null || photos == null) return "";
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < photoIds.length(); i++) ids.add(photoIds.optString(i));
        for (int i = 0; i < photos.length(); i++) {
            JSONObject photo = photos.optJSONObject(i);
            if (photo != null && ids.contains(photo.optString("id"))) {
                String[] keys = {"faceUrl", "coverUrl", "thumbnailUrl", "previewUrl", "imageUrl"};
                for (String key : keys) {
                    String value = photo.optString(key, "");
                    if (!value.isEmpty()) return value;
                }
            }
        }
        return "";
    }

    private void loadImageInto(String path, ImageView target) {
        target.setImageDrawable(placeholderDrawable());
        String absolute = absoluteURL(path);
        if (absolute.isEmpty()) return;
        new Thread(() -> {
            try {
                HttpURLConnection connection = (HttpURLConnection) new URL(absolute).openConnection();
                connection.setRequestMethod("GET");
                InputStream input = connection.getInputStream();
                final Bitmap bitmap = BitmapFactory.decodeStream(input);
                input.close();
                if (bitmap != null) runOnUiThread(() -> target.setImageBitmap(bitmap));
            } catch (Exception ignored) {
            }
        }).start();
    }

    private String absoluteURL(String path) {
        if (path == null || path.isEmpty()) return "";
        if (path.startsWith("http://") || path.startsWith("https://")) return path;
        return PRODUCTION_BASE_URL + (path.startsWith("/") ? path : "/" + path);
    }

    private String inviteCodeFrom(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) return "";
        int index = value.indexOf("/join/");
        if (index >= 0) value = value.substring(index + 6);
        int query = value.indexOf('?');
        if (query >= 0) value = value.substring(0, query);
        int slash = value.indexOf('/');
        if (slash >= 0) value = value.substring(0, slash);
        return value.replaceAll("[^A-Za-z0-9_-]", "").toUpperCase();
    }

    private String assetIdFromName(String filename) {
        int dot = filename.lastIndexOf('.');
        return dot > 0 ? filename.substring(0, dot).toLowerCase() : filename.toLowerCase();
    }

    private String displayName(Uri uri) {
        Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null);
        if (cursor != null) {
            try {
                if (cursor.moveToFirst()) {
                    int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    if (index >= 0) return cursor.getString(index);
                }
            } finally {
                cursor.close();
            }
        }
        return "upload-" + System.currentTimeMillis();
    }

    private long fileSize(Uri uri) {
        Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.SIZE}, null, null, null);
        if (cursor != null) {
            try {
                if (cursor.moveToFirst()) {
                    int index = cursor.getColumnIndex(OpenableColumns.SIZE);
                    if (index >= 0) return cursor.getLong(index);
                }
            } finally {
                cursor.close();
            }
        }
        return 0;
    }

    private String contentType(Uri uri, String filename) {
        String mimeType = getContentResolver().getType(uri);
        if (mimeType != null) return mimeType;
        String lower = filename.toLowerCase();
        if (lower.endsWith(".heic") || lower.endsWith(".heif")) return "image/heic";
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
        if (lower.endsWith(".png")) return "image/png";
        if (lower.endsWith(".mov")) return "video/quicktime";
        if (lower.endsWith(".mp4")) return "video/mp4";
        return "application/octet-stream";
    }

    private String readAll(InputStream input, String fallback) throws Exception {
        if (input == null) return fallback;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int read;
        while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
        return output.toString("UTF-8");
    }

    private void showError(final String prefix, final Exception error) {
        runOnUiThread(() -> {
            if (statusText != null) statusText.setText(prefix + "：" + (error.getMessage() == null ? "未知错误" : error.getMessage()));
        });
    }

    private LinearLayout vertical() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    private LinearLayout horizontal() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        return layout;
    }

    private TextView text(String value, int sp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setIncludeFontPadding(true);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private EditText field(String hint, boolean password) {
        EditText editText = new EditText(this);
        editText.setHint(hint);
        editText.setSingleLine(true);
        editText.setTextColor(PRIMARY);
        editText.setHintTextColor(SECONDARY);
        editText.setTextSize(17);
        editText.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        editText.setPadding(dp(22), dp(10), dp(22), dp(10));
        editText.setBackground(round(Color.argb(242, 255, 255, 255), dp(22), Color.rgb(215, 232, 235), dp(1)));
        if (password) editText.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(0, dp(12), 0, dp(12));
        editText.setLayoutParams(params);
        return editText;
    }

    private Button primaryButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(Color.WHITE);
        button.setTextSize(20);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setAllCaps(false);
        button.setBackground(round(TEAL, dp(28), TEAL, 0));
        return button;
    }

    private Button outlineButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(AQUA);
        button.setTextSize(18);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setAllCaps(false);
        button.setBackground(round(Color.argb(235, 255, 255, 255), dp(28), AQUA, dp(2)));
        return button;
    }

    private Button ghostButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(TEAL);
        button.setAllCaps(false);
        button.setBackground(round(Color.WHITE, dp(20), Color.TRANSPARENT, 0));
        return button;
    }

    private Button floatingButton(String label) {
        Button button = ghostButton(label);
        button.setBackground(round(Color.WHITE, dp(32), Color.TRANSPARENT, 0));
        return button;
    }

    private LinearLayout card() {
        LinearLayout layout = vertical();
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(0, dp(12), 0, dp(12));
        layout.setLayoutParams(params);
        layout.setBackground(round(Color.argb(238, 255, 255, 255), dp(24), Color.rgb(218, 246, 241), dp(1)));
        return layout;
    }

    private ImageView capsuleImage() {
        ImageView image = new ImageView(this);
        image.setScaleType(ImageView.ScaleType.CENTER_CROP);
        image.setPadding(dp(2), dp(2), dp(2), dp(2));
        image.setBackground(round(Color.WHITE, dp(32), Color.WHITE, dp(3)));
        return image;
    }

    private void addCenteredBrand(LinearLayout parent, int logoSize, int titleSp, int subtitleSp) {
        ImageView logo = new ImageView(this);
        logo.setImageResource(getResources().getIdentifier("picme_logo", "drawable", getPackageName()));
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(logoSize, logoSize);
        logoParams.gravity = Gravity.CENTER_HORIZONTAL;
        parent.addView(logo, logoParams);
        spacer(parent, dp(22));

        LinearLayout brand = horizontal();
        brand.setGravity(Gravity.CENTER);
        brand.addView(text("识我", titleSp, PRIMARY, true));
        brand.addView(text(" PicMe", titleSp, Color.rgb(98, 132, 220), true));
        parent.addView(brand, matchWrap());

        TextView subtitle = text("自动找到属于你的旅行照片", subtitleSp, SECONDARY, true);
        subtitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subtitleParams = matchWrap();
        subtitleParams.setMargins(0, dp(8), 0, 0);
        parent.addView(subtitle, subtitleParams);
    }

    private View dividerWithText(String label) {
        LinearLayout row = horizontal();
        row.setGravity(Gravity.CENTER);
        View left = new View(this);
        left.setBackgroundColor(Color.rgb(225, 227, 221));
        row.addView(left, new LinearLayout.LayoutParams(0, dp(1), 1));
        TextView middle = text(label, 17, SECONDARY, true);
        middle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(dp(150), ViewGroup.LayoutParams.WRAP_CONTENT);
        row.addView(middle, textParams);
        View right = new View(this);
        right.setBackgroundColor(Color.rgb(225, 227, 221));
        row.addView(right, new LinearLayout.LayoutParams(0, dp(1), 1));
        return row;
    }

    private LinearLayout.LayoutParams fieldParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.height = dp(72);
        params.setMargins(0, 0, 0, dp(18));
        return params;
    }

    private GradientDrawable placeholderDrawable() {
        return round(Color.rgb(229, 241, 242), dp(32), Color.WHITE, dp(2));
    }

    private GradientDrawable softBackground() {
        return new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(255, 251, 240), Color.rgb(235, 250, 248), Color.rgb(255, 242, 226)}
        );
    }

    private GradientDrawable round(int color, int radius, int strokeColor, int strokeWidth) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(radius);
        if (strokeWidth > 0) drawable.setStroke(strokeWidth, strokeColor);
        return drawable;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private void spacer(int height) {
        View view = new View(this);
        root.addView(view, new LinearLayout.LayoutParams(1, height));
    }

    private void spacer(LinearLayout parent, int height) {
        View view = new View(this);
        parent.addView(view, new LinearLayout.LayoutParams(1, height));
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
