package com.sharephotos.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.graphics.drawable.ColorDrawable;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.provider.MediaStore;
import android.text.InputType;
import android.util.LruCache;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.MediaController;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.VideoView;

import org.json.JSONArray;
import org.json.JSONObject;

import com.google.zxing.BinaryBitmap;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatWriter;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.NotFoundException;
import com.google.zxing.RGBLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.WriterException;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.common.BitMatrix;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.EnumMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

public class MainActivity extends Activity {
    private static final int REQUEST_PICK_FILES = 1001;
    private static final int REQUEST_PICK_AVATAR = 1002;
    private static final int REQUEST_PICK_QR_IMAGE = 1003;
    private static final int REQUEST_CAPTURE_QR = 1004;
    private static final int REQUEST_CAMERA_PERMISSION = 1005;
    private static final int REQUEST_PICK_REGISTER_AVATAR = 1006;
    private static final int REQUEST_WRITE_EXTERNAL_STORAGE = 1007;
    private static final int REQUEST_POST_NOTIFICATIONS = 1008;
    private static final String PRODUCTION_BASE_URL = "https://picme.me";
    private static final String PREFS = "picme-auth";
    private static final String CACHE_ALBUMS = "cache.albums";
    private static final String CACHE_USER = "cache.user";
    private static final int TEAL = Color.rgb(0, 128, 112);
    private static final int AQUA = Color.rgb(28, 194, 199);
    private static final int PRIMARY = Color.rgb(7, 22, 30);
    private static final int SECONDARY = Color.rgb(120, 134, 140);
    private static final long TRANSIENT_STATUS_MS = 4000L;

    private SharedPreferences prefs;
    private LinearLayout root;
    private TextView statusText;
    private TextView messageBadge;
    private Dialog messageDialog;
    private Dialog managementDialog;
    private String activeManagementPageTitle = "";
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText inviteCodeInput;
    private String pendingJoinCode = "";
    private String loginNoticeText = "";
    private String pendingUploader = "";
    private EditText registerUsernameInput;
    private EditText registerNicknameInput;
    private EditText registerPasswordInput;
    private EditText registerConfirmPasswordInput;
    private ImageView registerAvatarPreview;
    private Uri registerAvatarUri;
    private JSONArray albums = new JSONArray();
    private JSONObject currentUser;
    private JSONObject pendingNotificationMessage;
    private JSONObject pendingMessageRoute;
    private String selectedAlbumId = "";
    private String currentScreen = "login";
    private String photoReturnScreen = "album";
    private JSONObject currentAlbum;
    private String activeFolderId = "";
    private String activeAlbumTab = "my";
    private boolean photoSelectionMode = false;
    private boolean livePhotoPlaying = false;
    private PhotoDiskCache diskCache;
    private Set<String> selectedPhotoIds = new HashSet<>();
    private int unreadMessageCount = 0;
    private volatile boolean isUploading = false;
    private volatile String activeUploadAlbumId = "";
    private String pendingUploadAlbumId = "";
    private volatile boolean uploadCancelRequested = false;
    private volatile int uploadSelectedCount = 0;
    private volatile int uploadUploadedCount = 0;
    private volatile String uploadProgressText = "";
    private final Set<String> uploadBaselinePhotoIds = new HashSet<>();
    private final Set<String> uploadCreatedPhotoIds = new HashSet<>();
    private volatile int albumRecognitionPollRevision = 0;
    private volatile int avatarRecognitionPollRevision = 0;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private boolean transientStatusVisible = false;
    private View transientStatusView;
    private Runnable transientStatusAction;
    private final Runnable clearTransientStatusRunnable = () -> clearTransientStatus(false);
    private Runnable pendingInvitePermissionSave;
    private Runnable pendingLegacyWriteAction;
    private final Map<String, Runnable> pendingMemberPermissionSaves = new HashMap<>();
    private final LruCache<String, Bitmap> imageCache = new LruCache<String, Bitmap>(32 * 1024) {
        @Override
        protected int sizeOf(String key, Bitmap value) {
            return Math.max(1, value.getByteCount() / 1024);
        }
    };
    private Drawable transientPreviousBackground = null;
    private int transientPreviousTextColor = SECONDARY;
    private Typeface transientPreviousTypeface = Typeface.DEFAULT;
    private int transientPreviousPaddingLeft = 0;
    private int transientPreviousPaddingTop = 0;
    private int transientPreviousPaddingRight = 0;
    private int transientPreviousPaddingBottom = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        restoreCachedSessionData();
        if (hasLocalSession()) {
            // 先显示中性启动加载页(splash),在后台单线程里顺序校验会话后再决定进主页还是登录页,
            // 避免"先渲染主页壳再异步校验"导致会话失效时闪现残缺中间态(QA #9)。
            showSplash();
            bootstrapSession();
        } else {
            MessageNotificationJobService.cancel(this);
            showLogin();
        }
        handleJoinIntent(getIntent());
        handleNotificationIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleJoinIntent(intent);
        handleNotificationIntent(intent);
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        if (transientStatusVisible
                && (event.getActionMasked() == MotionEvent.ACTION_DOWN || event.getActionMasked() == MotionEvent.ACTION_MOVE)) {
            boolean keepForClickableTap = transientStatusAction != null
                    && event.getActionMasked() == MotionEvent.ACTION_DOWN
                    && isTouchInsideStatus(event);
            if (!keepForClickableTap) {
                clearTransientStatus(true);
            }
        }
        return super.dispatchTouchEvent(event);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if ("register".equals(currentScreen)) {
            showLogin();
        } else if ("photo".equals(currentScreen)) {
            showCurrentAlbumOrHome();
        } else if ("folder".equals(currentScreen)) {
            JSONObject album = currentAlbum != null ? currentAlbum : findAlbumById(selectedAlbumId);
            if (album != null) showAlbumDetail(album);
            else showHome();
        } else if ("album".equals(currentScreen)) {
            showHome();
        } else {
            finish();
        }
    }

    private void showLogin() {
        currentScreen = "login";
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
        boolean hasLoginNotice = loginNoticeText != null && !loginNoticeText.trim().isEmpty();
        spacer(dp(hasLoginNotice ? 26 : 58));

        TextView title = text("登录", 40, PRIMARY, true);
        title.setGravity(Gravity.START);
        root.addView(title, matchWrap());
        spacer(dp(22));

        if (hasLoginNotice) {
            TextView notice = text(loginNoticeText.trim(), 16, TEAL, true);
            notice.setPadding(dp(14), dp(12), dp(14), dp(12));
            notice.setBackground(round(Color.argb(242, 255, 255, 255), dp(18), Color.rgb(205, 244, 244), dp(2)));
            LinearLayout.LayoutParams noticeParams = matchWrap();
            noticeParams.setMargins(0, 0, 0, dp(18));
            root.addView(notice, noticeParams);
        }

        usernameInput = field("  登录账号", false);
        passwordInput = field("  密码", true);
        root.addView(usernameInput, fieldParams());
        root.addView(passwordInput, fieldParams());

        TextView forgot = text("忘记密码？", 17, AQUA, true);
        forgot.setGravity(Gravity.END);
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
        currentScreen = "home";
        FrameLayout frame = new FrameLayout(this);
        frame.setBackground(softBackground());
        ScrollView scroll = new ScrollView(this);
        root = vertical();
        root.setPadding(dp(18), dp(24), dp(18), dp(124));
        scroll.addView(root);
        frame.addView(scroll);

        LinearLayout top = horizontal();
        top.setGravity(Gravity.CENTER_VERTICAL);
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.picme_logo);
        top.addView(logo, new LinearLayout.LayoutParams(dp(58), dp(58)));
        LinearLayout brandBlock = vertical();
        LinearLayout brandRow = horizontal();
        brandRow.setGravity(Gravity.CENTER_VERTICAL);
        brandRow.addView(text("识我", 28, PRIMARY, true));
        TextView picme = text(" PicMe", 28, Color.rgb(97, 134, 220), true);
        brandRow.addView(picme);
        brandBlock.addView(brandRow, matchWrap());
        TextView slogan = text("自动找到属于你的旅行照片", 13, SECONDARY, true);
        slogan.setMaxLines(1);
        slogan.setEllipsize(android.text.TextUtils.TruncateAt.END);
        brandBlock.addView(slogan, matchWrap());
        LinearLayout.LayoutParams brandParams = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
        brandParams.setMargins(dp(14), 0, dp(12), 0);
        top.addView(brandBlock, brandParams);
        FrameLayout messageBtn = new FrameLayout(this);
        messageBtn.setBackground(round(Color.argb(235, 255, 255, 255), dp(27), Color.argb(30, 0, 128, 112), dp(1)));
        messageBtn.setElevation(dp(3));
        messageBtn.setContentDescription("消息提醒");
        messageBtn.setOnClickListener(v -> showMessageCenter());
        ImageView bell = new ImageView(this);
        bell.setImageResource(R.drawable.ic_bell);
        messageBtn.addView(bell, new FrameLayout.LayoutParams(dp(26), dp(26), Gravity.CENTER));
        messageBadge = text("", 11, Color.WHITE, true);
        messageBadge.setGravity(Gravity.CENTER);
        messageBadge.setMinWidth(dp(18));
        messageBadge.setMinHeight(dp(18));
        messageBadge.setPadding(dp(4), 0, dp(4), 0);
        messageBadge.setBackground(round(Color.rgb(230, 74, 83), dp(9), Color.WHITE, dp(1)));
        FrameLayout.LayoutParams badgeParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.END);
        badgeParams.setMargins(0, dp(2), dp(2), 0);
        messageBtn.addView(messageBadge, badgeParams);
        LinearLayout.LayoutParams messageParams = new LinearLayout.LayoutParams(dp(54), dp(54));
        messageParams.setMargins(0, 0, dp(8), 0);
        top.addView(messageBtn, messageParams);
        updateMessageBadge();
        ImageView avatar = capsuleImage();
        avatar.setContentDescription("我的资料");
        avatar.setOnClickListener(v -> showProfileDialog());
        loadImageInto(currentUser == null ? "" : currentUser.optString("avatarUrl", ""), avatar);
        top.addView(avatar, new LinearLayout.LayoutParams(dp(54), dp(54)));
        root.addView(top, matchWrap());
        spacer(dp(24));

        TextView title = text("相册", 38, Color.BLACK, true);
        root.addView(title, matchWrap());
        statusText = text("正在同步你的相册", 15, SECONDARY, false);
        root.addView(statusText, matchWrap());
        spacer(dp(26));

        renderAlbums();

        FrameLayout joinButton = new FrameLayout(this);
        joinButton.setBackground(round(Color.argb(240, 255, 255, 255), dp(32), Color.TRANSPARENT, 0));
        joinButton.setElevation(dp(4));
        joinButton.setContentDescription("扫码加入相册");
        joinButton.setOnClickListener(v -> showJoinDialog(inviteCodeInput == null ? "" : inviteCodeInput.getText().toString()));
        ImageView qrIcon = new ImageView(this);
        qrIcon.setImageResource(R.drawable.ic_qr_scan);
        joinButton.addView(qrIcon, new FrameLayout.LayoutParams(dp(28), dp(28), Gravity.CENTER));
        FrameLayout.LayoutParams joinParams = new FrameLayout.LayoutParams(dp(64), dp(64), Gravity.BOTTOM | Gravity.END);
        joinParams.setMargins(0, 0, dp(24), dp(104));
        frame.addView(joinButton, joinParams);

        Button createButton = primaryButton("+  创建新相册");
        createButton.setOnClickListener(v -> showCreateAlbumDialog());
        FrameLayout.LayoutParams createParams = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(64), Gravity.BOTTOM);
        createParams.setMargins(dp(28), 0, dp(28), dp(22));
        frame.addView(createButton, createParams);

        setContentView(frame);
        loadUnreadMessageCount();
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
        card.setPadding(dp(18), dp(18), dp(18), dp(18));
        final View.OnClickListener openAlbum = v -> {
            selectedAlbumId = album.optString("id");
            activeAlbumTab = "my";
            clearPhotoSelection();
            showAlbumDetail(album);
            refreshAlbumDetail(album.optString("id"));
        };
        card.setOnClickListener(openAlbum);
        card.setOnLongClickListener(v -> {
            showAlbumContextActions(album);
            return true;
        });

        HorizontalScrollView scroller = new HorizontalScrollView(this);
        scroller.setHorizontalScrollBarEnabled(false);
        // 顶部人物封面横条会拦截触摸用于滚动，setOnClickListener 对它不可靠；
        // 改用触摸监听：位移很小判定为"轻点"则进相册，返回 false 不消费、保留横条滚动。
        final float[] scrollerDown = new float[2];
        scroller.setOnTouchListener((v, event) -> {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                scrollerDown[0] = event.getX();
                scrollerDown[1] = event.getY();
            } else if (event.getAction() == MotionEvent.ACTION_UP) {
                if (Math.abs(event.getX() - scrollerDown[0]) < dp(10)
                        && Math.abs(event.getY() - scrollerDown[1]) < dp(10)) {
                    openAlbum.onClick(v);
                }
            }
            return false;
        });
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
                LinearLayout.LayoutParams imageParams = new LinearLayout.LayoutParams(dp(64), dp(88));
                imageParams.setMargins(0, 0, dp(14), 0);
                item.addView(image, imageParams);
                TextView name = text(folder.optString("name", "人物"), 14, SECONDARY, true);
                name.setGravity(Gravity.CENTER);
                item.addView(name, new LinearLayout.LayoutParams(dp(78), ViewGroup.LayoutParams.WRAP_CONTENT));
                faces.addView(item);
            }
        }
        scroller.addView(faces);
        card.addView(scroller, matchWrap());
        spacer(card, dp(18));

        TextView name = text(album.optString("name", "未命名相册"), 30, Color.BLACK, true);
        card.addView(name, matchWrap());
        String meta = safeArray(album, "photos").length() + " 张朋友视角 · " + safeArray(album, "contributors").length() + " 位参与者";
        TextView metaView = text(meta, 17, SECONDARY, true);
        metaView.setPadding(0, dp(10), 0, 0);
        card.addView(metaView, matchWrap());
        return card;
    }

    private void showAlbumContextActions(JSONObject album) {
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle(album.optString("name", "相册"))
                .setNegativeButton("取消", null);
        if (canEditMembers(album)) {
            builder.setItems(new String[]{"重命名相册", "删除相册"}, (dialog, which) -> {
                if (which == 0) showRenameAlbumDialog(album);
                else confirmDeleteOrLeaveAlbum(album);
            });
        } else {
            builder.setItems(new String[]{"退出相册"}, (dialog, which) -> confirmDeleteOrLeaveAlbum(album));
        }
        builder.show();
    }

    private void showAlbumDetail(JSONObject album) {
        currentScreen = "album";
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
        ImageView share = new ImageView(this);
        share.setImageResource(R.drawable.ic_share);
        share.setContentDescription("分享相册");
        share.setPadding(dp(10), dp(10), dp(10), dp(10));
        share.setOnClickListener(v -> {
            if (permissionAllowed(album, "share")) shareAlbum(album);
            else showPermissionDenied(album, "分享", "share");
        });
        header.addView(share, new LinearLayout.LayoutParams(dp(46), dp(46)));
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
        if ("people".equals(activeAlbumTab)) {
            addSectionTitle(content, "人物小相册", safeArray(album, "folders").length() + " 个可下载小相册");
            content.addView(folderGrid(album), matchWrap());
        } else if ("all".equals(activeAlbumTab)) {
            addSectionTitle(content, "全部照片", "缩略图优先，原图按需下载");
            addPhotoSelectionToolbar(content, album, safeArray(album, "photos"));
            content.addView(photoGrid(safeArray(album, "photos"), 60), matchWrap());
        } else {
            addSectionTitle(content, "我的照片", myPhotoCount(album) + " 张由头像匹配到的照片");
            JSONArray visible = myPhotos(album);
            addPhotoSelectionToolbar(content, album, visible);
            content.addView(photoGrid(visible, 60), matchWrap());
        }

        spacer(content, dp(16));
        LinearLayout actionRow = horizontal();
        actionRow.setGravity(Gravity.CENTER);
        addActionButton(actionRow, "分享相册", R.drawable.ic_share, () -> {
            if (permissionAllowed(album, "share")) shareAlbum(album);
            else showPermissionDenied(album, "分享", "share");
        });
        addActionButton(actionRow, "协作用户", R.drawable.ic_people, () -> showAlbumMembers(album));
        addActionButton(actionRow, "协作记录", R.drawable.ic_history, () -> showCollaborationRecords(album));
        if (!canEditMembers(album)) {
            addActionButton(actionRow, "申请权限", R.drawable.ic_key, () -> showPermissionRequestDialog(album, ""));
        }
        if (isAdmin(album)) {
            addActionButton(actionRow, "审批", R.drawable.ic_person_add, () -> showApprovalCenter(album));
        }
        content.addView(actionRow, matchWrap());

        if (canEditMembers(album)) {
            Button rename = ghostButton("重命名相册");
            rename.setOnClickListener(v -> showRenameAlbumDialog(album));
            content.addView(rename, matchWrap());
        }

        Button destructive = ghostButton(canEditMembers(album) ? "删除整个相册" : "退出这个相册");
        destructive.setTextColor(Color.rgb(230, 74, 83));
        destructive.setOnClickListener(v -> confirmDeleteOrLeaveAlbum(album));
        LinearLayout.LayoutParams destructiveParams = matchWrap();
        destructiveParams.setMargins(0, dp(12), 0, dp(10));
        content.addView(destructive, destructiveParams);

        View upload = albumUploadControl(album);
        FrameLayout.LayoutParams uploadParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                isUploadingToAlbum(album) ? dp(104) : dp(64),
                Gravity.BOTTOM
        );
        uploadParams.setMargins(dp(28), 0, dp(28), dp(22));
        frame.addView(upload, uploadParams);
        setContentView(frame);
    }

    private View albumUploadControl(final JSONObject album) {
        boolean uploadingHere = isUploadingToAlbum(album);
        LinearLayout control = vertical();
        control.setGravity(Gravity.CENTER_VERTICAL);
        control.setPadding(dp(20), uploadingHere ? dp(12) : 0, dp(20), uploadingHere ? dp(12) : 0);
        control.setBackground(round(TEAL, dp(28), TEAL, 0));
        control.setElevation(dp(5));
        control.setClickable(true);
        control.setOnClickListener(v -> {
            if (!permissionAllowed(album, "upload")) {
                showPermissionDenied(album, "上传", "upload");
            } else if (uploadingHere) {
                confirmCancelUpload();
            } else if (isUploading) {
                showTransientStatus("另一个相册正在上传照片，请等待完成或回到该相册取消上传");
            } else {
                showUploadDialog(album);
            }
        });
        if (!uploadingHere) {
            TextView title = text("+  上传照片", 20, Color.WHITE, true);
            title.setGravity(Gravity.CENTER);
            control.addView(title, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
            return control;
        }

        LinearLayout header = horizontal();
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.addView(text("正在上传照片", 17, Color.WHITE, true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        int progress = uploadProgressPercent();
        header.addView(text(progress + "%", 17, Color.WHITE, true), matchWrap());
        control.addView(header, matchWrap());

        ProgressBar progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setProgress(progress);
        progressBar.setProgressTintList(ColorStateList.valueOf(Color.WHITE));
        progressBar.setProgressBackgroundTintList(ColorStateList.valueOf(Color.argb(95, 255, 255, 255)));
        LinearLayout.LayoutParams progressParams = matchWrap();
        progressParams.height = dp(8);
        progressParams.setMargins(0, dp(8), 0, dp(6));
        control.addView(progressBar, progressParams);

        TextView detail = text(
                uploadProgressText == null || uploadProgressText.isEmpty()
                        ? "点击可取消本次上传"
                        : uploadProgressText + "，点击可取消",
                12,
                Color.WHITE,
                true
        );
        detail.setMaxLines(2);
        control.addView(detail, matchWrap());
        return control;
    }

    private boolean isUploadingToAlbum(JSONObject album) {
        return isUploading
                && album != null
                && !activeUploadAlbumId.isEmpty()
                && activeUploadAlbumId.equals(album.optString("id"));
    }

    private int uploadProgressPercent() {
        int total = Math.max(uploadSelectedCount, 1);
        int done = Math.min(Math.max(uploadUploadedCount, 0), total);
        return Math.round(done * 100f / total);
    }

    private void refreshAlbumDetail(final String albumId) {
        if (albumId == null || albumId.isEmpty() || !hasLocalSession()) return;
        new Thread(() -> {
            try {
                JSONObject response = requestJson("GET", "/api/albums/" + albumId, null, true, true);
                JSONObject updated = response.optJSONObject("album");
                if (updated == null && response.optString("id", "").equals(albumId)) updated = response;
                if (updated == null) return;
                replaceAlbumInCache(updated);
                final JSONObject latest = updated;
                runOnUiThread(() -> {
                    if ("album".equals(currentScreen) && albumId.equals(selectedAlbumId)) {
                        showAlbumDetail(latest);
                    } else if ("folder".equals(currentScreen) && albumId.equals(selectedAlbumId)) {
                        JSONObject folder = findFolderById(latest, activeFolderId);
                        if (folder != null) showFolderDialog(latest, folder);
                    }
                });
            } catch (Exception ignored) {
                // Cached album remains usable when a background refresh is unavailable.
            }
        }).start();
    }

    private void replaceAlbumInCache(JSONObject updated) {
        if (updated == null) return;
        JSONArray next = new JSONArray();
        boolean replaced = false;
        for (int i = 0; i < albums.length(); i++) {
            JSONObject item = albums.optJSONObject(i);
            if (item != null && updated.optString("id").equals(item.optString("id"))) {
                next.put(updated);
                replaced = true;
            } else if (item != null) {
                next.put(item);
            }
        }
        if (!replaced) next.put(updated);
        albums = next;
        currentAlbum = updated;
        cacheAlbums();
    }

    private void showUploadDialog(JSONObject album) {
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(8), dp(18), dp(8));
        panel.addView(text("把手机里的朋友视角加进来", 24, PRIMARY, true), matchWrap());
        EditText uploader = field("上传者，不填写则默认为访客", false);
        uploader.setText(pendingUploader);
        panel.addView(uploader, matchWrap());
        Button choose = primaryButton("从系统相册选择照片或 Live Photo");
        panel.addView(choose, matchWrap());
        TextView hint = text("手机上可以一次多选；上传后由后台生成预览和人物小相册。", 13, SECONDARY, false);
        hint.setPadding(0, dp(10), 0, 0);
        panel.addView(hint, matchWrap());

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setView(panel)
                .setNegativeButton("关闭", null)
                .create();
        choose.setOnClickListener(v -> {
            pendingUploader = uploader.getText().toString().trim();
            pendingUploadAlbumId = album.optString("id", selectedAlbumId);
            dialog.dismiss();
            pickFiles();
        });
        dialog.show();
    }

    private void showRegisterDialog() {
        currentScreen = "register";
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackground(softBackground());
        LinearLayout panel = vertical();
        panel.setPadding(dp(28), dp(24), dp(28), dp(96));
        panel.setBackground(softBackground());
        scroll.addView(panel, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout header = horizontal();
        header.setGravity(Gravity.CENTER_VERTICAL);
        Button back = ghostButton("‹ 返回");
        back.setOnClickListener(v -> showLogin());
        header.addView(back, new LinearLayout.LayoutParams(dp(104), dp(52)));
        TextView pageTitle = text("创建新账号", 22, PRIMARY, true);
        pageTitle.setGravity(Gravity.CENTER);
        header.addView(pageTitle, new LinearLayout.LayoutParams(0, dp(52), 1));
        header.addView(new View(this), new LinearLayout.LayoutParams(dp(104), dp(52)));
        panel.addView(header, matchWrap());
        spacer(panel, dp(24));

        panel.addView(text("推荐上传头像", 21, PRIMARY, true), matchWrap());
        panel.addView(text("上传清晰的头像，有助于我们更准确地识别你并匹配专属照片。", 14, SECONDARY, false), matchWrap());
        registerAvatarUri = null;
        registerAvatarPreview = capsuleImage();
        registerAvatarPreview.setContentDescription("选择头像");
        registerAvatarPreview.setImageResource(android.R.drawable.ic_menu_camera);
        registerAvatarPreview.setColorFilter(AQUA);
        registerAvatarPreview.setOnClickListener(v -> pickRegisterAvatar());
        LinearLayout.LayoutParams avatarParams = new LinearLayout.LayoutParams(dp(132), dp(132));
        avatarParams.gravity = Gravity.CENTER_HORIZONTAL;
        avatarParams.setMargins(0, dp(14), 0, dp(10));
        panel.addView(registerAvatarPreview, avatarParams);
        Button chooseAvatar = ghostButton("选择头像（推荐）");
        chooseAvatar.setOnClickListener(v -> pickRegisterAvatar());
        panel.addView(chooseAvatar, matchWrap());

        registerNicknameInput = field("  昵称（显示在相册中）", false);
        registerUsernameInput = field("  登录账号", false);
        registerPasswordInput = field("  密码", true);
        registerConfirmPasswordInput = field("  确认密码", true);
        panel.addView(registerNicknameInput, fieldParams());
        panel.addView(registerUsernameInput, fieldParams());
        panel.addView(text("登录账号为 1-20 位字母、数字或下划线", 13, SECONDARY, false), matchWrap());
        panel.addView(registerPasswordInput, fieldParams());
        panel.addView(text("密码为 6-20 位，可使用数字、字母和英文符号", 13, SECONDARY, false), matchWrap());
        panel.addView(registerConfirmPasswordInput, fieldParams());

        Button create = primaryButton("注册");
        create.setOnClickListener(v -> register());
        LinearLayout.LayoutParams createParams = matchWrap();
        createParams.height = dp(60);
        createParams.setMargins(0, dp(12), 0, 0);
        panel.addView(create, createParams);

        Button login = ghostButton("已有账号？立即登录");
        login.setOnClickListener(v -> showLogin());
        panel.addView(login, matchWrap());
        statusText = text("", 14, SECONDARY, false);
        statusText.setGravity(Gravity.CENTER);
        statusText.setPadding(0, dp(12), 0, 0);
        panel.addView(statusText, matchWrap());
        setContentView(scroll);
    }

    private void pickRegisterAvatar() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        startActivityForResult(intent, REQUEST_PICK_REGISTER_AVATAR);
    }

    private void addTabRow(LinearLayout content, JSONObject album) {
        LinearLayout tabs = horizontal();
        tabs.setGravity(Gravity.CENTER);
        String[] labels = {
                "我的照片\n" + myPhotoCount(album),
                "人物小相册\n" + safeArray(album, "folders").length(),
                "全部照片\n" + safeArray(album, "photos").length()
        };
        String[] keys = {"my", "people", "all"};
        for (int i = 0; i < labels.length; i++) {
            final String key = keys[i];
            boolean selected = key.equals(activeAlbumTab);
            TextView tab = text(labels[i], 16, selected ? Color.WHITE : PRIMARY, true);
            tab.setGravity(Gravity.CENTER);
            tab.setPadding(dp(8), dp(12), dp(8), dp(12));
            tab.setBackground(round(selected ? TEAL : Color.WHITE, dp(14), Color.rgb(218, 246, 241), dp(1)));
            tab.setOnClickListener(v -> {
                activeAlbumTab = key;
                clearPhotoSelection();
                showAlbumDetail(album);
            });
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(72), 1);
            params.setMargins(i == 0 ? 0 : dp(6), dp(18), i == labels.length - 1 ? 0 : dp(6), dp(10));
            tabs.addView(tab, params);
        }
        content.addView(tabs, matchWrap());
    }

    private void showProfileDialog() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(20), dp(14), dp(20), dp(28));
        scroll.addView(panel);

        panel.addView(text("上传清晰的人脸头像后，PicMe 会更准确地推荐属于你的照片", 16, SECONDARY, true), matchWrap());
        spacer(panel, dp(22));

        ImageView avatar = capsuleImage();
        avatar.setContentDescription("更换头像");
        loadImageInto(currentUser == null ? "" : currentUser.optString("avatarUrl", ""), avatar);
        avatar.setOnClickListener(v -> pickAvatar());
        LinearLayout.LayoutParams avatarParams = new LinearLayout.LayoutParams(dp(148), dp(148));
        avatarParams.gravity = Gravity.CENTER_HORIZONTAL;
        panel.addView(avatar, avatarParams);

        TextView title = text(currentUser == null ? "我的资料" : currentUser.optString("nickname", "我的资料"), 25, PRIMARY, true);
        title.setGravity(Gravity.CENTER);
        panel.addView(title, matchWrap());
        TextView faceStatus = text(avatarRecognitionStatusText(), 14, currentUser != null && currentUser.optBoolean("hasFaceProfile") ? TEAL : SECONDARY, true);
        faceStatus.setGravity(Gravity.CENTER);
        panel.addView(faceStatus, matchWrap());
        spacer(panel, dp(18));

        panel.addView(profileInfoRow("昵称", currentUser == null ? "-" : currentUser.optString("nickname", "-")), matchWrap());
        panel.addView(profileInfoRow("登录账号", currentUser == null ? "-" : "@" + currentUser.optString("username", "-")), matchWrap());
        panel.addView(profileInfoRow("我的照片推荐", avatarRecognitionStatusText()), matchWrap());
        spacer(panel, dp(18));

        EditText nickname = field("昵称", false);
        if (currentUser != null) nickname.setText(currentUser.optString("nickname", ""));
        panel.addView(nickname, matchWrap());

        Button saveNickname = primaryButton("保存昵称");
        saveNickname.setOnClickListener(v -> updateNickname(nickname.getText().toString()));
        LinearLayout.LayoutParams saveParams = matchWrap();
        saveParams.height = dp(58);
        panel.addView(saveNickname, saveParams);

        Button uploadAvatar = outlineButton("更换头像");
        uploadAvatar.setOnClickListener(v -> pickAvatar());
        LinearLayout.LayoutParams uploadParams = matchWrap();
        uploadParams.height = dp(58);
        uploadParams.setMargins(0, dp(12), 0, 0);
        panel.addView(uploadAvatar, uploadParams);

        Button logoutButton = ghostButton("退出登录");
        logoutButton.setTextColor(Color.rgb(230, 74, 83));
        LinearLayout.LayoutParams logoutParams = matchWrap();
        logoutParams.height = dp(58);
        logoutParams.setMargins(0, dp(28), 0, 0);
        panel.addView(logoutButton, logoutParams);
        logoutButton.setOnClickListener(v -> {
            if (managementDialog != null && managementDialog.isShowing()) managementDialog.dismiss();
            logout();
        });
        showManagedAlbumPage("我的资料", scroll);
    }

    private View profileInfoRow(String label, String value) {
        LinearLayout row = horizontal();
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(16), dp(14), dp(16), dp(14));
        row.setBackground(round(Color.argb(238, 255, 255, 255), dp(16), Color.rgb(218, 246, 241), dp(1)));
        row.addView(text(label, 15, SECONDARY, true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        TextView content = text(value == null || value.isEmpty() ? "-" : value, 16, PRIMARY, true);
        content.setGravity(Gravity.END);
        row.addView(content, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(0, dp(6), 0, dp(6));
        row.setLayoutParams(params);
        return row;
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
        currentScreen = "folder";
        currentAlbum = album;
        selectedAlbumId = album.optString("id", selectedAlbumId);
        activeFolderId = folder.optString("id", activeFolderId);
        JSONObject activeFolder = findFolderById(album, activeFolderId);
        if (activeFolder == null) activeFolder = folder;

        FrameLayout frame = new FrameLayout(this);
        frame.setBackground(softBackground());
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(28), dp(18), dp(32));
        scroll.addView(panel);
        frame.addView(scroll);

        Button back = ghostButton("‹ 返回相册");
        back.setOnClickListener(v -> showAlbumDetail(album));
        panel.addView(back, new LinearLayout.LayoutParams(dp(150), dp(52)));

        HorizontalScrollView switcher = new HorizontalScrollView(this);
        switcher.setHorizontalScrollBarEnabled(false);
        LinearLayout folderButtons = horizontal();
        JSONArray folders = safeArray(album, "folders");
        for (int i = 0; i < folders.length(); i++) {
            JSONObject item = folders.optJSONObject(i);
            if (item == null) continue;
            boolean selected = activeFolderId.equals(item.optString("id"));
            Button button = selected ? primaryButton(item.optString("name", "人物")) : outlineButton(item.optString("name", "人物"));
            button.setTextSize(15);
            button.setOnClickListener(v -> {
                clearPhotoSelection();
                showFolderDialog(album, item);
            });
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(128), dp(52));
            params.setMargins(0, dp(10), dp(10), dp(10));
            folderButtons.addView(button, params);
        }
        switcher.addView(folderButtons);
        panel.addView(switcher, matchWrap());

        panel.addView(text(activeFolder.optString("name", "小相册"), 34, Color.BLACK, true), matchWrap());
        JSONArray visiblePhotos = folderPhotos(album, activeFolder);
        panel.addView(text(visiblePhotos.length() + " 张照片", 20, SECONDARY, true), matchWrap());

        LinearLayout actions = horizontal();
        JSONObject finalActiveFolder = activeFolder;
        addActionButton(actions, "重命名", R.drawable.ic_pencil, () -> showRenameFolderDialog(album, finalActiveFolder));
        addActionButton(actions, "下载", R.drawable.ic_download, () -> {
            if (permissionAllowed(album, "download")) runWithLegacyWritePermission(() -> downloadFolder(album, finalActiveFolder));
            else showPermissionDenied(album, "下载", "download");
        });
        addActionButton(actions, "删除", R.drawable.ic_trash, () -> {
            if (permissionAllowed(album, "delete")) confirmDeleteFolder(album, finalActiveFolder);
            else showPermissionDenied(album, "删除", "delete");
        });
        panel.addView(actions, matchWrap());
        addPhotoSelectionToolbar(panel, album, visiblePhotos);
        panel.addView(photoGrid(visiblePhotos, 120), matchWrap());
        setContentView(frame);
    }

    private JSONObject findFolderById(JSONObject album, String folderId) {
        JSONArray folders = safeArray(album, "folders");
        for (int i = 0; i < folders.length(); i++) {
            JSONObject folder = folders.optJSONObject(i);
            if (folder != null && folderId.equals(folder.optString("id"))) return folder;
        }
        return null;
    }

    private void addPhotoSelectionToolbar(LinearLayout content, JSONObject album, JSONArray photos) {
        LinearLayout toolbar = horizontal();
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        if (!photoSelectionMode) {
            TextView hint = text("点照片查看，或进入选择模式批量操作", 14, SECONDARY, false);
            toolbar.addView(hint, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            Button select = ghostButton("选择");
            select.setOnClickListener(v -> {
                photoSelectionMode = true;
                selectedPhotoIds.clear();
                refreshCurrentAlbumView();
            });
            toolbar.addView(select, new LinearLayout.LayoutParams(dp(86), dp(44)));
        } else {
            TextView count = text("已选择 " + selectedPhotoIds.size() + " 项", 15, PRIMARY, true);
            toolbar.addView(count, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            Button all = ghostButton(allPhotosSelected(photos) ? "清空" : "全选");
            all.setOnClickListener(v -> {
                if (allPhotosSelected(photos)) {
                    selectedPhotoIds.clear();
                } else {
                    selectedPhotoIds.clear();
                    for (int i = 0; i < photos.length(); i++) {
                        JSONObject photo = photos.optJSONObject(i);
                        if (photo != null) selectedPhotoIds.add(photo.optString("id"));
                    }
                }
                refreshCurrentAlbumView();
            });
            toolbar.addView(all, new LinearLayout.LayoutParams(dp(78), dp(44)));
            Button more = ghostButton("操作");
            more.setOnClickListener(v -> showSelectedPhotoActions(album, photos));
            toolbar.addView(more, new LinearLayout.LayoutParams(dp(78), dp(44)));
            Button cancel = ghostButton("取消");
            cancel.setOnClickListener(v -> {
                clearPhotoSelection();
                refreshCurrentAlbumView();
            });
            toolbar.addView(cancel, new LinearLayout.LayoutParams(dp(78), dp(44)));
        }
        content.addView(toolbar, matchWrap());
    }

    private boolean allPhotosSelected(JSONArray photos) {
        if (photos == null || photos.length() == 0) return false;
        for (int i = 0; i < photos.length(); i++) {
            JSONObject photo = photos.optJSONObject(i);
            if (photo == null || !selectedPhotoIds.contains(photo.optString("id"))) return false;
        }
        return true;
    }

    private void clearPhotoSelection() {
        photoSelectionMode = false;
        selectedPhotoIds.clear();
    }

    private JSONArray selectedPhotos(JSONArray visiblePhotos) {
        JSONArray result = new JSONArray();
        if (visiblePhotos == null) return result;
        for (int i = 0; i < visiblePhotos.length(); i++) {
            JSONObject photo = visiblePhotos.optJSONObject(i);
            if (photo != null && selectedPhotoIds.contains(photo.optString("id"))) result.put(photo);
        }
        return result;
    }

    private void showSelectedPhotoActions(final JSONObject album, final JSONArray visiblePhotos) {
        JSONArray selected = selectedPhotos(visiblePhotos);
        if (selected.length() == 0) {
            statusText.setText("请先选择照片");
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("操作所选照片")
                .setItems(new String[]{"保存到系统相册", "下载照片包", "移动到小相册", "删除所选照片"}, (dialog, which) -> {
                    if (which == 0) {
                        if (permissionAllowed(album, "download")) runWithLegacyWritePermission(() -> saveSelectedPhotos(selected));
                        else showPermissionDenied(album, "下载", "download");
                    } else if (which == 1) {
                        if (permissionAllowed(album, "download")) runWithLegacyWritePermission(() -> downloadSelectedPhotos(album, selected));
                        else showPermissionDenied(album, "下载", "download");
                    } else if (which == 2) {
                        showMoveSelectedPhotosDialog(album, selected);
                    } else {
                        if (canDeletePhotos(album, selected)) confirmDeleteSelectedPhotos(album, selected);
                        else showPermissionDenied(album, "删除", "delete");
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private LinearLayout folderGrid(JSONObject album) {
        LinearLayout wrapper = vertical();
        JSONArray folders = album.optJSONArray("folders");
        if (folders == null || folders.length() == 0) {
            TextView empty = text("还没有人物小相册", 16, SECONDARY, false);
            empty.setPadding(0, dp(18), 0, dp(18));
            wrapper.addView(empty, matchWrap());
            return wrapper;
        }
        LinearLayout row = null;
        for (int i = 0; i < folders.length(); i++) {
            if (i % 2 == 0) {
                row = horizontal();
                wrapper.addView(row, matchWrap());
            }
            JSONObject folder = folders.optJSONObject(i);
            if (folder == null) continue;
            LinearLayout item = card();
            item.setPadding(dp(12), dp(12), dp(12), dp(14));
            ImageView image = capsuleImage();
            String cover = folder.optString("coverUrl", "");
            if (cover.isEmpty()) cover = firstPhotoCover(album, folder);
            loadImageInto(cover, image);
            item.addView(image, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(132)));
            TextView name = text(folder.optString("name", "人物"), 22, PRIMARY, true);
            name.setPadding(0, dp(10), 0, 0);
            item.addView(name, matchWrap());
            item.addView(text(safeArray(folder, "photoIds").length() + " 张", 15, SECONDARY, true), matchWrap());
            item.setOnClickListener(v -> showFolderDialog(album, folder));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
            params.setMargins(dp(4), dp(4), dp(4), dp(8));
            row.addView(item, params);
        }
        return wrapper;
    }

    private void showRenameFolderDialog(final JSONObject album, final JSONObject folder) {
        EditText name = field("小相册名称", false);
        name.setText(folder.optString("name", ""));
        new AlertDialog.Builder(this)
                .setTitle("重命名小相册")
                .setView(name)
                .setNegativeButton("取消", null)
                .setPositiveButton("保存", (dialog, which) -> renameFolder(album, folder, name.getText().toString()))
                .show();
    }

    private void renameFolder(final JSONObject album, final JSONObject folder, final String rawName) {
        final String name = rawName == null ? "" : rawName.trim();
        if (name.isEmpty()) {
            statusText.setText("小相册名称不能为空");
            return;
        }
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("name", name);
                JSONObject response = requestJson("POST", "/api/albums/" + album.optString("id") + "/folders/" + folder.optString("id") + "/rename", body, true, true);
                updateAlbumFromResponse(response);
                runOnUiThread(() -> statusText.setText("小相册名已保存"));
            } catch (final Exception error) {
                showError("保存失败", error);
            }
        }).start();
    }

    private void downloadFolder(final JSONObject album, final JSONObject folder) {
        statusText.setText("正在下载小相册...");
        new Thread(() -> {
            try {
                JSONObject manifest = requestJson("GET", "/api/albums/" + album.optString("id") + "/folders/" + folder.optString("id") + "/download", null, true, true);
                JSONArray files = manifest.optJSONArray("files");
                if (files == null || files.length() == 0) throw new IllegalStateException("没有可下载的照片");
                for (int i = 0; i < files.length(); i++) {
                    JSONObject file = files.optJSONObject(i);
                    if (file == null) continue;
                    final int index = i + 1;
                    runOnUiThread(() -> statusText.setText("正在保存第 " + index + "/" + files.length() + " 个文件"));
                    saveUrlToMediaStore(file.optString("url", ""), file.optString("name", "picme-" + index), file.optString("mimeType", "application/octet-stream"));
                }
                runOnUiThread(() -> statusText.setText("小相册已保存到系统相册/下载目录"));
            } catch (final Exception error) {
                showError("下载失败", error);
            }
        }).start();
    }

    private void confirmDeleteFolder(final JSONObject album, final JSONObject folder) {
        new AlertDialog.Builder(this)
                .setTitle("删除小相册？")
                .setMessage("会移除这个小相册分类，照片也会从相册中删除。")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除", (dialog, which) -> deleteFolder(album, folder))
                .show();
    }

    private void deleteFolder(final JSONObject album, final JSONObject folder) {
        new Thread(() -> {
            try {
                JSONObject response = requestJson("DELETE", "/api/albums/" + album.optString("id") + "/folders/" + folder.optString("id"), null, true, true);
                updateAlbumFromResponse(response);
                runOnUiThread(() -> statusText.setText("小相册已删除"));
            } catch (final Exception error) {
                showError("删除失败", error);
            }
        }).start();
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
                boolean selected = selectedPhotoIds.contains(photo.optString("id"));
                if (photoSelectionMode) {
                    if (selected) {
                        View veil = new View(this);
                        veil.setBackgroundColor(Color.argb(80, 28, 194, 199));
                        cell.addView(veil, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
                    }
                    TextView check = text(selected ? "✓" : "", 20, Color.WHITE, true);
                    check.setGravity(Gravity.CENTER);
                    check.setBackground(round(selected ? AQUA : Color.argb(115, 0, 0, 0), dp(18), Color.WHITE, dp(2)));
                    FrameLayout.LayoutParams checkParams = new FrameLayout.LayoutParams(dp(34), dp(34), Gravity.END | Gravity.TOP);
                    checkParams.setMargins(0, dp(8), dp(8), 0);
                    cell.addView(check, checkParams);
                }
                if ("live_photo".equals(photo.optString("type"))) {
                    TextView badge = text("◎ LIVE", 12, Color.WHITE, true);
                    badge.setGravity(Gravity.CENTER);
                    badge.setBackground(round(Color.argb(145, 0, 0, 0), dp(16), Color.TRANSPARENT, 0));
                    FrameLayout.LayoutParams badgeParams = new FrameLayout.LayoutParams(dp(72), dp(30), Gravity.START | Gravity.BOTTOM);
                    badgeParams.setMargins(dp(8), 0, 0, dp(8));
                    cell.addView(badge, badgeParams);
                }
                final int photoIndex = i;
                cell.setOnClickListener(v -> {
                    JSONObject tapped = photos.optJSONObject(photoIndex);
                    if (tapped == null) return;
                    if (photoSelectionMode) {
                        String id = tapped.optString("id");
                        if (selectedPhotoIds.contains(id)) selectedPhotoIds.remove(id);
                        else selectedPhotoIds.add(id);
                        JSONObject album = currentAlbum != null ? currentAlbum : findAlbumById(selectedAlbumId);
                        if (album != null) refreshCurrentAlbumView();
                    } else {
                        showPhotoViewer(photos, photoIndex);
                    }
                });
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
        if (!"photo".equals(currentScreen)) photoReturnScreen = currentScreen;
        currentScreen = "photo";
        final int index = Math.max(0, Math.min(startIndex, photos.length() - 1));
        final JSONObject photo = photos.optJSONObject(index);
        if (photo == null) return;
        // 进入/切换查看器都重建视图，旧的 VideoView 已不存在，复位播放标志，避免卡死后无法再播。
        livePhotoPlaying = false;

        final boolean isLive = "live_photo".equals(photo.optString("type"));
        final int blue = Color.rgb(0, 122, 255);

        // 整体与 iOS 一致：白色背景。
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(Color.WHITE);
        LinearLayout content = vertical();
        content.setGravity(Gravity.CENTER_HORIZONTAL);
        frame.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        // 顶部：左“‹ 返回”(蓝色无底)，中间日期+时间，右侧“⋯”更多菜单(保存/删除)。
        LinearLayout header = horizontal();
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(16), dp(14), dp(16), dp(10));
        header.setBackgroundColor(Color.WHITE);
        Button back = plainTextButton("‹ 返回", blue, 17);
        back.setOnClickListener(v -> showCurrentAlbumOrHome());
        header.addView(back);
        LinearLayout center = vertical();
        center.setGravity(Gravity.CENTER);
        String dateStr = viewerDate(photo);
        if (dateStr.isEmpty()) {
            center.addView(text((index + 1) + " / " + photos.length(), 16, PRIMARY, true));
        } else {
            center.addView(text(dateStr, 16, PRIMARY, true));
            center.addView(text(viewerTime(photo), 12, SECONDARY, true));
        }
        header.addView(center, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button more = plainTextButton("⋯", blue, 24);
        more.setOnClickListener(v -> showPhotoViewerMenu(v, photo));
        header.addView(more);
        content.addView(header, matchWrap());

        // 照片区：白底、按比例居中。
        final FrameLayout imageSlot = new FrameLayout(this);
        final ImageView image = new ImageView(this);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        imageSlot.addView(image, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        // 大图加载期间显示居中转圈，避免长时间空白；加载完成回调里移除。
        final ProgressBar imageSpinner = new ProgressBar(this);
        imageSpinner.getIndeterminateDrawable().setColorFilter(AQUA, android.graphics.PorterDuff.Mode.SRC_IN);
        imageSlot.addView(imageSpinner, new FrameLayout.LayoutParams(dp(44), dp(44), Gravity.CENTER));
        loadImageInto(photo.optString("previewUrl", photo.optString("imageUrl", bestPhotoURL(photo))), image,
                () -> { if (imageSlot.indexOfChild(imageSpinner) >= 0) imageSlot.removeView(imageSpinner); });
        addSwipeNavigation(image, photos, index);
        content.addView(imageSlot, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        if (isLive) {
            // 仿 iOS LIVE 标志：照片左上角深色半透明胶囊（◉ + LIVE，白字），点击就地播放。
            final TextView liveBadge = text("◉  LIVE", 13, Color.WHITE, true);
            liveBadge.setGravity(Gravity.CENTER);
            liveBadge.setPadding(dp(12), dp(7), dp(12), dp(7));
            liveBadge.setBackground(round(Color.argb(128, 0, 0, 0), dp(16), Color.TRANSPARENT, 0));
            FrameLayout.LayoutParams badgeParams = new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.START | Gravity.TOP);
            badgeParams.setMargins(dp(14), dp(14), 0, 0);
            liveBadge.setOnClickListener(v -> playLiveVideo(photo, imageSlot, image, liveBadge));
            imageSlot.addView(liveBadge, badgeParams);
        }

        // 底部缩略图胶片条：当前张蓝色描边，点击跳转。
        final HorizontalScrollView strip = new HorizontalScrollView(this);
        strip.setHorizontalScrollBarEnabled(false);
        LinearLayout stripRow = horizontal();
        stripRow.setPadding(dp(12), dp(8), dp(12), dp(8));
        for (int i = 0; i < photos.length(); i++) {
            JSONObject p = photos.optJSONObject(i);
            ImageView thumb = new ImageView(this);
            thumb.setScaleType(ImageView.ScaleType.CENTER_CROP);
            boolean selected = (i == index);
            thumb.setBackground(round(Color.rgb(229, 241, 242), dp(8), selected ? blue : Color.TRANSPARENT, selected ? dp(2) : 0));
            thumb.setClipToOutline(true);
            if (p != null) {
                loadImageInto(p.optString("thumbnailUrl", p.optString("previewUrl", bestPhotoURL(p))), thumb);
                final int target = i;
                thumb.setOnClickListener(v -> showPhotoViewer(photos, target));
            }
            LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(dp(46), dp(46));
            tp.setMargins(dp(3), 0, dp(3), 0);
            stripRow.addView(thumb, tp);
        }
        strip.addView(stripRow);
        content.addView(strip, matchWrap());
        strip.post(() -> strip.smoothScrollTo(dp(52) * index - dp(140), 0));

        // 底部主操作：单个“保存”按钮（浅灰底、蓝字），与 iOS 一致。
        Button save = new Button(this);
        save.setText(isLive ? "⤓  保存 Live Photo" : "⤓  保存照片");
        save.setTextColor(blue);
        save.setTextSize(17);
        save.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        save.setAllCaps(false);
        save.setBackground(round(Color.rgb(238, 240, 243), dp(18), Color.TRANSPARENT, 0));
        save.setOnClickListener(v -> {
            JSONObject album = currentAlbum != null ? currentAlbum : findAlbumById(selectedAlbumId);
            if (album != null && !permissionAllowed(album, "download")) {
                showPermissionDenied(album, "下载", "download");
            } else {
                runWithLegacyWritePermission(() -> savePhotoResource(photo));
            }
        });
        LinearLayout.LayoutParams saveParams = matchWrap();
        saveParams.height = dp(54);
        saveParams.setMargins(dp(20), dp(8), dp(20), dp(26));
        content.addView(save, saveParams);

        setContentView(frame);
    }

    private void showPhotoViewerMenu(View anchor, final JSONObject photo) {
        boolean isLive = "live_photo".equals(photo.optString("type"));
        android.widget.PopupMenu menu = new android.widget.PopupMenu(this, anchor);
        final int idSave = 1;
        final int idDelete = 2;
        menu.getMenu().add(0, idSave, 0, isLive ? "保存 Live Photo" : "保存照片");
        menu.getMenu().add(0, idDelete, 1, "删除");
        menu.setOnMenuItemClickListener(item -> {
            JSONObject album = currentAlbum != null ? currentAlbum : findAlbumById(selectedAlbumId);
            if (item.getItemId() == idDelete) {
                if (album != null && canDeletePhoto(album, photo)) {
                    confirmDeletePhoto(album, photo);
                } else if (album != null) {
                    showPermissionDenied(album, "删除", "delete");
                }
            } else {
                if (album != null && !permissionAllowed(album, "download")) {
                    showPermissionDenied(album, "下载", "download");
                } else {
                    runWithLegacyWritePermission(() -> savePhotoResource(photo));
                }
            }
            return true;
        });
        menu.show();
    }

    private Button plainTextButton(String label, int color, int sizeSp) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(color);
        button.setTextSize(sizeSp);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setAllCaps(false);
        button.setBackgroundColor(Color.TRANSPARENT);
        button.setMinWidth(0);
        button.setMinimumWidth(0);
        button.setPadding(dp(6), dp(4), dp(6), dp(4));
        return button;
    }

    private String viewerDate(JSONObject photo) {
        long ts = photo.optLong("createdAt", 0L);
        if (ts <= 0) return "";
        return new SimpleDateFormat("yyyy年M月d日", Locale.CHINA).format(new Date(ts * 1000L));
    }

    private String viewerTime(JSONObject photo) {
        long ts = photo.optLong("createdAt", 0L);
        if (ts <= 0) return "";
        return new SimpleDateFormat("HH:mm", Locale.CHINA).format(new Date(ts * 1000L));
    }

    private void showCurrentAlbumOrHome() {
        JSONObject album = currentAlbum != null ? currentAlbum : findAlbumById(selectedAlbumId);
        JSONObject folder = album == null ? null : findFolderById(album, activeFolderId);
        if (album != null && "folder".equals(photoReturnScreen) && folder != null) showFolderDialog(album, folder);
        else if (album != null) showAlbumDetail(album);
        else showHome();
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
                view.performClick();
            }
            return true;
        });
    }

    private void playLiveVideo(JSONObject photo, final FrameLayout imageSlot, final ImageView stillImage, final View liveBadge) {
        if (livePhotoPlaying) return;
        livePhotoPlaying = true;
        // 仿 iOS Live Photo：点击左上角标志后，在照片原位就地播放短片，
        // 不显示任何播放器控件（无进度条/时长/播放暂停），播完自动回到静态图。
        liveBadge.setVisibility(View.GONE);

        // 统一走 PhotoDiskCache：已有本地缓存时不再显示加载态、也不再走网络，做到“首次缓存、之后秒开”。
        final String liveCacheId = "live:" + photo.optString("id", "");
        final boolean needDownload = diskCache().peekId(liveCacheId) == null;

        final LinearLayout loading;
        if (needDownload) {
            loading = vertical();
            loading.setGravity(Gravity.CENTER);
            loading.setPadding(dp(22), dp(18), dp(22), dp(18));
            loading.setBackground(round(Color.argb(150, 0, 0, 0), dp(16), Color.TRANSPARENT, 0));
            android.widget.ProgressBar spinner = new android.widget.ProgressBar(this);
            spinner.getIndeterminateDrawable().setColorFilter(Color.WHITE, android.graphics.PorterDuff.Mode.SRC_IN);
            loading.addView(spinner, new LinearLayout.LayoutParams(dp(38), dp(38)));
            TextView loadingText = text("Live 图加载中", 14, Color.WHITE, true);
            loadingText.setSingleLine(true);
            loadingText.setGravity(Gravity.CENTER);
            LinearLayout.LayoutParams ltp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            ltp.setMargins(0, dp(10), 0, 0);
            loading.addView(loadingText, ltp);
            imageSlot.addView(loading, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        } else {
            loading = null;
        }

        final Runnable restore = () -> {
            if (loading != null && imageSlot.indexOfChild(loading) >= 0) imageSlot.removeView(loading);
            stillImage.setVisibility(View.VISIBLE);
            liveBadge.setVisibility(View.VISIBLE);
            livePhotoPlaying = false;
        };

        new Thread(() -> {
            final java.io.File file;
            try {
                // Live 视频可能要先解析签名 URL，再下载；交给磁盘缓存统一管理(同标识并发只下一次)。
                file = diskCache().fetch(liveCacheId, out -> {
                    String url = liveVideoURL(photo);
                    if (url == null || url.isEmpty()) throw new IllegalStateException("没有可播放的视频资源");
                    downloadToFile(absoluteURL(url), out);
                });
            } catch (final Exception error) {
                runOnUiThread(() -> { restore.run(); showError("Live Photo 预览失败", error); });
                return;
            }
            // 自拍(前置)Live Photo 的视频带镜像变换矩阵，MediaPlayer 会忽略它导致画面水平翻转，
            // 这里解析出来后手动用 setScaleX(-1) 反镜像，和 iOS 表现保持一致。
            final boolean mirrored = isVideoMirrored(file);
            runOnUiThread(() -> startLivePlayback(file, mirrored, imageSlot, stillImage, loading, restore));
        }).start();
    }

    // 用 TextureView + MediaPlayer 播放：TextureView 是普通视图、内容就绪前完全透明，
    // 不像 VideoView(SurfaceView) 那样“挖洞”合成，因此点击瞬间不会出现黑屏闪烁。
    private void startLivePlayback(final java.io.File file, final boolean mirrored, final FrameLayout imageSlot,
                                   final ImageView stillImage, final LinearLayout loading, final Runnable restore) {
        final android.view.TextureView texture = new android.view.TextureView(this);
        texture.setOpaque(false);
        if (mirrored) texture.setScaleX(-1f); // 反镜像：与 iOS 一致
        final android.media.MediaPlayer player = new android.media.MediaPlayer();
        final boolean[] released = {false};
        final Runnable teardown = () -> {
            if (!released[0]) {
                released[0] = true;
                try { player.stop(); } catch (Exception ignored) {}
                try { player.release(); } catch (Exception ignored) {}
            }
            if (imageSlot.indexOfChild(texture) >= 0) imageSlot.removeView(texture);
            restore.run();
        };
        texture.setSurfaceTextureListener(new android.view.TextureView.SurfaceTextureListener() {
            @Override public void onSurfaceTextureAvailable(android.graphics.SurfaceTexture st, int w, int h) {
                try {
                    player.setSurface(new android.view.Surface(st));
                    player.setDataSource(file.getAbsolutePath());
                    player.setVolume(0f, 0f); // Live Photo 风格：静音
                    player.setOnPreparedListener(mp -> {
                        sizeTextureToVideo(texture, imageSlot, mp.getVideoWidth(), mp.getVideoHeight());
                        mp.start();
                    });
                    player.setOnInfoListener((mp, what, extra) -> {
                        // 首帧真正渲染后，再移除加载态并隐藏静态封面，杜绝黑屏闪烁。
                        if (what == android.media.MediaPlayer.MEDIA_INFO_VIDEO_RENDERING_START) {
                            if (loading != null && imageSlot.indexOfChild(loading) >= 0) imageSlot.removeView(loading);
                            stillImage.setVisibility(View.GONE);
                        }
                        return false;
                    });
                    player.setOnCompletionListener(mp -> teardown.run());
                    player.setOnErrorListener((mp, what, extra) -> { teardown.run(); return true; });
                    player.prepareAsync();
                } catch (Exception e) {
                    teardown.run();
                }
            }
            @Override public void onSurfaceTextureSizeChanged(android.graphics.SurfaceTexture st, int w, int h) {}
            @Override public boolean onSurfaceTextureDestroyed(android.graphics.SurfaceTexture st) { return true; }
            @Override public void onSurfaceTextureUpdated(android.graphics.SurfaceTexture st) {}
        });
        // 放在最底层，静态封面盖在上面；首帧出现前 TextureView 透明，看到的始终是静态图。
        imageSlot.addView(texture, 0, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER));
    }

    private void sizeTextureToVideo(android.view.TextureView texture, FrameLayout slot, int vw, int vh) {
        if (vw <= 0 || vh <= 0) return;
        int sw = slot.getWidth();
        int sh = slot.getHeight();
        if (sw <= 0 || sh <= 0) return;
        float scale = Math.min(sw / (float) vw, sh / (float) vh);
        int w = Math.max(1, Math.round(vw * scale));
        int h = Math.max(1, Math.round(vh * scale));
        texture.setLayoutParams(new FrameLayout.LayoutParams(w, h, Gravity.CENTER));
    }

    // 下载指定 URL 到目标文件（供 Live 视频等先解析签名 URL 再下载的场景使用）。
    private void downloadToFile(String absoluteUrl, java.io.File out) throws Exception {
        java.net.HttpURLConnection connection = (java.net.HttpURLConnection) new java.net.URL(absoluteUrl).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestMethod("GET");
        InputStream input = connection.getInputStream();
        java.io.FileOutputStream output = new java.io.FileOutputStream(out);
        try {
            byte[] buffer = new byte[16384];
            int n;
            while ((n = input.read(buffer)) > 0) output.write(buffer, 0, n);
        } finally {
            try { output.close(); } catch (Exception ignored) {}
            try { input.close(); } catch (Exception ignored) {}
            connection.disconnect();
        }
    }

    // 解析 MP4/MOV 视频轨道头(tkhd)的变换矩阵，行列式为负说明含水平镜像(前置自拍)。
    private boolean isVideoMirrored(java.io.File file) {
        try (java.io.RandomAccessFile raf = new java.io.RandomAccessFile(file, "r")) {
            float[] m = findVideoTkhdMatrix(raf, 0, raf.length());
            if (m == null) return false;
            double det = (double) m[0] * m[3] - (double) m[1] * m[2];
            return det < 0;
        } catch (Exception ignored) {
            return false;
        }
    }

    // 在 [start,end) 内遍历 box，递归进入 moov/trak/mdia，找到视频轨道的 tkhd 并返回其 2x2 矩阵 [a,b,c,d]。
    private float[] findVideoTkhdMatrix(java.io.RandomAccessFile raf, long start, long end) throws java.io.IOException {
        long pos = start;
        while (pos + 8 <= end) {
            raf.seek(pos);
            long size = raf.readInt() & 0xFFFFFFFFL;
            int type = raf.readInt();
            long headerSize = 8;
            if (size == 1) { size = raf.readLong(); headerSize = 16; }
            else if (size == 0) { size = end - pos; }
            if (size < headerSize) break;
            long contentStart = pos + headerSize;
            long contentEnd = Math.min(pos + size, end);
            String t = boxType(type);
            if ("moov".equals(t) || "trak".equals(t) || "mdia".equals(t)) {
                float[] r = findVideoTkhdMatrix(raf, contentStart, contentEnd);
                if (r != null) return r;
            } else if ("tkhd".equals(t)) {
                float[] r = parseTkhdMatrix(raf, contentStart);
                if (r != null) return r; // 仅视频轨(宽高>0)会返回
            }
            pos += size;
        }
        return null;
    }

    private float[] parseTkhdMatrix(java.io.RandomAccessFile raf, long start) throws java.io.IOException {
        raf.seek(start);
        int versionFlags = raf.readInt();
        int version = (versionFlags >>> 24) & 0xFF;
        // creation+modification+trackID+reserved+duration
        long skip = (version == 1) ? (8 + 8 + 4 + 4 + 8) : (4 + 4 + 4 + 4 + 4);
        raf.seek(start + 4 + skip);
        raf.skipBytes(16); // reserved(8)+layer(2)+alternate(2)+volume(2)+reserved(2)
        int a = raf.readInt();
        int b = raf.readInt();
        raf.skipBytes(4);  // u
        int c = raf.readInt();
        int d = raf.readInt();
        raf.skipBytes(4 + 4 + 4 + 4); // v,x,y,w
        int widthFixed = raf.readInt();
        int heightFixed = raf.readInt();
        long width = (widthFixed >>> 16) & 0xFFFF;
        long height = (heightFixed >>> 16) & 0xFFFF;
        if (width == 0 || height == 0) return null; // 非视频轨(如音频)宽高为 0
        return new float[]{a, b, c, d};
    }

    private String boxType(int type) {
        return new String(new char[]{
                (char) ((type >>> 24) & 0xFF),
                (char) ((type >>> 16) & 0xFF),
                (char) ((type >>> 8) & 0xFF),
                (char) (type & 0xFF)
        });
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

    private void savePhotoResource(final JSONObject photo) {
        statusText.setText("正在保存照片...");
        new Thread(() -> {
            try {
                savePhotoResourceSync(photo);
                runOnUiThread(() -> statusText.setText("已保存到系统相册"));
                toast("已保存到系统相册");
            } catch (final Exception error) {
                showError("保存失败", error);
            }
        }).start();
    }

    private void savePhotoResourceSync(final JSONObject photo) throws Exception {
        String url = photo.optString("downloadImageUrl", "");
        String mimeType = "image/jpeg";
        String filename = photo.optString("originalName", "picme-" + System.currentTimeMillis() + ".jpg");
        if (url.isEmpty()) url = photo.optString("imageUrl", photo.optString("previewUrl", bestPhotoURL(photo)));
        if ("live_photo".equals(photo.optString("type")) && !photo.optString("downloadLiveUrl", "").isEmpty()) {
            JSONObject manifest = requestJson("GET", photo.optString("downloadLiveUrl"), null, true, true);
            JSONObject image = manifest.optJSONObject("image");
            if (image != null) {
                url = image.optString("url", url);
                filename = image.optString("filename", filename);
                mimeType = image.optString("mimeType", mimeType);
            }
            JSONObject video = manifest.optJSONObject("video");
            if (video != null) {
                // Live Photo 的动态视频与静态图同名（仅扩展名不同），方便在系统相册里配对识别。
                String base = filename.contains(".") ? filename.substring(0, filename.lastIndexOf('.')) : filename;
                String videoName = base + ".mov";
                saveUrlToMediaStore(video.optString("url", ""), videoName, video.optString("mimeType", "video/quicktime"));
            }
        }
        if (url.isEmpty()) throw new IllegalStateException("没有可保存的原图资源");
        saveUrlToMediaStore(absoluteURL(url), filename, mimeType);
    }

    private void saveSelectedPhotos(final JSONArray photos) {
        statusText.setText("正在保存所选照片...");
        new Thread(() -> {
            try {
                for (int i = 0; i < photos.length(); i++) {
                    JSONObject photo = photos.optJSONObject(i);
                    if (photo == null) continue;
                    final int index = i + 1;
                    runOnUiThread(() -> statusText.setText("正在保存第 " + index + "/" + photos.length() + " 张"));
                    savePhotoResourceSync(photo);
                }
                final int savedCount = photos.length();
                runOnUiThread(() -> {
                    clearPhotoSelection();
                    statusText.setText("已保存 " + savedCount + " 张照片");
                    refreshCurrentAlbumView();
                });
                toast("已保存 " + savedCount + " 张照片到系统相册");
            } catch (final Exception error) {
                showError("保存失败", error);
            }
        }).start();
    }

    private void downloadSelectedPhotos(final JSONObject album, final JSONArray photos) {
        statusText.setText("正在准备所选照片包...");
        new Thread(() -> {
            try {
                JSONArray ids = new JSONArray();
                for (int i = 0; i < photos.length(); i++) {
                    JSONObject photo = photos.optJSONObject(i);
                    if (photo != null) ids.put(photo.optString("id"));
                }
                JSONObject body = new JSONObject();
                body.put("photoIds", ids);
                JSONObject manifest = requestJson("POST", "/api/albums/" + album.optString("id") + "/photos/download-selected", body, true, true);
                JSONArray files = manifest.optJSONArray("files");
                if (files == null || files.length() == 0) throw new IllegalStateException("没有可下载的照片");
                for (int i = 0; i < files.length(); i++) {
                    JSONObject file = files.optJSONObject(i);
                    if (file == null) continue;
                    final int index = i + 1;
                    runOnUiThread(() -> statusText.setText("正在保存照片包第 " + index + "/" + files.length() + " 个文件"));
                    saveUrlToMediaStore(file.optString("url", ""), file.optString("name", "picme-selected-" + index), file.optString("mimeType", "application/octet-stream"));
                }
                runOnUiThread(() -> {
                    clearPhotoSelection();
                    statusText.setText("所选照片包已保存");
                    refreshCurrentAlbumView();
                });
                toast("所选照片包已保存到系统相册");
            } catch (final Exception error) {
                showError("下载失败", error);
            }
        }).start();
    }

    private void showMoveSelectedPhotosDialog(final JSONObject album, final JSONArray photos) {
        JSONArray folders = safeArray(album, "folders");
        List<JSONObject> targets = new ArrayList<>();
        List<String> names = new ArrayList<>();
        for (int i = 0; i < folders.length(); i++) {
            JSONObject folder = folders.optJSONObject(i);
            if (folder == null) continue;
            String id = folder.optString("id", "");
            if ("pending".equals(id)) continue;
            if ("folder".equals(currentScreen) && id.equals(activeFolderId)) continue;
            targets.add(folder);
            names.add(folder.optString("name", "小相册"));
        }
        if (targets.isEmpty()) {
            statusText.setText("暂无可移动的小相册");
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("移动到小相册")
                .setItems(names.toArray(new String[0]), (dialog, which) -> moveSelectedPhotos(album, photos, targets.get(which)))
                .setNegativeButton("取消", null)
                .show();
    }

    private void moveSelectedPhotos(final JSONObject album, final JSONArray photos, final JSONObject targetFolder) {
        statusText.setText("正在移动所选照片...");
        new Thread(() -> {
            try {
                JSONObject latest = null;
                for (int i = 0; i < photos.length(); i++) {
                    JSONObject photo = photos.optJSONObject(i);
                    if (photo == null) continue;
                    JSONObject body = new JSONObject();
                    body.put("targetFolderId", targetFolder.optString("id"));
                    latest = requestJson("POST", "/api/albums/" + album.optString("id") + "/photos/" + photo.optString("id") + "/move", body, true, true);
                    final int index = i + 1;
                    runOnUiThread(() -> statusText.setText("正在移动第 " + index + "/" + photos.length() + " 张"));
                }
                clearPhotoSelection();
                if (latest != null) updateAlbumFromResponse(latest);
                runOnUiThread(() -> statusText.setText("已移动到 " + targetFolder.optString("name", "小相册")));
            } catch (final Exception error) {
                showError("移动失败", error);
            }
        }).start();
    }

    private void saveUrlToMediaStore(String rawUrl, String filename, String mimeType) throws Exception {
        String url = absoluteURL(rawUrl);
        if (url.isEmpty()) throw new IllegalStateException("下载地址为空");
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setRequestMethod("GET");
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) throw new IllegalStateException(readAll(connection.getErrorStream(), "下载失败：" + code));
        boolean isImage = mimeType != null && mimeType.startsWith("image/");
        boolean isVideo = mimeType != null && mimeType.startsWith("video/");
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, filename);
        values.put(MediaStore.MediaColumns.MIME_TYPE, mimeType);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // 图片→Pictures/PicMe，视频→Movies/PicMe（与图片一样落在系统相册可见目录，
            // 而不是之前的 Download，避免 Live Photo 的动态视频跑到下载里、相册看不到）。
            String relativePath = isImage ? Environment.DIRECTORY_PICTURES + "/PicMe"
                    : isVideo ? Environment.DIRECTORY_MOVIES + "/PicMe"
                    : Environment.DIRECTORY_DOWNLOADS + "/PicMe";
            values.put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath);
            values.put(MediaStore.MediaColumns.IS_PENDING, 1);
        }
        Uri collection;
        if (isImage) {
            collection = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                    ? MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                    : MediaStore.Images.Media.EXTERNAL_CONTENT_URI;
        } else if (isVideo) {
            collection = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                    ? MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                    : MediaStore.Video.Media.EXTERNAL_CONTENT_URI;
        } else {
            collection = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                    ? MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                    : MediaStore.Files.getContentUri("external");
        }
        Uri outputUri = getContentResolver().insert(collection, values);
        if (outputUri == null) throw new IllegalStateException("无法创建系统文件");
        InputStream input = connection.getInputStream();
        OutputStream output = getContentResolver().openOutputStream(outputUri);
        if (output == null) throw new IllegalStateException("无法写入系统文件");
        byte[] buffer = new byte[1024 * 64];
        int read;
        while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
        output.flush();
        output.close();
        input.close();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            values.clear();
            values.put(MediaStore.MediaColumns.IS_PENDING, 0);
            getContentResolver().update(outputUri, values, null, null);
        }
    }

    private void runWithLegacyWritePermission(Runnable action) {
        if (action == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                || checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED) {
            action.run();
            return;
        }
        pendingLegacyWriteAction = action;
        requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQUEST_WRITE_EXTERNAL_STORAGE);
    }

    private void confirmDeletePhoto(final JSONObject album, final JSONObject photo) {
        new AlertDialog.Builder(this)
                .setTitle("删除照片？")
                .setMessage("会从这个相册里删除这张照片。")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除", (dialog, which) -> deletePhoto(album, photo))
                .show();
    }

    private void deletePhoto(final JSONObject album, final JSONObject photo) {
        new Thread(() -> {
            try {
                JSONObject response = requestJson("DELETE", "/api/albums/" + album.optString("id") + "/photos/" + photo.optString("id"), null, true, true);
                updateAlbumFromResponse(response);
                runOnUiThread(() -> statusText.setText("照片已删除"));
            } catch (final Exception error) {
                showError("删除失败", error);
            }
        }).start();
    }

    private void confirmDeleteSelectedPhotos(final JSONObject album, final JSONArray photos) {
        new AlertDialog.Builder(this)
                .setTitle("删除所选照片？")
                .setMessage("会从这个相册里删除 " + photos.length() + " 张照片。")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除", (dialog, which) -> deleteSelectedPhotos(album, photos))
                .show();
    }

    private void deleteSelectedPhotos(final JSONObject album, final JSONArray photos) {
        new Thread(() -> {
            try {
                JSONArray ids = new JSONArray();
                for (int i = 0; i < photos.length(); i++) {
                    JSONObject photo = photos.optJSONObject(i);
                    if (photo != null) ids.put(photo.optString("id"));
                }
                JSONObject body = new JSONObject();
                body.put("photoIds", ids);
                JSONObject response = requestJson("POST", "/api/albums/" + album.optString("id") + "/photos/delete-selected", body, true, true);
                clearPhotoSelection();
                updateAlbumFromResponse(response);
                runOnUiThread(() -> statusText.setText("所选照片已删除"));
            } catch (final Exception error) {
                showError("删除失败", error);
            }
        }).start();
    }

    private void shareAlbum(final JSONObject album) {
        statusText.setText("正在读取分享信息...");
        showManagedAlbumPage("分享相册", managementStateContent("正在生成分享信息", true, null));
        new Thread(() -> {
            try {
                JSONObject response = requestJson("POST", "/api/albums/" + album.optString("id") + "/invite", new JSONObject(), true, true);
                JSONObject invite = response.optJSONObject("invite");
                if (invite == null) throw new IllegalStateException("无法生成分享信息");
                runOnUiThread(() -> renderShareInviteDialog(album, invite));
            } catch (final Exception error) {
                runOnUiThread(() -> showManagedAlbumPage(
                        "分享相册",
                        managementStateContent("分享失败：" + humanReadableError(error.getMessage()), false, () -> shareAlbum(album))
                ));
            }
        }).start();
    }

    private void renderShareInviteDialog(final JSONObject album, final JSONObject invite) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setGravity(Gravity.CENTER_HORIZONTAL);
        panel.setPadding(dp(18), dp(10), dp(18), dp(8));
        scroll.addView(panel);

        String shareUrl = invite.optString("shareUrl", "");
        String code = invite.optString("code", "");
        ImageView qr = new ImageView(this);
        qr.setContentDescription("相册分享二维码");
        try {
            qr.setImageBitmap(generateQRCode(shareUrl, 720));
            qr.setScaleType(ImageView.ScaleType.FIT_CENTER);
            qr.setBackground(round(Color.WHITE, dp(16), Color.rgb(218, 246, 241), dp(1)));
            panel.addView(qr, new LinearLayout.LayoutParams(dp(250), dp(250)));
        } catch (Exception error) {
            panel.addView(text("二维码生成失败，可复制链接分享", 14, SECONDARY, true), matchWrap());
        }

        TextView codeView = text(code, 30, AQUA, true);
        codeView.setGravity(Gravity.CENTER);
        codeView.setPadding(0, dp(12), 0, dp(4));
        codeView.setOnClickListener(v -> copyText("相册码", code));
        panel.addView(codeView, matchWrap());
        TextView linkView = text(shareUrl, 13, SECONDARY, true);
        linkView.setGravity(Gravity.CENTER);
        linkView.setOnClickListener(v -> copyText("分享链接", shareUrl));
        panel.addView(linkView, matchWrap());
        panel.addView(text("点按相册码或链接即可复制", 12, SECONDARY, false), matchWrap());

        spacer(panel, dp(12));
        panel.addView(text("通过此链接加入的默认权限", 20, PRIMARY, true), matchWrap());
        Map<String, Switch> switches = permissionSwitches(panel, permissionsObject(invite, "permissions"), true);
        for (Switch control : switches.values()) {
            control.setOnCheckedChangeListener((buttonView, isChecked) ->
                    updateInvitePermissions(album, permissionsFromSwitches(switches)));
        }

        Button share = primaryButton("分享给微信或朋友");
        share.setOnClickListener(v -> shareInviteText(album, invite));
        LinearLayout.LayoutParams shareParams = matchWrap();
        shareParams.setMargins(0, dp(18), 0, dp(6));
        panel.addView(share, shareParams);

        Button reset = ghostButton("重置相册码");
        reset.setTextColor(Color.rgb(230, 74, 83));
        reset.setOnClickListener(v -> confirmResetInvite(album, permissionsFromSwitches(switches)));
        panel.addView(reset, matchWrap());

        showManagedAlbumPage("分享相册", scroll);
    }

    private void updateInvitePermissions(final JSONObject album, final JSONObject permissions) {
        if (pendingInvitePermissionSave != null) mainHandler.removeCallbacks(pendingInvitePermissionSave);
        pendingInvitePermissionSave = () -> new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("permissions", permissions == null ? defaultPermissions() : permissions);
                requestJson("POST", "/api/albums/" + album.optString("id") + "/invite", body, true, true);
                runOnUiThread(() -> statusText.setText("已自动保存链接默认权限"));
            } catch (final Exception error) {
                showError("保存链接权限失败", error);
            }
        }).start();
        mainHandler.postDelayed(pendingInvitePermissionSave, 250L);
    }

    private void confirmResetInvite(final JSONObject album, final JSONObject permissions) {
        new AlertDialog.Builder(this)
                .setTitle("重置相册码？")
                .setMessage("旧的相册码和分享链接会立即失效。")
                .setNegativeButton("取消", null)
                .setPositiveButton("重置", (dialog, which) -> resetInvite(album, permissions))
                .show();
    }

    private void resetInvite(final JSONObject album, final JSONObject permissions) {
        statusText.setText("正在重置相册码...");
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("permissions", permissions == null ? defaultPermissions() : permissions);
                JSONObject response = requestJson("POST", "/api/albums/" + album.optString("id") + "/invite/reset", body, true, true);
                JSONObject invite = response.optJSONObject("invite");
                if (invite == null) throw new IllegalStateException("没有返回新的相册码");
                runOnUiThread(() -> {
                    statusText.setText("相册码已重置");
                    renderShareInviteDialog(album, invite);
                });
            } catch (final Exception error) {
                showError("重置相册码失败", error);
            }
        }).start();
    }

    private void shareInviteText(JSONObject album, JSONObject invite) {
        String shareUrl = invite.optString("shareUrl", "");
        Intent intent = new Intent(Intent.ACTION_SEND);
        intent.setType("text/plain");
        intent.putExtra(Intent.EXTRA_TEXT, "加入 PicMe 相册：" + album.optString("name", "共享相册") + "\n" + shareUrl);
        startActivity(Intent.createChooser(intent, "分享相册"));
    }

    private void copyText(String label, String value) {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) clipboard.setPrimaryClip(ClipData.newPlainText(label, value));
        statusText.setText(label + "已复制");
    }

    private Bitmap generateQRCode(String value, int size) throws WriterException {
        BitMatrix matrix = new MultiFormatWriter().encode(value, BarcodeFormat.QR_CODE, size, size);
        int[] pixels = new int[size * size];
        for (int y = 0; y < size; y++) {
            int offset = y * size;
            for (int x = 0; x < size; x++) {
                pixels[offset + x] = matrix.get(x, y) ? Color.BLACK : Color.WHITE;
            }
        }
        Bitmap bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        bitmap.setPixels(pixels, 0, size, 0, 0, size, size);
        return bitmap;
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
        return findAlbumInArray(albums, albumId);
    }

    private JSONObject findAlbumInArray(JSONArray source, String albumId) {
        if (source == null || albumId == null || albumId.isEmpty()) return null;
        for (int i = 0; i < source.length(); i++) {
            JSONObject album = source.optJSONObject(i);
            if (album != null && albumId.equals(album.optString("id"))) return album;
        }
        return null;
    }

    private void showCreateAlbumDialog() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(20), dp(14), dp(20), dp(28));
        scroll.addView(panel);
        panel.addView(text("给这次出游起个名字，并设置协作用户可以进行的操作。", 16, SECONDARY, true), matchWrap());
        spacer(panel, dp(16));
        EditText name = field("例如：重庆周末小队", false);
        name.setPadding(dp(16), dp(12), dp(16), dp(12));
        panel.addView(name, matchWrap());
        TextView hint = text("相册级权限", 18, PRIMARY, true);
        panel.addView(hint, matchWrap());
        Map<String, Switch> switches = permissionSwitches(panel, defaultPermissions(), true);
        spacer(panel, dp(20));
        Button create = primaryButton("创建相册");
        create.setOnClickListener(v -> createAlbum(name.getText().toString(), permissionsFromSwitches(switches)));
        LinearLayout.LayoutParams createParams = matchWrap();
        createParams.height = dp(60);
        panel.addView(create, createParams);
        showManagedAlbumPage("创建新相册", scroll);
    }

    private void showJoinDialog(String preset) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(20), dp(14), dp(20), dp(28));
        scroll.addView(panel);
        panel.addView(text("扫描 PicMe 分享二维码，或粘贴相册码 / 分享链接。", 15, SECONDARY, false), matchWrap());
        inviteCodeInput = field("相册码或分享链接", false);
        inviteCodeInput.setText(inviteCodeFrom(preset));
        panel.addView(inviteCodeInput, matchWrap());
        spacer(panel, dp(16));
        Button camera = outlineButton("扫码加入相册");
        camera.setOnClickListener(v -> captureJoinQRCode());
        LinearLayout.LayoutParams cameraParams = matchWrap();
        cameraParams.height = dp(54);
        panel.addView(camera, cameraParams);
        spacer(panel, dp(12));
        Button picker = outlineButton("从相册中选择");
        picker.setOnClickListener(v -> pickJoinQRCodeImage());
        LinearLayout.LayoutParams pickerParams = matchWrap();
        pickerParams.height = dp(54);
        panel.addView(picker, pickerParams);
        spacer(panel, dp(24));
        Button join = primaryButton("申请加入");
        join.setOnClickListener(v -> requestJoinFromInput());
        LinearLayout.LayoutParams joinParams = matchWrap();
        joinParams.height = dp(60);
        panel.addView(join, joinParams);
        showManagedAlbumPage("加入相册", scroll);
    }

    private void captureJoinQRCode() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQUEST_CAMERA_PERMISSION);
            return;
        }
        Intent intent = new Intent(this, QRCodeScannerActivity.class);
        statusText.setText("请扫描 PicMe 相册二维码");
        startActivityForResult(intent, REQUEST_CAPTURE_QR);
    }

    private void pickJoinQRCodeImage() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        statusText.setText("请选择包含分享二维码的图片");
        startActivityForResult(intent, REQUEST_PICK_QR_IMAGE);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_CAMERA_PERMISSION) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                captureJoinQRCode();
            } else {
                showTransientStatus("需要相机权限才能扫码，也可以从相册选择二维码");
            }
        } else if (requestCode == REQUEST_WRITE_EXTERNAL_STORAGE) {
            Runnable action = pendingLegacyWriteAction;
            pendingLegacyWriteAction = null;
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                if (action != null) action.run();
            } else {
                showTransientStatus("需要存储权限才能保存到系统相册，请在系统设置中授权");
            }
        }
    }

    private void handleJoinIntent(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data == null) return;
        String code = inviteCodeFrom(data.toString());
        if (!code.isEmpty()) {
            if (hasLocalSession()) {
                showJoinDialog(code);
            } else {
                pendingJoinCode = code;
                loginNoticeText = "已识别相册码：" + code + "，登录后可申请加入。";
                showLogin();
            }
        }
    }

    private boolean openPendingJoinAfterAuth() {
        String code = pendingJoinCode == null ? "" : pendingJoinCode.trim();
        if (code.isEmpty()) return false;
        pendingJoinCode = "";
        showJoinDialog(code);
        return true;
    }

    private boolean openPendingNotificationAfterAuth() {
        if (pendingNotificationMessage == null) return false;
        JSONObject message = pendingNotificationMessage;
        pendingNotificationMessage = null;
        openMessage(message);
        return true;
    }

    private void handleNotificationIntent(Intent intent) {
        if (intent == null) return;
        String messageId = intent.getStringExtra("messageId");
        if (messageId == null || messageId.isEmpty()) return;
        JSONObject message = new JSONObject();
        try {
            message.put("id", messageId);
            message.put("type", intent.getStringExtra("messageType"));
            message.put("albumId", intent.getStringExtra("albumId"));
        } catch (Exception ignored) {
        }
        intent.removeExtra("messageId");
        if (hasLocalSession()) {
            openMessage(message);
        } else {
            pendingNotificationMessage = message;
            loginNoticeText = "登录后可查看这条消息。";
            showLogin();
        }
    }

    private void enableMessageNotifications() {
        MessageNotificationJobService.schedule(this);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                && !prefs.getBoolean("notificationPermissionRequested", false)) {
            prefs.edit().putBoolean("notificationPermissionRequested", true).apply();
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQUEST_POST_NOTIFICATIONS);
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
                syncDefaultUploader();
                cacheCurrentUser();
                runOnUiThread(() -> {
                    loginNoticeText = "";
                    showHome();
                    enableMessageNotifications();
                    statusText.setText("欢迎回来，" + (currentUser == null ? username : currentUser.optString("nickname", username)));
                    if (!openPendingJoinAfterAuth() && !openPendingNotificationAfterAuth()) {
                        loadAlbums();
                    }
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
        final String confirmPassword = registerConfirmPasswordInput == null ? "" : registerConfirmPasswordInput.getText().toString();
        final Uri avatarUri = registerAvatarUri;
        if (nickname.isEmpty()) {
            showTransientStatus("昵称不能为空");
            return;
        }
        if (!isValidUsername(username)) {
            showTransientStatus("登录账号需为 1-20 位字母、数字或下划线");
            return;
        }
        if (!isValidPasswordFormat(password)) {
            showTransientStatus("密码需为 6-20 位，且不能包含中文、空格或中文符号");
            return;
        }
        if (!password.equals(confirmPassword)) {
            showTransientStatus("两次输入的密码不一致");
            return;
        }
        statusText.setText("正在创建账号...");
        new Thread(() -> {
            try {
                JSONObject response = registerRequest(username, nickname, password, avatarUri);
                saveTokens(response);
                currentUser = response.optJSONObject("user");
                syncDefaultUploader();
                cacheCurrentUser();
                runOnUiThread(() -> {
                    loginNoticeText = "";
                    showHome();
                    enableMessageNotifications();
                    statusText.setText("欢迎加入 PicMe，" + nickname);
                    if (!openPendingJoinAfterAuth() && !openPendingNotificationAfterAuth()) {
                        loadAlbums();
                    }
                });
                if (avatarUri != null) pollAvatarRecognition();
            } catch (final Exception error) {
                showError("创建账号失败", error);
            }
        }).start();
    }

    private void logout() {
        final String accessToken = prefs.getString("accessToken", "");
        avatarRecognitionPollRevision++;
        albumRecognitionPollRevision++;
        prefs.edit().clear().apply();
        MessageNotificationJobService.cancel(this);
        albums = new JSONArray();
        selectedAlbumId = "";
        loginNoticeText = "";
        currentUser = null;
        showLogin();
        statusText.setText("已退出登录");
        if (!accessToken.isEmpty()) new Thread(() -> logoutServer(accessToken)).start();
    }

    // 中性启动加载页:仅 logo + 品牌 + 转圈,不渲染任何依赖会话的主页/登录壳,
    // 校验期间作为占位,避免闪现残缺中间态(QA #9)。
    private void showSplash() {
        currentScreen = "splash";
        LinearLayout container = vertical();
        container.setGravity(Gravity.CENTER);
        container.setBackground(softBackground());
        container.setPadding(dp(28), dp(28), dp(28), dp(28));

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.picme_logo);
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(dp(82), dp(82));
        logoParams.gravity = Gravity.CENTER_HORIZONTAL;
        container.addView(logo, logoParams);
        spacer(container, dp(22));

        LinearLayout brand = horizontal();
        brand.setGravity(Gravity.CENTER);
        brand.addView(text("识我", 26, PRIMARY, true));
        brand.addView(text(" PicMe", 26, Color.rgb(98, 132, 220), true));
        container.addView(brand, matchWrap());
        spacer(container, dp(30));

        ProgressBar spinner = new ProgressBar(this);
        spinner.getIndeterminateDrawable().setColorFilter(AQUA, android.graphics.PorterDuff.Mode.SRC_IN);
        LinearLayout.LayoutParams spinnerParams = new LinearLayout.LayoutParams(dp(40), dp(40));
        spinnerParams.gravity = Gravity.CENTER_HORIZONTAL;
        container.addView(spinner, spinnerParams);
        setContentView(container);
    }

    // 冷启动会话校验:单线程顺序请求 /api/me → /api/albums(只触发一次 token 刷新,消除并发竞态),
    // 校验通过才切主页;401 时 requestJson 内部已调用 expireSession() 干净切登录页;
    // 其它网络错误则用缓存数据降级进主页,避免卡在 splash。
    private void bootstrapSession() {
        new Thread(() -> {
            try {
                JSONObject meResponse = requestJson("GET", "/api/me", null, true, true);
                currentUser = meResponse.optJSONObject("user");
                syncDefaultUploader();
                cacheCurrentUser();

                JSONObject albumResponse = requestJson("GET", "/api/albums", null, true, true);
                JSONArray refreshed = albumResponse.optJSONArray("albums");
                albums = refreshed == null ? new JSONArray() : refreshed;
                cacheAlbums();
                if (albums.length() > 0 && selectedAlbumId.isEmpty()) {
                    JSONObject first = albums.optJSONObject(0);
                    if (first != null) selectedAlbumId = first.optString("id");
                }

                runOnUiThread(() -> {
                    showHome();
                    enableMessageNotifications();
                });
                MessageNotificationJobService.schedule(this);
                if (currentUser != null && isAvatarRecognitionPending(currentUser)) pollAvatarRecognition();
            } catch (Exception error) {
                // requestJson 在 401 时已 expireSession()(清会话并切到登录页),此时 hasLocalSession()==false,无需处理。
                // 其它错误(网络不可达等)会话仍在:用缓存数据进主页,实现离线降级,避免停在 splash。
                runOnUiThread(() -> {
                    if (hasLocalSession()) {
                        showHome();
                        enableMessageNotifications();
                        MessageNotificationJobService.schedule(this);
                    }
                });
            }
        }).start();
    }

    private void pollAvatarRecognition() {
        final int revision = ++avatarRecognitionPollRevision;
        new Thread(() -> {
            for (int attempt = 0; attempt < 24; attempt++) {
                if (revision != avatarRecognitionPollRevision || !hasLocalSession()) return;
                try {
                    JSONObject response = requestJson("GET", "/api/me", null, true, true);
                    JSONObject user = response.optJSONObject("user");
                    if (user == null || revision != avatarRecognitionPollRevision) return;
                    currentUser = user;
                    syncDefaultUploader();
                    cacheCurrentUser();
                    if (user.optBoolean("hasFaceProfile") || "ready".equals(user.optString("faceProfileStatus"))) {
                        JSONObject albumResponse = requestJson("GET", "/api/albums", null, true, true);
                        JSONArray refreshed = albumResponse.optJSONArray("albums");
                        albums = refreshed == null ? new JSONArray() : refreshed;
                        cacheAlbums();
                        runOnUiThread(() -> {
                            if (isManagedPageOpen("我的资料")) {
                                showProfileDialog();
                            } else {
                                showHome();
                                statusText.setText("头像识别完成，已更新你的照片推荐");
                            }
                        });
                        return;
                    }
                    if ("failed".equals(user.optString("faceProfileStatus"))) {
                        runOnUiThread(() -> {
                            if (isManagedPageOpen("我的资料")) showProfileDialog();
                            else statusText.setText("头像未识别人脸，可以换一张更清晰的正脸头像");
                        });
                        return;
                    }
                    Thread.sleep(attempt < 4 ? 1000L : 2000L);
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    return;
                } catch (Exception error) {
                    return;
                }
            }
            if (revision == avatarRecognitionPollRevision && hasLocalSession()) {
                runOnUiThread(() -> statusText.setText("头像识别仍在后台进行，稍后刷新即可看到结果"));
            }
        }).start();
    }

    private boolean isAvatarRecognitionPending(JSONObject user) {
        if (user == null || user.optBoolean("hasFaceProfile")) return false;
        String status = user.optString("faceProfileStatus", "");
        return "queued".equals(status) || "processing".equals(status);
    }

    private String avatarRecognitionStatusText() {
        if (currentUser == null) return "头像状态：尚未识别";
        if (currentUser.optBoolean("hasFaceProfile") || "ready".equals(currentUser.optString("faceProfileStatus"))) {
            return "头像状态：已识别，可自动匹配我的照片";
        }
        String status = currentUser.optString("faceProfileStatus", "missing");
        if ("queued".equals(status) || "processing".equals(status)) return "头像状态：正在后台识别";
        if ("failed".equals(status)) return "头像状态：未识别人脸，请更换清晰正脸";
        return "头像状态：尚未上传可识别头像";
    }

    private void loadAlbums() {
        loadAlbums("");
    }

    private void loadAlbums(final String preferredAlbumId) {
        if (statusText != null) statusText.setText("正在同步相册...");
        new Thread(() -> {
            try {
                final JSONObject response = requestJson("GET", "/api/albums", null, true, true);
                albums = response.optJSONArray("albums");
                if (albums == null) albums = new JSONArray();
                String nextSelected = preferredAlbumId == null || preferredAlbumId.isEmpty() ? selectedAlbumId : preferredAlbumId;
                if (findAlbumInArray(albums, nextSelected) == null && albums.length() > 0) {
                    JSONObject first = albums.optJSONObject(0);
                    nextSelected = first == null ? "" : first.optString("id");
                }
                selectedAlbumId = nextSelected == null ? "" : nextSelected;
                cacheAlbums();
                runOnUiThread(() -> {
                    JSONObject preferred = findAlbumById(preferredAlbumId);
                    if (preferred != null && preferredAlbumId != null && !preferredAlbumId.isEmpty()) {
                        if (pendingMessageRoute != null) {
                            JSONObject message = pendingMessageRoute;
                            pendingMessageRoute = null;
                            routeMessageToAlbum(message, preferred);
                        } else {
                            showAlbumDetail(preferred);
                        }
                        statusText.setText("已打开 " + preferred.optString("name", "相册"));
                    } else {
                        renderAlbums();
                        statusText.setText(albums.length() == 0 ? "暂无相册" : "已同步 " + albums.length() + " 个相册");
                    }
                });
            } catch (final Exception error) {
                showError("读取相册失败", error);
            }
        }).start();
    }

    private void createAlbum(final String rawName, final JSONObject permissions) {
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
                body.put("permissions", permissions == null ? defaultPermissions() : permissions);
                requestJson("POST", "/api/albums", body, true, true);
                runOnUiThread(() -> {
                    if (managementDialog != null && managementDialog.isShowing()) managementDialog.dismiss();
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
                syncDefaultUploader();
                cacheCurrentUser();
                runOnUiThread(() -> {
                    showProfileDialog();
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
        statusText.setText("正在确认相册码...");
        new Thread(() -> {
            try {
                JSONObject preview = requestJson("GET", "/api/invites/" + code, null, true, true);
                JSONObject invite = preview.optJSONObject("invite");
                String albumId = invite == null ? "" : invite.optString("albumId", "");
                if ("member".equals(preview.optString("joinStatus"))) {
                    runOnUiThread(() -> {
                        if (managementDialog != null && managementDialog.isShowing()) managementDialog.dismiss();
                        statusText.setText("你已经在这个相册里，正在打开...");
                    });
                    loadAlbums(albumId);
                    return;
                }
                runOnUiThread(() -> statusText.setText("正在提交加入申请..."));
                requestJson("POST", "/api/invites/" + code + "/request", new JSONObject(), true, true);
                String albumName = invite == null ? "" : invite.optString("albumName", "");
                runOnUiThread(() -> {
                    if (managementDialog != null && managementDialog.isShowing()) managementDialog.dismiss();
                    showTransientStatus(albumName.isEmpty()
                            ? "已提交加入申请，等待相册管理员审批"
                            : "已提交加入「" + albumName + "」申请，等待相册管理员审批");
                });
            } catch (final Exception error) {
                showError("申请加入失败", error);
            }
        }).start();
    }

    private void showMessageCenter() {
        statusText.setText("正在加载消息...");
        if (messageDialog != null && messageDialog.isShowing()) messageDialog.dismiss();
        messageDialog = showManagementPage("消息提醒", managementStateContent("正在加载消息", true, null), "", null);
        new Thread(() -> {
            try {
                final JSONObject response = requestJson("GET", "/api/messages", null, true, true);
                final JSONArray messages = response.optJSONArray("messages");
                unreadMessageCount = response.optInt("unreadCount", 0);
                runOnUiThread(() -> renderMessagesDialog(messages == null ? new JSONArray() : messages, response.optInt("unreadCount", 0)));
            } catch (final Exception error) {
                runOnUiThread(() -> {
                    if (messageDialog != null && messageDialog.isShowing()) messageDialog.dismiss();
                    messageDialog = showManagementPage(
                            "消息提醒",
                            managementStateContent("加载消息失败：" + humanReadableError(error.getMessage()), false, this::showMessageCenter),
                            "",
                            null
                    );
                });
            }
        }).start();
    }

    private void updateMessageBadge() {
        if (messageBadge == null) return;
        if (unreadMessageCount > 0) {
            messageBadge.setText(unreadMessageCount > 99 ? "99+" : String.valueOf(unreadMessageCount));
            messageBadge.setVisibility(View.VISIBLE);
        } else {
            messageBadge.setVisibility(View.GONE);
        }
    }

    private void loadUnreadMessageCount() {
        if (!hasLocalSession()) return;
        new Thread(() -> {
            try {
                JSONObject response = requestJson("GET", "/api/messages/unread-count", null, true, true);
                unreadMessageCount = response.optInt("unreadCount", 0);
                runOnUiThread(() -> {
                    updateMessageBadge();
                });
            } catch (Exception ignored) {
            }
        }).start();
    }

    private void renderMessagesDialog(JSONArray messages, int unreadCount) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(8), dp(18), dp(8));
        scroll.addView(panel);
        TextView summary = text(unreadCount > 0 ? unreadCount + " 条未读消息" : "暂无未读消息", 16, SECONDARY, true);
        panel.addView(summary, matchWrap());
        if (messages.length() == 0) {
            panel.addView(text("暂无站内消息", 16, SECONDARY, false), matchWrap());
        }
        for (int i = 0; i < messages.length(); i++) {
            JSONObject message = messages.optJSONObject(i);
            if (message == null) continue;
            panel.addView(messageRow(message), matchWrap());
        }
        if (messageDialog != null && messageDialog.isShowing()) messageDialog.dismiss();
        messageDialog = showManagementPage("消息提醒", scroll, "全部已读", this::markAllMessagesRead);
    }

    private View messageRow(final JSONObject message) {
        LinearLayout row = card();
        row.setPadding(dp(14), dp(12), dp(14), dp(12));
        String unreadPrefix = message.optBoolean("isRead", message.optBoolean("read", false)) ? "" : "● ";
        LinearLayout titleRow = horizontal();
        titleRow.setGravity(Gravity.CENTER_VERTICAL);
        titleRow.addView(text(unreadPrefix + message.optString("title", "站内消息"), 18, PRIMARY, true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        String createdAt = formatTimestamp(message.optLong("createdAt", 0));
        if (!createdAt.isEmpty()) titleRow.addView(text(createdAt, 12, SECONDARY, true), trailingWrap());
        row.addView(titleRow, matchWrap());
        String body = message.optString("body", "");
        if (!body.isEmpty()) row.addView(text(body, 14, SECONDARY, false), matchWrap());
        String albumName = message.optString("albumName", "");
        if (!albumName.isEmpty()) row.addView(text("相册 · " + albumName, 13, TEAL, true), matchWrap());
        row.setOnClickListener(v -> openMessage(message));
        return row;
    }

    private void openMessage(final JSONObject message) {
        if (message == null) return;
        final boolean wasUnread = !message.optBoolean("isRead", message.optBoolean("read", false));
        new Thread(() -> {
            try {
                requestJson("POST", "/api/messages/" + message.optString("id") + "/read", null, true, true);
                if (wasUnread) unreadMessageCount = Math.max(0, unreadMessageCount - 1);
            } catch (Exception ignored) {
            }
            runOnUiThread(() -> {
                updateMessageBadge();
                if (messageDialog != null && messageDialog.isShowing()) messageDialog.dismiss();
                if (!messageRequiresAlbum(message)) {
                    showMessageCenter();
                    return;
                }
                String albumId = message.optString("albumId", "");
                JSONObject album = findAlbumById(albumId);
                if (album != null) {
                    routeMessageToAlbum(message, album);
                } else if (!albumId.isEmpty()) {
                    pendingMessageRoute = message;
                    loadAlbums(albumId);
                } else {
                    statusText.setText("消息已读");
                }
            });
        }).start();
    }

    private boolean messageRequiresAlbum(JSONObject message) {
        String type = message == null ? "" : message.optString("type", "");
        return "album.join_request".equals(type)
                || "album.permission_request".equals(type)
                || "face.my_photos_matched".equals(type);
    }

    private void routeMessageToAlbum(JSONObject message, JSONObject album) {
        String type = message == null ? "" : message.optString("type", "");
        if ("album.join_request".equals(type) || "album.permission_request".equals(type)) {
            showApprovalCenter(album);
            return;
        }
        if ("face.my_photos_matched".equals(type)) {
            activeAlbumTab = "my";
            clearPhotoSelection();
            showAlbumDetail(album);
            return;
        }
        showMessageCenter();
    }

    private void markAllMessagesRead() {
        new Thread(() -> {
            try {
                requestJson("POST", "/api/messages/mark-read", null, true, true);
                unreadMessageCount = 0;
                runOnUiThread(() -> {
                    statusText.setText("消息已全部标记为已读");
                    updateMessageBadge();
                });
            } catch (final Exception error) {
                showError("标记已读失败", error);
            }
        }).start();
    }

    private void showAlbumMembers(final JSONObject album) {
        statusText.setText("正在加载协作用户...");
        showManagedAlbumPage("协作用户", managementStateContent("正在加载协作用户", true, null));
        new Thread(() -> {
            try {
                final JSONArray members = requestJson("GET", "/api/albums/" + album.optString("id") + "/members", null, true, true).optJSONArray("members");
                runOnUiThread(() -> renderMembersDialog(album, members == null ? new JSONArray() : members));
            } catch (final Exception error) {
                runOnUiThread(() -> showManagedAlbumPage(
                        "协作用户",
                        managementStateContent("加载协作用户失败：" + humanReadableError(error.getMessage()), false, () -> showAlbumMembers(album))
                ));
            }
        }).start();
    }

    private void renderMembersDialog(final JSONObject album, JSONArray members) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(10), dp(18), dp(8));
        scroll.addView(panel);

        for (int i = 0; i < members.length(); i++) {
            JSONObject member = members.optJSONObject(i);
            if (member == null) continue;
            panel.addView(memberRow(album, member), matchWrap());
        }
        showManagedAlbumPage("协作用户", scroll);
    }

    private View memberRow(final JSONObject album, final JSONObject member) {
        LinearLayout card = card();
        card.setPadding(dp(16), dp(14), dp(16), dp(14));
        JSONObject user = member.optJSONObject("user");
        LinearLayout top = horizontal();
        top.setGravity(Gravity.CENTER_VERTICAL);
        ImageView avatar = capsuleImage();
        avatar.setContentDescription(displayUserName(user) + "的头像");
        loadImageInto(user == null ? "" : user.optString("avatarUrl", ""), avatar);
        top.addView(avatar, new LinearLayout.LayoutParams(dp(48), dp(48)));
        LinearLayout names = vertical();
        names.addView(text(displayUserName(user), 19, PRIMARY, true), matchWrap());
        names.addView(text("@" + (user == null ? member.optString("userId") : user.optString("username")) + " · " + roleText(member.optString("role")), 14, SECONDARY, true), matchWrap());
        top.addView(names, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button permissions = ghostButton("权限");
        top.addView(permissions, new LinearLayout.LayoutParams(dp(82), dp(42)));
        if (canEditMembers(album) && !"owner".equals(member.optString("role"))) {
            Button remove = ghostButton("移除");
            remove.setTextColor(Color.rgb(230, 74, 83));
            remove.setOnClickListener(v -> confirmRemoveMember(album, member));
            top.addView(remove, new LinearLayout.LayoutParams(dp(82), dp(42)));
        }
        card.addView(top, matchWrap());

        LinearLayout permissionPanel = vertical();
        permissionPanel.setVisibility(View.GONE);
        Map<String, Switch> switches = permissionSwitches(permissionPanel, member.optJSONObject("permissions"), canEditMembers(album) && !"owner".equals(member.optString("role")));
        if (canEditMembers(album) && !"owner".equals(member.optString("role"))) {
            for (Switch control : switches.values()) {
                control.setOnCheckedChangeListener((buttonView, isChecked) -> scheduleMemberPermissionsUpdate(album, member, permissionsFromSwitches(switches)));
            }
        }
        card.addView(permissionPanel, matchWrap());
        permissions.setOnClickListener(v -> {
            boolean expanding = permissionPanel.getVisibility() != View.VISIBLE;
            permissionPanel.setVisibility(expanding ? View.VISIBLE : View.GONE);
            permissions.setText(expanding ? "收起" : "权限");
        });
        return card;
    }

    private void showCollaborationRecords(final JSONObject album) {
        statusText.setText("正在加载协作记录...");
        showManagedAlbumPage("协作记录", managementStateContent("正在加载协作记录", true, null));
        new Thread(() -> {
            try {
                final JSONArray records = requestJson("GET", "/api/albums/" + album.optString("id") + "/collaboration-records", null, true, true).optJSONArray("records");
                runOnUiThread(() -> renderRecordsDialog("协作记录", records == null ? new JSONArray() : records, "暂无照片上传或删除记录"));
            } catch (final Exception error) {
                runOnUiThread(() -> showManagedAlbumPage(
                        "协作记录",
                        managementStateContent("加载协作记录失败：" + humanReadableError(error.getMessage()), false, () -> showCollaborationRecords(album))
                ));
            }
        }).start();
    }

    private void showApprovalCenter(final JSONObject album) {
        statusText.setText("正在加载审批...");
        showManagedAlbumPage("审批", managementStateContent("正在加载审批", true, null));
        new Thread(() -> {
            try {
                final JSONArray joins = requestJson("GET", "/api/albums/" + album.optString("id") + "/join-requests", null, true, true).optJSONArray("requests");
                final JSONArray permissions = canEditMembers(album)
                        ? requestJson("GET", "/api/albums/" + album.optString("id") + "/permission-requests", null, true, true).optJSONArray("requests")
                        : new JSONArray();
                runOnUiThread(() -> renderApprovalDialog(album, joins == null ? new JSONArray() : joins, permissions == null ? new JSONArray() : permissions));
            } catch (final Exception error) {
                runOnUiThread(() -> showManagedAlbumPage(
                        "审批",
                        managementStateContent("加载审批失败：" + humanReadableError(error.getMessage()), false, () -> showApprovalCenter(album))
                ));
            }
        }).start();
    }

    private void renderApprovalDialog(final JSONObject album, JSONArray joins, JSONArray permissions) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(8), dp(18), dp(8));
        scroll.addView(panel);
        panel.addView(text("加入申请", 21, PRIMARY, true), matchWrap());
        int pendingJoinCount = addJoinApprovalRows(panel, album, joins, true);
        if (pendingJoinCount == 0) panel.addView(text("暂无待审批加入申请", 15, SECONDARY, false), matchWrap());
        if (canEditMembers(album)) {
            spacer(panel, dp(12));
            panel.addView(text("权限申请", 21, PRIMARY, true), matchWrap());
            int pendingPermissionCount = addPermissionApprovalRows(panel, album, permissions, true);
            if (pendingPermissionCount == 0) panel.addView(text("暂无待审批权限申请", 15, SECONDARY, false), matchWrap());
        }
        spacer(panel, dp(12));
        panel.addView(text("已审批", 21, PRIMARY, true), matchWrap());
        int reviewed = addReviewedApprovalRows(panel, album, joins, canEditMembers(album) ? permissions : new JSONArray());
        if (reviewed == 0) panel.addView(text("暂无已审批记录", 15, SECONDARY, false), matchWrap());
        showManagedAlbumPage("审批", scroll);
    }

    private int addReviewedApprovalRows(LinearLayout panel, JSONObject album, JSONArray joins, JSONArray permissions) {
        List<ApprovalRecord> records = new ArrayList<>();
        for (int i = 0; i < joins.length(); i++) {
            JSONObject request = joins.optJSONObject(i);
            if (request != null && isReviewedApprovalStatus(request.optString("status"))) {
                records.add(new ApprovalRecord("join", request));
            }
        }
        for (int i = 0; i < permissions.length(); i++) {
            JSONObject request = permissions.optJSONObject(i);
            if (request != null && isReviewedApprovalStatus(request.optString("status"))) {
                records.add(new ApprovalRecord("permission", request));
            }
        }
        Collections.sort(records, (left, right) -> Long.compare(requestTimestamp(right.request), requestTimestamp(left.request)));
        for (ApprovalRecord record : records) {
            JSONArray single = new JSONArray().put(record.request);
            if ("join".equals(record.kind)) addJoinApprovalRows(panel, album, single, false);
            else addPermissionApprovalRows(panel, album, single, false);
        }
        return records.size();
    }

    private int addJoinApprovalRows(LinearLayout panel, JSONObject album, JSONArray requests, boolean pendingOnly) {
        int count = 0;
        for (int i = 0; i < requests.length(); i++) {
            JSONObject request = requests.optJSONObject(i);
            if (request == null) continue;
            boolean pending = "pending".equals(request.optString("status"));
            if (pendingOnly != pending) continue;
            if (!pendingOnly && !isReviewedApprovalStatus(request.optString("status"))) continue;
            JSONObject user = request.optJSONObject("user");
            LinearLayout row = card();
            row.setPadding(dp(14), dp(12), dp(14), dp(12));
            row.addView(approvalTitleRow("加入申请" + statusLabel(request.optString("status")), requestTimestamp(request)), matchWrap());
            row.addView(text("申请加入相册", 15, SECONDARY, false), matchWrap());
            row.addView(text(userIdentity(user), 14, TEAL, true), matchWrap());
            if (!pending) addReviewerDetails(row, request);
            if (pending) addReviewButtons(row, () -> reviewJoin(album, request, true), () -> reviewJoin(album, request, false));
            panel.addView(row, matchWrap());
            count++;
        }
        return count;
    }

    private int addPermissionApprovalRows(LinearLayout panel, JSONObject album, JSONArray requests, boolean pendingOnly) {
        int count = 0;
        for (int i = 0; i < requests.length(); i++) {
            JSONObject request = requests.optJSONObject(i);
            if (request == null) continue;
            boolean pending = "pending".equals(request.optString("status"));
            if (pendingOnly != pending) continue;
            if (!pendingOnly && !isReviewedApprovalStatus(request.optString("status"))) continue;
            JSONObject user = request.optJSONObject("user");
            LinearLayout row = card();
            row.setPadding(dp(14), dp(12), dp(14), dp(12));
            row.addView(approvalTitleRow("权限申请" + statusLabel(request.optString("status")), requestTimestamp(request)), matchWrap());
            row.addView(text("申请：" + permissionSummary(request.optJSONObject("requestedPermissions")), 15, TEAL, true), matchWrap());
            row.addView(text("当前：" + permissionSummary(request.optJSONObject("currentPermissions")), 14, SECONDARY, true), matchWrap());
            row.addView(text(userIdentity(user), 14, TEAL, true), matchWrap());
            if (!pending) addReviewerDetails(row, request);
            if (pending) addReviewButtons(row, () -> reviewPermission(album, request, true), () -> reviewPermission(album, request, false));
            panel.addView(row, matchWrap());
            count++;
        }
        return count;
    }

    private void addReviewerDetails(LinearLayout row, JSONObject request) {
        JSONObject reviewer = request.optJSONObject("reviewedByUser");
        if (reviewer == null) return;
        row.addView(text("处理人 · " + userNameOnly(reviewer), 13, SECONDARY, true), matchWrap());
    }

    private void renderRecordsDialog(String title, JSONArray records, String emptyText) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(8), dp(18), dp(8));
        scroll.addView(panel);
        int visibleRecords = 0;
        for (int i = 0; i < records.length(); i++) {
            JSONObject record = records.optJSONObject(i);
            if (record != null && isCollaborationRecordType(record.optString("type"))) visibleRecords++;
        }
        if (visibleRecords == 0) {
            panel.addView(text(emptyText, 16, SECONDARY, false), matchWrap());
        }
        for (int i = 0; i < records.length(); i++) {
            JSONObject record = records.optJSONObject(i);
            if (record == null) continue;
            if (!isCollaborationRecordType(record.optString("type"))) continue;
            LinearLayout row = card();
            row.setPadding(dp(14), dp(12), dp(14), dp(12));
            LinearLayout titleRow = horizontal();
            titleRow.setGravity(Gravity.CENTER_VERTICAL);
            titleRow.addView(text(record.optString("title", "协作动态"), 18, PRIMARY, true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            String createdAt = formatTimestamp(record.optLong("createdAt", 0));
            if (!createdAt.isEmpty()) titleRow.addView(text(createdAt, 12, SECONDARY, true), trailingWrap());
            row.addView(titleRow, matchWrap());
            String message = record.optString("message", "");
            if (!message.isEmpty()) row.addView(text(message, 14, SECONDARY, false), matchWrap());
            JSONObject actor = record.optJSONObject("actor");
            String actorName = actor == null ? record.optString("actorName", "") : displayUserName(actor);
            if (!actorName.isEmpty()) row.addView(text("操作人 · " + actorName, 13, TEAL, true), matchWrap());
            panel.addView(row, matchWrap());
        }
        showManagedAlbumPage(title, scroll);
    }

    private boolean isReviewedApprovalStatus(String status) {
        return "approved".equals(status) || "rejected".equals(status);
    }

    private boolean isCollaborationRecordType(String type) {
        return "photo.upload".equals(type) || "photo.delete".equals(type);
    }

    private void showPermissionDenied(final JSONObject album, String action, final String permissionKey) {
        JSONObject owner = album == null ? null : album.optJSONObject("ownerUser");
        showTransientStatus(
                "你没有" + action + "权限，请联系相册创建者授权。点按申请权限",
                () -> showPermissionRequestDialog(album, permissionKey),
                owner,
                ownerDisplayName(album)
        );
    }

    private void showPermissionRequestDialog(final JSONObject album, final String requestedKey) {
        statusText.setText("正在读取权限申请...");
        showManagedAlbumPage("申请权限", managementStateContent("正在加载申请进度", true, null));
        new Thread(() -> {
            try {
                final JSONArray requests = requestJson("GET", "/api/albums/" + album.optString("id") + "/permission-requests", null, true, true).optJSONArray("requests");
                runOnUiThread(() -> renderPermissionRequestDialog(album, requests == null ? new JSONArray() : requests, requestedKey));
            } catch (final Exception error) {
                runOnUiThread(() -> showManagedAlbumPage(
                        "申请权限",
                        managementStateContent("读取申请进度失败：" + humanReadableError(error.getMessage()), false, () -> showPermissionRequestDialog(album, requestedKey))
                ));
            }
        }).start();
    }

    private void renderPermissionRequestDialog(final JSONObject album, JSONArray requests, String requestedKey) {
        JSONObject latest = latestRequest(requests);
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = vertical();
        panel.setPadding(dp(18), dp(12), dp(18), dp(24));
        scroll.addView(panel);
        JSONObject owner = album.optJSONObject("ownerUser");
        LinearLayout ownerRow = horizontal();
        ownerRow.setGravity(Gravity.CENTER_VERTICAL);
        ImageView avatar = capsuleImage();
        avatar.setContentDescription(ownerDisplayName(album) + "的头像");
        loadImageInto(owner == null ? "" : owner.optString("avatarUrl", ""), avatar);
        ownerRow.addView(avatar, new LinearLayout.LayoutParams(dp(56), dp(56)));
        LinearLayout ownerTexts = vertical();
        ownerTexts.addView(text("向创建者申请", 15, SECONDARY, true), matchWrap());
        ownerTexts.addView(text(ownerDisplayName(album), 23, PRIMARY, true), matchWrap());
        ownerRow.addView(ownerTexts, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        panel.addView(ownerRow, matchWrap());
        spacer(panel, dp(12));

        if (latest != null && "pending".equals(latest.optString("status"))) {
            panel.addView(text("待创建者审批", 22, PRIMARY, true), matchWrap());
            panel.addView(text("申请权限：" + permissionSummary(latest.optJSONObject("requestedPermissions")), 16, SECONDARY, true), matchWrap());
            String submittedAt = formatTimestamp(latest.optLong("createdAt", 0));
            if (!submittedAt.isEmpty()) panel.addView(text("提交时间：" + submittedAt, 14, SECONDARY, true), matchWrap());
            panel.addView(text("这次申请还在审批中，暂时不能重复提交新的申请。", 14, SECONDARY, false), matchWrap());
            spacer(panel, dp(18));
            Button cancel = outlineButton("撤销申请");
            cancel.setTextColor(Color.rgb(230, 74, 83));
            cancel.setOnClickListener(v -> cancelPermissionRequest(album, latest));
            LinearLayout.LayoutParams cancelParams = matchWrap();
            cancelParams.height = dp(58);
            panel.addView(cancel, cancelParams);
            showManagedAlbumPage("申请权限", scroll);
            return;
        }

        if (latest != null) {
            panel.addView(text("上次申请" + statusLabel(latest.optString("status")) + "：" + permissionSummary(latest.optJSONObject("requestedPermissions")), 15, SECONDARY, true), matchWrap());
            spacer(panel, dp(8));
        }
        panel.addView(text("申请开通的权限", 20, PRIMARY, true), matchWrap());
        JSONObject initial = permissionsObject(album, "currentUserMemberPermissions");
        if (requestedKey != null && !requestedKey.isEmpty()) {
            try { initial.put(requestedKey, true); } catch (Exception ignored) {}
        }
        Map<String, Switch> switches = permissionSwitches(panel, initial, true);
        spacer(panel, dp(20));
        Button submit = primaryButton("提交申请");
        submit.setOnClickListener(v -> submitPermissionRequest(album, permissionsFromSwitches(switches)));
        LinearLayout.LayoutParams submitParams = matchWrap();
        submitParams.height = dp(60);
        panel.addView(submit, submitParams);
        showManagedAlbumPage("申请权限", scroll);
    }

    private void confirmDeleteOrLeaveAlbum(final JSONObject album) {
        boolean owner = canEditMembers(album);
        new AlertDialog.Builder(this)
                .setTitle(owner ? "删除相册？" : "退出相册？")
                .setMessage(owner ? "会删除整个相册和其中的照片分类。" : "退出后你将不再看到这个相册，可通过分享链接重新申请加入。")
                .setNegativeButton("取消", null)
                .setPositiveButton(owner ? "删除" : "退出", (dialog, which) -> deleteOrLeaveAlbum(album))
                .show();
    }

    private void showRenameAlbumDialog(final JSONObject album) {
        EditText name = field("相册名称", false);
        name.setText(album.optString("name", ""));
        new AlertDialog.Builder(this)
                .setTitle("重命名相册")
                .setView(name)
                .setNegativeButton("取消", null)
                .setPositiveButton("保存", (dialog, which) -> renameAlbum(album, name.getText().toString()))
                .show();
    }

    private void renameAlbum(final JSONObject album, final String rawName) {
        final String name = rawName == null ? "" : rawName.trim();
        if (name.isEmpty()) {
            statusText.setText("相册名不能为空");
            return;
        }
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("name", name);
                JSONObject response = requestJson("POST", "/api/albums/" + album.optString("id") + "/rename", body, true, true);
                updateAlbumFromResponse(response);
                runOnUiThread(() -> statusText.setText("相册名已保存"));
            } catch (final Exception error) {
                showError("保存失败", error);
            }
        }).start();
    }

    private void deleteOrLeaveAlbum(final JSONObject album) {
        statusText.setText(canEditMembers(album) ? "正在删除相册..." : "正在退出相册...");
        new Thread(() -> {
            try {
                requestJson("DELETE", "/api/albums/" + album.optString("id"), null, true, true);
                runOnUiThread(() -> {
                    showHome();
                    statusText.setText(canEditMembers(album) ? "相册已删除" : "已退出相册");
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError(canEditMembers(album) ? "删除失败" : "退出失败", error);
            }
        }).start();
    }

    private void updateMemberPermissions(final JSONObject album, final JSONObject member, final JSONObject permissions) {
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("permissions", permissions);
                requestJson("POST", "/api/albums/" + album.optString("id") + "/members/" + member.optString("userId") + "/permissions", body, true, true);
                runOnUiThread(() -> statusText.setText("成员权限已保存"));
            } catch (final Exception error) {
                showError("保存成员权限失败", error);
            }
        }).start();
    }

    private void scheduleMemberPermissionsUpdate(final JSONObject album, final JSONObject member, final JSONObject permissions) {
        String memberId = member.optString("userId");
        Runnable previous = pendingMemberPermissionSaves.remove(memberId);
        if (previous != null) mainHandler.removeCallbacks(previous);
        Runnable save = () -> {
            pendingMemberPermissionSaves.remove(memberId);
            updateMemberPermissions(album, member, permissions);
        };
        pendingMemberPermissionSaves.put(memberId, save);
        mainHandler.postDelayed(save, 250L);
    }

    private void confirmRemoveMember(final JSONObject album, final JSONObject member) {
        JSONObject user = member.optJSONObject("user");
        new AlertDialog.Builder(this)
                .setTitle("移除协作用户？")
                .setMessage("移除 " + displayUserName(user) + " 后，对方将不再看到这个相册。")
                .setNegativeButton("取消", null)
                .setPositiveButton("移除", (dialog, which) -> removeMember(album, member))
                .show();
    }

    private void removeMember(final JSONObject album, final JSONObject member) {
        new Thread(() -> {
            try {
                requestJson("DELETE", "/api/albums/" + album.optString("id") + "/members/" + member.optString("userId"), null, true, true);
                runOnUiThread(() -> {
                    statusText.setText("协作用户已移除");
                    showAlbumMembers(album);
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError("移除失败", error);
            }
        }).start();
    }

    private void reviewJoin(final JSONObject album, final JSONObject request, final boolean approve) {
        new Thread(() -> {
            try {
                requestJson("POST", "/api/albums/" + album.optString("id") + "/join-requests/" + request.optString("id") + "/" + (approve ? "approve" : "reject"), null, true, true);
                runOnUiThread(() -> {
                    statusText.setText(approve ? "已批准加入申请" : "已拒绝加入申请");
                    showApprovalCenter(album);
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError("处理失败", error);
            }
        }).start();
    }

    private void reviewPermission(final JSONObject album, final JSONObject request, final boolean approve) {
        new Thread(() -> {
            try {
                requestJson("POST", "/api/albums/" + album.optString("id") + "/permission-requests/" + request.optString("id") + "/" + (approve ? "approve" : "reject"), null, true, true);
                runOnUiThread(() -> {
                    statusText.setText(approve ? "已批准权限申请" : "已拒绝权限申请");
                    showApprovalCenter(album);
                    loadAlbums();
                });
            } catch (final Exception error) {
                showError("处理失败", error);
            }
        }).start();
    }

    private void submitPermissionRequest(final JSONObject album, final JSONObject permissions) {
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("permissions", permissions);
                JSONObject response = requestJson("POST", "/api/albums/" + album.optString("id") + "/permission-requests", body, true, true);
                runOnUiThread(() -> {
                    if (managementDialog != null && managementDialog.isShowing()) managementDialog.dismiss();
                    showTransientStatus(response.optString("message", "权限申请已提交，等待创建者审批"));
                });
            } catch (final Exception error) {
                showError("提交申请失败", error);
            }
        }).start();
    }

    private void cancelPermissionRequest(final JSONObject album, final JSONObject request) {
        new Thread(() -> {
            try {
                requestJson("DELETE", "/api/albums/" + album.optString("id") + "/permission-requests/" + request.optString("id"), null, true, true);
                runOnUiThread(() -> {
                    statusText.setText("权限申请已撤销");
                    showPermissionRequestDialog(album, "");
                });
            } catch (final Exception error) {
                showError("撤销失败", error);
            }
        }).start();
    }

    private void startUploadState(String albumId, int count) {
        albumRecognitionPollRevision++;
        isUploading = true;
        activeUploadAlbumId = albumId == null ? "" : albumId;
        uploadCancelRequested = false;
        uploadSelectedCount = count;
        uploadUploadedCount = 0;
        uploadBaselinePhotoIds.clear();
        uploadCreatedPhotoIds.clear();
        JSONObject album = findAlbumById(activeUploadAlbumId);
        if (album != null) uploadBaselinePhotoIds.addAll(photoIds(album));
        uploadProgressText = "正在准备 " + count + " 个文件，点击底部进度可取消";
        statusText.setText(uploadProgressText);
        refreshCurrentAlbumView();
    }

    private void finishUploadState(String message) {
        isUploading = false;
        activeUploadAlbumId = "";
        uploadCancelRequested = false;
        uploadProgressText = "";
        uploadSelectedCount = 0;
        uploadUploadedCount = 0;
        uploadBaselinePhotoIds.clear();
        uploadCreatedPhotoIds.clear();
        runOnUiThread(() -> {
            if (statusText != null) statusText.setText(message);
            refreshCurrentAlbumView();
        });
    }

    private void updateUploadProgress(String message, int done, int total) {
        uploadUploadedCount = Math.max(uploadUploadedCount, done);
        uploadProgressText = message;
        runOnUiThread(() -> {
            if (statusText != null) statusText.setText(message);
            JSONObject album = findAlbumById(activeUploadAlbumId);
            if (album != null && activeUploadAlbumId.equals(selectedAlbumId)) {
                showAlbumDetail(album);
            }
        });
    }

    private void confirmCancelUpload() {
        new AlertDialog.Builder(this)
                .setTitle("取消正在上传的照片？")
                .setMessage("会尽快停止本次上传。已经提交到后台的照片可能仍会继续整理，稍后可在相册里删除。")
                .setNegativeButton("继续上传", null)
                .setPositiveButton("取消上传", (dialog, which) -> {
                    uploadCancelRequested = true;
                    uploadProgressText = "正在取消上传...";
                    if (statusText != null) statusText.setText(uploadProgressText);
                    refreshCurrentAlbumView();
                })
                .show();
    }

    private void ensureUploadNotCancelled() {
        if (uploadCancelRequested) throw new IllegalStateException("上传已取消");
    }

    private void refreshCurrentAlbumView() {
        JSONObject album = currentAlbum != null ? currentAlbum : findAlbumById(selectedAlbumId);
        if (album == null) return;
        JSONObject folder = findFolderById(album, activeFolderId);
        if ("folder".equals(currentScreen) && folder != null) showFolderDialog(album, folder);
        else showAlbumDetail(album);
    }

    private void pickFiles() {
        if (pendingUploadAlbumId.isEmpty()) {
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
        if (requestCode == REQUEST_PICK_REGISTER_AVATAR && resultCode == RESULT_OK && data != null && data.getData() != null) {
            registerAvatarUri = data.getData();
            if (registerAvatarPreview != null) {
                registerAvatarPreview.clearColorFilter();
                registerAvatarPreview.setImageURI(registerAvatarUri);
            }
            return;
        }
        if (requestCode == REQUEST_PICK_AVATAR && resultCode == RESULT_OK && data != null && data.getData() != null) {
            statusText.setText("头像已选择，正在上传识别...");
            final Uri avatarUri = data.getData();
            new Thread(() -> {
                try {
                    uploadAvatar(avatarUri, true);
                    runOnUiThread(() -> {
                        showProfileDialog();
                        statusText.setText("头像已更新，后台正在匹配你的照片");
                        loadAlbums();
                    });
                    pollAvatarRecognition();
                } catch (final Exception error) {
                    showError("头像上传失败", error);
                }
            }).start();
            return;
        }
        if (requestCode == REQUEST_PICK_QR_IMAGE && resultCode == RESULT_OK && data != null && data.getData() != null) {
            final Uri imageUri = data.getData();
            statusText.setText("正在识别二维码...");
            new Thread(() -> {
                try {
                    final String raw = decodeQRCode(decodeBitmapFromUri(imageUri));
                    runOnUiThread(() -> applyScannedInviteCode(raw));
                } catch (final Exception error) {
                    showError("二维码识别失败", error);
                }
            }).start();
            return;
        }
        if (requestCode == REQUEST_CAPTURE_QR && resultCode == RESULT_OK && data != null) {
            String raw = data.getStringExtra(QRCodeScannerActivity.EXTRA_SCAN_RESULT);
            if (raw != null && !raw.trim().isEmpty()) applyScannedInviteCode(raw);
            return;
        }
        if (requestCode != REQUEST_PICK_FILES) return;
        final String uploadAlbumId = pendingUploadAlbumId;
        pendingUploadAlbumId = "";
        if (resultCode != RESULT_OK || data == null || uploadAlbumId.isEmpty()) return;
        final List<Uri> uris = new ArrayList<>();
        if (data.getClipData() != null) {
            for (int i = 0; i < data.getClipData().getItemCount(); i++) {
                uris.add(data.getClipData().getItemAt(i).getUri());
            }
        } else if (data.getData() != null) {
            uris.add(data.getData());
        }
        if (uris.isEmpty()) return;
        startUploadState(uploadAlbumId, uris.size());
        new Thread(() -> {
            try {
                directUpload(uploadAlbumId, uris);
                runOnUiThread(() -> {
                    finishUploadState("上传完成，后台开始整理");
                    loadAlbums();
                });
                pollAlbumRecognition(uploadAlbumId);
            } catch (final Exception error) {
                if (uploadCancelRequested) {
                    cleanupCanceledUpload(uploadAlbumId);
                } else {
                    finishUploadState("上传失败");
                    showError("上传失败", error);
                }
            }
        }).start();
    }

    private Bitmap decodeBitmapFromUri(Uri uri) throws Exception {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        try (InputStream input = getContentResolver().openInputStream(uri)) {
            BitmapFactory.decodeStream(input, null, bounds);
        }
        int sample = 1;
        int longest = Math.max(bounds.outWidth, bounds.outHeight);
        while (longest / sample > 1800) sample *= 2;
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = Math.max(1, sample);
        try (InputStream input = getContentResolver().openInputStream(uri)) {
            Bitmap bitmap = BitmapFactory.decodeStream(input, null, options);
            if (bitmap == null) throw new IllegalStateException("无法读取这张二维码图片");
            return bitmap;
        }
    }

    private String decodeQRCode(Bitmap bitmap) throws Exception {
        int width = bitmap.getWidth();
        int height = bitmap.getHeight();
        int[] pixels = new int[width * height];
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height);
        RGBLuminanceSource source = new RGBLuminanceSource(width, height, pixels);
        BinaryBitmap binaryBitmap = new BinaryBitmap(new HybridBinarizer(source));
        MultiFormatReader reader = new MultiFormatReader();
        Map<DecodeHintType, Object> hints = new EnumMap<>(DecodeHintType.class);
        hints.put(DecodeHintType.TRY_HARDER, Boolean.TRUE);
        try {
            Result result = reader.decode(binaryBitmap, hints);
            return result == null ? "" : result.getText();
        } catch (NotFoundException error) {
            throw new IllegalStateException("没有在图片里识别到 PicMe 分享二维码");
        } finally {
            reader.reset();
        }
    }

    private void applyScannedInviteCode(String raw) {
        String code = inviteCodeFrom(raw);
        if (code.isEmpty()) {
            statusText.setText("二维码不是有效的 PicMe 相册分享码");
            return;
        }
        if (inviteCodeInput != null) inviteCodeInput.setText(code);
        statusText.setText("已识别相册码：" + code);
        showJoinDialog(code);
    }

    private void directUpload(String albumId, List<Uri> uris) throws Exception {
        String uploader = pendingUploader.trim();
        if (uploader.isEmpty()) uploader = "访客";
        Map<String, Uri> uriById = new HashMap<>();
        JSONArray files = new JSONArray();
        for (int i = 0; i < uris.size(); i++) {
            ensureUploadNotCancelled();
            updateUploadProgress("正在准备第 " + (i + 1) + "/" + uris.size() + " 个文件", i, uris.size());
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
        updateUploadProgress("正在准备上传", 0, Math.max(uris.size(), 1));
        JSONObject init = requestJson("POST", "/api/albums/" + albumId + "/uploads/init", initBody, true, true);
        JSONArray uploads = init.optJSONArray("uploads");
        if (uploads == null || uploads.length() == 0) throw new IllegalStateException("没有可上传的文件");
        for (int i = 0; i < uploads.length(); i++) {
            ensureUploadNotCancelled();
            updateUploadProgress("正在上传第 " + (i + 1) + "/" + uploads.length() + " 张，点击进度可取消", i, uploads.length());
            JSONObject upload = uploads.getJSONObject(i);
            putSignedResource(upload.getJSONObject("image"), uriById);
            if (!upload.isNull("video")) putSignedResource(upload.getJSONObject("video"), uriById);
            uploadUploadedCount = i + 1;
            updateUploadProgress("已上传 " + uploadUploadedCount + "/" + uploads.length() + " 张", uploadUploadedCount, uploads.length());
        }
        ensureUploadNotCancelled();
        JSONObject completeBody = new JSONObject();
        completeBody.put("uploader", uploader);
        completeBody.put("uploads", uploads);
        updateUploadProgress("正在提交照片", uploads.length(), uploads.length());
        JSONObject response = requestJson("POST", "/api/albums/" + albumId + "/uploads/complete", completeBody, true, true);
        JSONArray createdIds = response.optJSONArray("photoIds");
        if (createdIds != null) {
            for (int i = 0; i < createdIds.length(); i++) {
                String id = createdIds.optString(i);
                if (!id.isEmpty()) uploadCreatedPhotoIds.add(id);
            }
        }
    }

    private void cleanupCanceledUpload(String albumId) {
        updateUploadProgress("正在取消上传，并清理本次照片", 0, Math.max(uploadSelectedCount, 1));
        Set<String> pendingIds = new HashSet<>(uploadCreatedPhotoIds);
        String cleanupError = "";
        for (int attempt = 0; attempt < 4; attempt++) {
            try {
                if (attempt > 0) Thread.sleep(attempt * 900L);
                JSONObject response = requestJson("GET", "/api/albums/" + albumId, null, true, true);
                JSONObject latest = response.optJSONObject("album");
                if (latest == null && albumId.equals(response.optString("id"))) latest = response;
                if (latest != null) {
                    Set<String> latestIds = photoIds(latest);
                    latestIds.removeAll(uploadBaselinePhotoIds);
                    pendingIds.addAll(latestIds);
                }
                if (pendingIds.isEmpty()) continue;
                JSONObject body = new JSONObject();
                body.put("photoIds", new JSONArray(pendingIds));
                JSONObject deleted = requestJson("POST", "/api/albums/" + albumId + "/photos/delete-selected", body, true, true);
                JSONObject updated = deleted.optJSONObject("album");
                if (updated != null) replaceAlbumInCache(updated);
                pendingIds.clear();
                cleanupError = "";
                break;
            } catch (Exception error) {
                cleanupError = humanReadableError(error.getMessage());
            }
        }
        final String message = pendingIds.isEmpty()
                ? "上传已取消，本次照片已清理"
                : "上传已取消，但清理失败：" + (cleanupError.isEmpty() ? "请稍后手动删除本次照片" : cleanupError);
        runOnUiThread(() -> {
            finishUploadState(message);
            loadAlbums();
        });
    }

    private Set<String> photoIds(JSONObject album) {
        Set<String> ids = new HashSet<>();
        JSONArray photos = safeArray(album, "photos");
        for (int i = 0; i < photos.length(); i++) {
            JSONObject photo = photos.optJSONObject(i);
            if (photo != null && !photo.optString("id").isEmpty()) ids.add(photo.optString("id"));
        }
        return ids;
    }

    private void pollAlbumRecognition(String albumId) {
        final int revision = ++albumRecognitionPollRevision;
        new Thread(() -> {
            for (int attempt = 0; attempt < 30; attempt++) {
                if (revision != albumRecognitionPollRevision || !hasLocalSession()) return;
                try {
                    if (attempt > 0) Thread.sleep(1500L);
                    if (revision != albumRecognitionPollRevision || !hasLocalSession()) return;
                    JSONObject response = requestJson("GET", "/api/albums/" + albumId, null, true, true);
                    JSONObject latest = response.optJSONObject("album");
                    if (latest == null && albumId.equals(response.optString("id"))) latest = response;
                    if (latest == null) continue;
                    replaceAlbumInCache(latest);
                    JSONArray photos = safeArray(latest, "photos");
                    int active = 0;
                    int ready = 0;
                    int failed = 0;
                    for (int i = 0; i < photos.length(); i++) {
                        JSONObject photo = photos.optJSONObject(i);
                        if (photo == null) continue;
                        String status = photo.optString("status", "ready");
                        if ("queued".equals(status) || "preparing".equals(status) || "processing".equals(status)) active++;
                        else if ("failed".equals(status)) failed++;
                        else ready++;
                    }
                    final JSONObject refreshed = latest;
                    final int activeCount = active;
                    final int readyCount = ready;
                    final int failedCount = failed;
                    runOnUiThread(() -> {
                        if (albumId.equals(selectedAlbumId) && ("album".equals(currentScreen) || "folder".equals(currentScreen))) {
                            if ("folder".equals(currentScreen)) {
                                JSONObject folder = findFolderById(refreshed, activeFolderId);
                                if (folder != null) showFolderDialog(refreshed, folder);
                                else showAlbumDetail(refreshed);
                            } else {
                                showAlbumDetail(refreshed);
                            }
                        }
                        if (activeCount > 0) {
                            statusText.setText(activeCount + " 张照片正在整理，已完成 " + readyCount + " 张");
                        }
                    });
                    if (active == 0) {
                        runOnUiThread(() -> showTransientStatus(
                                failedCount > 0
                                        ? "照片整理完成：" + readyCount + " 张可查看，" + failedCount + " 张需要稍后再看"
                                        : "照片整理完成，人物小相册已更新"
                        ));
                        return;
                    }
                } catch (Exception error) {
                    if (attempt >= 2) return;
                }
            }
            runOnUiThread(() -> showTransientStatus("照片较多，后台会继续整理，稍后刷新即可看到结果"));
        }).start();
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
        if (code == 401) expireSession();
        if (code < 200 || code >= 300) throw new IllegalStateException(text.isEmpty() ? ("请求失败：" + code) : text);
        JSONObject response = text.isEmpty() ? new JSONObject() : new JSONObject(text);
        imageCache.evictAll();
        currentUser = response.optJSONObject("user");
        syncDefaultUploader();
        cacheCurrentUser();
    }

    private JSONObject registerRequest(String username, String nickname, String password, Uri avatarUri) throws Exception {
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
        if (avatarUri != null) writeMultipartFile(output, boundary, "avatar", avatarUri);
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

    private void writeMultipartFile(OutputStream output, String boundary, String fieldName, Uri uri) throws Exception {
        String filename = displayName(uri);
        String mimeType = contentType(uri, filename);
        output.write(("--" + boundary + "\r\n").getBytes("UTF-8"));
        output.write(("Content-Disposition: form-data; name=\"" + fieldName + "\"; filename=\"" + filename + "\"\r\n").getBytes("UTF-8"));
        output.write(("Content-Type: " + mimeType + "\r\n\r\n").getBytes("UTF-8"));
        try (InputStream input = getContentResolver().openInputStream(uri)) {
            if (input == null) throw new IllegalStateException("无法读取头像文件");
            byte[] buffer = new byte[1024 * 64];
            int read;
            while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
        }
        output.write("\r\n".getBytes("UTF-8"));
    }

    private void logoutServer(String accessToken) {
        try {
            HttpURLConnection connection = (HttpURLConnection) new URL(PRODUCTION_BASE_URL + "/api/auth/logout").openConnection();
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Authorization", "Bearer " + accessToken);
            connection.getResponseCode();
            connection.disconnect();
        } catch (Exception ignored) {
            // Local logout has already completed; server revocation is best effort.
        }
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
        while ((read = input.read(buffer)) != -1) {
            ensureUploadNotCancelled();
            output.write(buffer, 0, read);
        }
        input.close();
        output.flush();
        output.close();
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) throw new IllegalStateException(readAll(connection.getErrorStream(), "文件上传失败：" + code));
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
        if (code == 401 && auth) {
            if (retryRefresh && refreshTokens()) return requestJson(method, path, body, true, false);
            expireSession();
            throw new IllegalStateException("登录已失效，请重新登录");
        }
        if (code < 200 || code >= 300) throw new IllegalStateException(text.isEmpty() ? ("请求失败：" + code) : text);
        return text.isEmpty() ? new JSONObject() : new JSONObject(text);
    }

    private void expireSession() {
        avatarRecognitionPollRevision++;
        albumRecognitionPollRevision++;
        prefs.edit()
                .remove("accessToken")
                .remove("refreshToken")
                .remove(CACHE_ALBUMS)
                .remove(CACHE_USER)
                .apply();
        MessageNotificationJobService.cancel(this);
        albums = new JSONArray();
        selectedAlbumId = "";
        currentAlbum = null;
        currentUser = null;
        runOnUiThread(() -> {
            showLogin();
            showTransientStatus("登录已失效，请重新登录");
        });
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

    private boolean isValidUsername(String value) {
        return value != null && value.matches("^[A-Za-z0-9_]{1,20}$");
    }

    private boolean isValidPasswordFormat(String value) {
        if (value == null || value.length() < 6 || value.length() > 20) return false;
        for (int i = 0; i < value.length(); i++) {
            char character = value.charAt(i);
            if (character < 0x21 || character > 0x7E) return false;
        }
        return true;
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
            if (!cachedUser.isEmpty()) {
                currentUser = new JSONObject(cachedUser);
                syncDefaultUploader();
            }
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

    private PhotoDiskCache diskCache() {
        if (diskCache == null) diskCache = new PhotoDiskCache(getApplicationContext(), 512L * 1024 * 1024);
        return diskCache;
    }

    // 三级缓存：内存(已解码 Bitmap) → 磁盘(原始文件，对齐 iOS) → 网络。
    // 内存 key 带目标尺寸档位，缩略图/大图各自按需降采样、互不污染。
    private void loadImageInto(String path, ImageView target) {
        loadImageInto(path, target, null);
    }

    // onComplete 在图片就绪/失败后于 UI 线程回调（缓存命中或加载结束都会调用），供调用方隐藏 loading。
    private void loadImageInto(String path, ImageView target, final Runnable onComplete) {
        String absolute = absoluteURL(path);
        if (absolute.isEmpty()) {
            target.setImageDrawable(placeholderDrawable());
            if (onComplete != null) onComplete.run();
            return;
        }
        String idKey = absolute.contains("?") ? absolute.substring(0, absolute.indexOf('?')) : absolute;
        final int reqPx = requestedSizePx(target);
        final String memKey = idKey + "#" + reqPx;
        target.setTag(memKey);
        Bitmap cached = imageCache.get(memKey);
        if (cached != null) {
            target.setImageBitmap(cached);
            if (onComplete != null) onComplete.run();
            return;
        }
        target.setImageDrawable(placeholderDrawable());
        new Thread(() -> {
            Bitmap bitmap = null;
            try {
                File file = diskCache().fetch(absolute);
                bitmap = decodeSampled(file, reqPx);
                if (bitmap != null) imageCache.put(memKey, bitmap);
            } catch (Exception ignored) {
            }
            final Bitmap result = bitmap;
            runOnUiThread(() -> {
                if (result != null && memKey.equals(target.getTag())) target.setImageBitmap(result);
                if (onComplete != null) onComplete.run();
            });
        }).start();
    }

    /** 估算目标显示像素：优先布局尺寸，其次已测量尺寸，最后兜底屏幕宽；量化到 64 的整数倍以稳定缓存 key。 */
    private int requestedSizePx(ImageView target) {
        int px = 0;
        ViewGroup.LayoutParams lp = target.getLayoutParams();
        if (lp != null) px = Math.max(lp.width, lp.height);
        if (px <= 0) px = Math.max(target.getWidth(), target.getHeight());
        if (px <= 0) px = getResources().getDisplayMetrics().widthPixels;
        return Math.max(64, ((px + 63) / 64) * 64);
    }

    private Bitmap decodeSampled(File file, int reqPx) {
        String filePath = file.getAbsolutePath();
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(filePath, bounds);
        int longest = Math.max(bounds.outWidth, bounds.outHeight);
        int sample = 1;
        // 保留约 2x 余量，避免缩略图发虚。
        while (longest > 0 && longest / (sample * 2) > reqPx) sample *= 2;
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inSampleSize = Math.max(1, sample);
        Bitmap decoded = BitmapFactory.decodeFile(filePath, opts);
        if (decoded == null) {
            // 文件可能损坏(半截下载等)：删掉缓存让下次重新拉取。
            file.delete();
        }
        return decoded;
    }

    private String absoluteURL(String path) {
        if (path == null || path.isEmpty()) return "";
        if (path.startsWith("http://") || path.startsWith("https://")) return path;
        return PRODUCTION_BASE_URL + (path.startsWith("/") ? path : "/" + path);
    }

    private String inviteCodeFrom(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) return "";
        String inviteParam = queryParameter(value, "invite");
        if (!inviteParam.isEmpty()) value = inviteParam;
        int index = value.indexOf("/join/");
        if (index >= 0) value = value.substring(index + 6);
        int query = value.indexOf('?');
        if (query >= 0) value = value.substring(0, query);
        int fragment = value.indexOf('#');
        if (fragment >= 0) value = value.substring(0, fragment);
        int slash = value.indexOf('/');
        if (slash >= 0) value = value.substring(0, slash);
        return value.replaceAll("[^A-Za-z0-9_-]", "").toUpperCase(Locale.ROOT);
    }

    private String queryParameter(String raw, String name) {
        if (raw == null || name == null || name.isEmpty()) return "";
        try {
            Uri uri = Uri.parse(raw);
            String value = uri.getQueryParameter(name);
            return value == null ? "" : value.trim();
        } catch (Exception ignored) {
            return "";
        }
    }

    private String assetIdFromName(String filename) {
        int dot = filename.lastIndexOf('.');
        return dot > 0 ? filename.substring(0, dot).toLowerCase(Locale.ROOT) : filename.toLowerCase(Locale.ROOT);
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
        String lower = filename.toLowerCase(Locale.ROOT);
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
        String detail = humanReadableError(error == null ? null : error.getMessage());
        showTransientStatus(prefix + "：" + detail);
    }

    private String humanReadableError(String raw) {
        if (raw == null || raw.trim().isEmpty()) return "未知错误";
        String value = raw.trim();
        String lower = value.toLowerCase(Locale.ROOT);
        if (lower.contains("unable to resolve host") || lower.contains("no address associated with hostname")) {
            return "网络连接失败，请检查网络后重试";
        }
        if (lower.contains("failed to connect") || lower.contains("connection refused") || lower.contains("connect timed out")) {
            return "连接服务失败，请稍后重试";
        }
        if (lower.contains("socket closed") || lower.contains("connection reset")) {
            return "网络连接已中断，请重试";
        }
        if (lower.equals("http 502") || lower.equals("http 503") || lower.equals("http 504")) {
            return "服务暂不可用，请稍后重试";
        }
        if (value.startsWith("{")) {
            try {
                JSONObject payload = new JSONObject(value);
                String[] keys = {"error", "message", "detail"};
                for (String key : keys) {
                    String message = payload.optString(key, "").trim();
                    if (!message.isEmpty()) return message;
                }
            } catch (Exception ignored) {
                // Fall through to the original response when it is not valid JSON.
            }
        }
        return value;
    }

    private void showTransientStatus(final String message) {
        showTransientStatus(message, null);
    }

    private void showTransientStatus(final String message, final Runnable action) {
        showTransientStatus(message, action, null, "");
    }

    private void showTransientStatus(final String message, final Runnable action, final JSONObject owner, final String ownerName) {
        runOnUiThread(() -> {
            clearTransientStatus(false);
            mainHandler.removeCallbacks(clearTransientStatusRunnable);
            transientStatusVisible = true;
            transientStatusAction = action;
            View hud = transientStatusHud(message, action != null, owner, ownerName);
            transientStatusView = hud;
            hud.setClickable(true);
            hud.setOnClickListener(action == null ? v -> clearTransientStatus(true) : v -> {
                Runnable callback = transientStatusAction;
                clearTransientStatus(true);
                if (callback != null) callback.run();
            });
            FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.TOP
            );
            params.setMargins(dp(18), dp(42), dp(18), 0);
            addContentView(hud, params);
            mainHandler.postDelayed(clearTransientStatusRunnable, TRANSIENT_STATUS_MS);
        });
    }

    private View transientStatusHud(String message, boolean actionable, JSONObject owner, String ownerName) {
        LinearLayout hud = horizontal();
        hud.setGravity(Gravity.CENTER_VERTICAL);
        hud.setPadding(dp(14), dp(12), dp(14), dp(12));
        hud.setBackground(round(Color.argb(248, 255, 255, 255), dp(20), Color.rgb(205, 244, 244), dp(2)));
        hud.setElevation(dp(10));
        if (owner != null) {
            ImageView avatar = capsuleImage();
            avatar.setContentDescription((ownerName == null || ownerName.isEmpty() ? "相册创建者" : ownerName) + "的头像");
            loadImageInto(owner.optString("avatarUrl", ""), avatar);
            LinearLayout.LayoutParams avatarParams = new LinearLayout.LayoutParams(dp(46), dp(46));
            avatarParams.setMargins(0, 0, dp(12), 0);
            hud.addView(avatar, avatarParams);
        }
        LinearLayout texts = vertical();
        String title = actionable ? "需要授权" : "提示";
        texts.addView(text(title, 17, PRIMARY, true), matchWrap());
        if (owner != null) {
            texts.addView(text("创建者：" + (ownerName == null || ownerName.isEmpty() ? "相册创建者" : ownerName), 13, TEAL, true), matchWrap());
        }
        TextView body = text(message == null ? "" : message, 13, SECONDARY, true);
        body.setMaxLines(3);
        texts.addView(body, matchWrap());
        hud.addView(texts, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        return hud;
    }

    private boolean isTouchInsideStatus(MotionEvent event) {
        if (transientStatusView == null) return false;
        android.graphics.Rect bounds = new android.graphics.Rect();
        if (!transientStatusView.getGlobalVisibleRect(bounds)) return false;
        return bounds.contains((int) event.getRawX(), (int) event.getRawY());
    }

    private void clearTransientStatus(boolean fromInteraction) {
        if (!transientStatusVisible) return;
        mainHandler.removeCallbacks(clearTransientStatusRunnable);
        transientStatusVisible = false;
        transientStatusAction = null;
        if (transientStatusView != null) {
            ViewGroup parent = (ViewGroup) transientStatusView.getParent();
            if (parent != null) parent.removeView(transientStatusView);
            transientStatusView = null;
        }
    }

    private void showManagedAlbumPage(String title, View content) {
        if (managementDialog != null && managementDialog.isShowing()) managementDialog.dismiss();
        Dialog dialog = showManagementPage(title, content, "", null);
        managementDialog = dialog;
        activeManagementPageTitle = title == null ? "" : title;
        dialog.setOnDismissListener(d -> {
            if (managementDialog == dialog) {
                managementDialog = null;
                activeManagementPageTitle = "";
            }
        });
    }

    private boolean isManagedPageOpen(String title) {
        return managementDialog != null
                && managementDialog.isShowing()
                && activeManagementPageTitle.equals(title == null ? "" : title);
    }

    private View managementStateContent(String message, boolean loading, Runnable retry) {
        LinearLayout state = vertical();
        state.setGravity(Gravity.CENTER);
        state.setPadding(dp(24), dp(80), dp(24), dp(80));
        if (loading) {
            ProgressBar progress = new ProgressBar(this);
            state.addView(progress, new LinearLayout.LayoutParams(dp(48), dp(48)));
            spacer(state, dp(18));
        }
        TextView label = text(message, 17, loading ? SECONDARY : PRIMARY, !loading);
        label.setGravity(Gravity.CENTER);
        state.addView(label, matchWrap());
        if (retry != null) {
            spacer(state, dp(22));
            Button retryButton = primaryButton("重试");
            retryButton.setOnClickListener(v -> retry.run());
            LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(dp(180), dp(56));
            retryParams.gravity = Gravity.CENTER_HORIZONTAL;
            state.addView(retryButton, retryParams);
        }
        return state;
    }

    private Dialog showManagementPage(String title, View content, String actionLabel, Runnable action) {
        LinearLayout page = vertical();
        page.setPadding(dp(18), dp(18), dp(18), dp(12));
        page.setBackground(softBackground());

        LinearLayout header = horizontal();
        header.setGravity(Gravity.CENTER_VERTICAL);
        Button close = ghostButton("关闭");
        close.setTextSize(16);
        header.addView(close, new LinearLayout.LayoutParams(dp(92), dp(52)));
        TextView heading = text(title, 23, PRIMARY, true);
        heading.setGravity(Gravity.CENTER);
        header.addView(heading, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        if (action != null && actionLabel != null && !actionLabel.isEmpty()) {
            Button command = ghostButton(actionLabel);
            command.setTextSize(15);
            header.addView(command, new LinearLayout.LayoutParams(dp(104), dp(52)));
            command.setTag(action);
        } else {
            header.addView(new View(this), new LinearLayout.LayoutParams(dp(92), dp(52)));
        }
        page.addView(header, matchWrap());
        spacer(page, dp(14));

        LinearLayout contentFrame = vertical();
        contentFrame.setPadding(dp(4), 0, dp(4), 0);
        contentFrame.setBackground(round(Color.argb(225, 255, 255, 255), dp(24), Color.rgb(218, 246, 241), dp(1)));
        contentFrame.addView(content, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        page.addView(contentFrame, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        Dialog dialog = new Dialog(this, android.R.style.Theme_Material_Light_NoActionBar);
        dialog.setContentView(page);
        close.setOnClickListener(v -> dialog.dismiss());
        View command = header.getChildAt(2);
        if (command instanceof Button && command.getTag() instanceof Runnable) {
            command.setOnClickListener(v -> {
                ((Runnable) command.getTag()).run();
                dialog.dismiss();
            });
        }
        dialog.show();
        Window window = dialog.getWindow();
        if (window != null) {
            window.clearFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
            window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            window.setStatusBarColor(Color.rgb(249, 251, 246));
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                window.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
            }
            window.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        }
        return dialog;
    }

    private void addActionButton(LinearLayout row, String label, int iconRes, final Runnable action) {
        // 仿 iOS：图标在上、文字在下的轻量卡片按钮（square.and.arrow.up / person.2 等）。
        LinearLayout button = vertical();
        button.setGravity(Gravity.CENTER);
        button.setBackground(round(Color.argb(220, 255, 255, 255), dp(18), Color.argb(46, 0, 128, 112), dp(1)));
        button.setOnClickListener(v -> action.run());
        ImageView icon = new ImageView(this);
        icon.setImageResource(iconRes);
        LinearLayout.LayoutParams iconParams = new LinearLayout.LayoutParams(dp(24), dp(24));
        iconParams.setMargins(0, 0, 0, dp(6));
        button.addView(icon, iconParams);
        TextView caption = text(label, 13, TEAL, true);
        caption.setGravity(Gravity.CENTER);
        button.addView(caption, matchWrap());
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(78), 1);
        params.setMargins(dp(4), dp(6), dp(4), dp(6));
        row.addView(button, params);
    }

    private void addReviewButtons(LinearLayout row, Runnable approve, Runnable reject) {
        LinearLayout actions = horizontal();
        Button yes = primaryButton("批准");
        yes.setTextSize(16);
        yes.setOnClickListener(v -> approve.run());
        Button no = ghostButton("拒绝");
        no.setTextColor(Color.rgb(230, 74, 83));
        no.setOnClickListener(v -> reject.run());
        actions.addView(yes, new LinearLayout.LayoutParams(0, dp(46), 1));
        actions.addView(no, new LinearLayout.LayoutParams(0, dp(46), 1));
        row.addView(actions, matchWrap());
    }

    private Map<String, Switch> permissionSwitches(LinearLayout parent, JSONObject permissions, boolean editable) {
        Map<String, Switch> switches = new HashMap<>();
        addPermissionSwitch(parent, switches, "upload", "允许上传", permissions, editable);
        addPermissionSwitch(parent, switches, "delete", "允许删除", permissions, editable);
        addPermissionSwitch(parent, switches, "download", "允许下载", permissions, editable);
        addPermissionSwitch(parent, switches, "share", "允许分享", permissions, editable);
        return switches;
    }

    private void addPermissionSwitch(LinearLayout parent, Map<String, Switch> switches, String key, String label, JSONObject permissions, boolean editable) {
        Switch control = new Switch(this);
        control.setText(label);
        control.setTextSize(18);
        control.setTextColor(PRIMARY);
        control.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        control.setPadding(0, dp(6), 0, dp(6));
        control.setChecked(permissionValue(permissions, key));
        control.setEnabled(editable);
        switches.put(key, control);
        parent.addView(control, matchWrap());
    }

    private JSONObject permissionsFromSwitches(Map<String, Switch> switches) {
        JSONObject permissions = new JSONObject();
        try {
            permissions.put("upload", switches.containsKey("upload") && switches.get("upload").isChecked());
            permissions.put("delete", switches.containsKey("delete") && switches.get("delete").isChecked());
            permissions.put("download", switches.containsKey("download") && switches.get("download").isChecked());
            permissions.put("share", switches.containsKey("share") && switches.get("share").isChecked());
        } catch (Exception ignored) {
        }
        return permissions;
    }

    private JSONObject defaultPermissions() {
        JSONObject permissions = new JSONObject();
        try {
            permissions.put("upload", true);
            permissions.put("delete", true);
            permissions.put("download", true);
            permissions.put("share", true);
        } catch (Exception ignored) {
        }
        return permissions;
    }

    private JSONObject permissionsObject(JSONObject source, String key) {
        JSONObject permissions = source == null ? null : source.optJSONObject(key);
        JSONObject normalized = defaultPermissions();
        if (permissions == null) return normalized;
        try {
            normalized.put("upload", permissionValue(permissions, "upload"));
            normalized.put("delete", permissionValue(permissions, "delete"));
            normalized.put("download", permissionValue(permissions, "download"));
            normalized.put("share", permissionValue(permissions, "share"));
        } catch (Exception ignored) {
        }
        return normalized;
    }

    private boolean permissionAllowed(JSONObject album, String key) {
        if (canEditMembers(album)) return true;
        return permissionValue(permissionsObject(album, "currentUserPermissions"), key);
    }

    private boolean canDeletePhoto(JSONObject album, JSONObject photo) {
        if (permissionAllowed(album, "delete")) return true;
        String currentUserId = currentUser == null ? "" : currentUser.optString("id", "");
        if (!currentUserId.isEmpty() && currentUserId.equals(photo.optString("uploaderUserId", ""))) return true;
        String nickname = currentUser == null ? "" : currentUser.optString("nickname", "").trim();
        return !nickname.isEmpty() && nickname.equals(photo.optString("uploader", "").trim());
    }

    private void syncDefaultUploader() {
        if (currentUser == null) return;
        String nickname = currentUser.optString("nickname", "").trim();
        if (!nickname.isEmpty()) pendingUploader = nickname;
    }

    private boolean canDeletePhotos(JSONObject album, JSONArray photos) {
        if (photos == null || photos.length() == 0) return false;
        for (int i = 0; i < photos.length(); i++) {
            JSONObject photo = photos.optJSONObject(i);
            if (photo == null || !canDeletePhoto(album, photo)) return false;
        }
        return true;
    }

    private boolean permissionValue(JSONObject permissions, String key) {
        return permissions == null || !permissions.has(key) || permissions.optBoolean(key, true);
    }

    private String permissionSummary(JSONObject permissions) {
        JSONObject normalized = permissions == null ? defaultPermissions() : permissions;
        List<String> values = new ArrayList<>();
        if (permissionValue(normalized, "upload")) values.add("上传");
        if (permissionValue(normalized, "delete")) values.add("删除");
        if (permissionValue(normalized, "download")) values.add("下载");
        if (permissionValue(normalized, "share")) values.add("分享");
        if (values.isEmpty()) return "无";
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < values.size(); i++) {
            if (i > 0) builder.append("、");
            builder.append(values.get(i));
        }
        return builder.toString();
    }

    private boolean canEditMembers(JSONObject album) {
        return album != null && (album.optBoolean("isOwner", false) || "owner".equals(album.optString("currentUserRole")));
    }

    private boolean isAdmin(JSONObject album) {
        if (album == null) return false;
        String role = album.optString("currentUserRole");
        return album.optBoolean("canAdmin", false) || "owner".equals(role) || "admin".equals(role);
    }

    private String ownerDisplayName(JSONObject album) {
        JSONObject owner = album == null ? null : album.optJSONObject("ownerUser");
        String nickname = owner == null ? "" : owner.optString("nickname", "").trim();
        if (!nickname.isEmpty()) return nickname;
        String username = owner == null ? album.optString("ownerUsername", "") : owner.optString("username", "");
        if (username != null && !username.trim().isEmpty()) return "@" + username.trim();
        String userId = album == null ? "" : album.optString("ownerUserId", "");
        return userId.isEmpty() ? "相册创建者" : userId;
    }

    private String displayUserName(JSONObject user) {
        if (user == null) return "协作用户";
        String nickname = user.optString("nickname", "").trim();
        if (!nickname.isEmpty()) return nickname;
        String username = user.optString("username", "").trim();
        if (!username.isEmpty()) return "@" + username;
        return user.optString("id", "协作用户");
    }

    private String userIdentity(JSONObject user) {
        return "申请人 · " + userNameOnly(user);
    }

    // 仅返回用户显示名（昵称 @账号），不带角色前缀，供"处理人/申请人"等不同角色复用。
    private String userNameOnly(JSONObject user) {
        if (user == null) return "协作用户";
        String nickname = user.optString("nickname", "").trim();
        String username = user.optString("username", "").trim();
        if (!nickname.isEmpty() && !username.isEmpty()) return nickname + " @" + username;
        if (!nickname.isEmpty()) return nickname;
        if (!username.isEmpty()) return "@" + username;
        return user.optString("id", "协作用户");
    }

    private LinearLayout approvalTitleRow(String title, long timestamp) {
        LinearLayout row = horizontal();
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.addView(text(title, 18, PRIMARY, true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        String formatted = formatTimestamp(timestamp);
        if (!formatted.isEmpty()) row.addView(text(formatted, 12, SECONDARY, true), trailingWrap());
        return row;
    }

    private long requestTimestamp(JSONObject request) {
        if (request == null) return 0;
        long reviewedAt = request.optLong("reviewedAt", 0);
        return reviewedAt > 0 ? reviewedAt : request.optLong("createdAt", 0);
    }

    private static final class ApprovalRecord {
        final String kind;
        final JSONObject request;

        ApprovalRecord(String kind, JSONObject request) {
            this.kind = kind;
            this.request = request;
        }
    }

    private String formatTimestamp(long timestamp) {
        if (timestamp <= 0) return "";
        long millis = timestamp < 10_000_000_000L ? timestamp * 1000L : timestamp;
        return new SimpleDateFormat("MM/dd HH:mm", Locale.CHINA).format(new Date(millis));
    }

    private String roleText(String role) {
        if ("owner".equals(role)) return "创建人";
        if ("admin".equals(role)) return "管理员";
        return "成员";
    }

    private String statusLabel(String status) {
        if ("pending".equals(status)) return "待审批";
        if ("approved".equals(status)) return "已批准";
        if ("rejected".equals(status)) return "已拒绝";
        if ("cancelled".equals(status)) return "已撤销";
        return status == null || status.isEmpty() ? "已处理" : status;
    }

    private JSONObject latestRequest(JSONArray requests) {
        JSONObject latest = null;
        int best = -1;
        for (int i = 0; i < requests.length(); i++) {
            JSONObject request = requests.optJSONObject(i);
            if (request == null) continue;
            if ("pending".equals(request.optString("status"))) return request;
            int timestamp = Math.max(request.optInt("reviewedAt", 0), request.optInt("createdAt", 0));
            if (timestamp > best) {
                best = timestamp;
                latest = request;
            }
        }
        return latest;
    }

    private void updateAlbumFromResponse(JSONObject response) {
        JSONObject updated = response == null ? null : response.optJSONObject("album");
        if (updated == null) return;
        selectedAlbumId = updated.optString("id", selectedAlbumId);
        currentAlbum = updated;
        JSONArray next = new JSONArray();
        boolean replaced = false;
        for (int i = 0; i < albums.length(); i++) {
            JSONObject album = albums.optJSONObject(i);
            if (album != null && album.optString("id").equals(updated.optString("id"))) {
                next.put(updated);
                replaced = true;
            } else if (album != null) {
                next.put(album);
            }
        }
        if (!replaced) next.put(updated);
        albums = next;
        cacheAlbums();
        runOnUiThread(() -> {
            JSONObject folder = findFolderById(updated, activeFolderId);
            if ("folder".equals(currentScreen) && folder != null) showFolderDialog(updated, folder);
            else showAlbumDetail(updated);
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
        layout.setElevation(dp(2));
        return layout;
    }

    private ImageView capsuleImage() {
        ImageView image = new ImageView(this);
        image.setScaleType(ImageView.ScaleType.CENTER_CROP);
        image.setPadding(dp(2), dp(2), dp(2), dp(2));
        image.setBackground(round(Color.WHITE, dp(32), Color.WHITE, dp(3)));
        image.setClipToOutline(true);
        return image;
    }

    private void addCenteredBrand(LinearLayout parent, int logoSize, int titleSp, int subtitleSp) {
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.picme_logo);
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

    // 全局可见的轻提示（子页面没有 statusText，用 Toast 确保保存/下载等操作有反馈）。
    private void toast(final String message) {
        runOnUiThread(() -> Toast.makeText(this, message, Toast.LENGTH_SHORT).show());
    }

    // 水平行里靠右的次要文字（如时间）：用 WRAP_CONTENT 宽度，避免占满整行把带 weight 的标题挤成 0 宽。
    private LinearLayout.LayoutParams trailingWrap() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(dp(8), 0, 0, 0);
        return params;
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
