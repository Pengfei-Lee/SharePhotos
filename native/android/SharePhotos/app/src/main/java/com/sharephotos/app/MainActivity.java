package com.sharephotos.app;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public class MainActivity extends Activity {
    private static final int REQUEST_PICK_FILES = 1001;
    private static final String PRODUCTION_BASE_URL = "https://picme.me";
    private static final String PREFS = "picme-auth";

    private EditText usernameInput;
    private EditText passwordInput;
    private EditText albumIdInput;
    private EditText uploaderInput;
    private EditText inviteCodeInput;
    private TextView albumsText;
    private TextView statusText;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 56, 40, 40);
        root.setGravity(Gravity.TOP);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("PicMe");
        title.setTextSize(32);
        root.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("朋友拍的你，一键收齐");
        subtitle.setTextSize(14);
        root.addView(subtitle);

        usernameInput = input("登录账号", "");
        passwordInput = input("密码", "");
        passwordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        albumIdInput = input("相册 ID", "");
        uploaderInput = input("上传者，不填则使用账号", "");
        inviteCodeInput = input("相册码或分享链接", "");

        root.addView(usernameInput);
        root.addView(passwordInput);

        Button loginButton = button("登录 / 刷新登录态", new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                login();
            }
        });
        root.addView(loginButton);

        Button loadAlbumsButton = button("读取我的相册", new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                loadAlbums();
            }
        });
        root.addView(loadAlbumsButton);

        albumsText = new TextView(this);
        albumsText.setText("登录后读取已加入的相册。");
        albumsText.setTextSize(14);
        root.addView(albumsText);

        root.addView(albumIdInput);
        root.addView(uploaderInput);

        Button pickButton = button("选择照片 / 视频并直传 OSS", new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                pickFiles();
            }
        });
        root.addView(pickButton);

        root.addView(inviteCodeInput);
        Button joinButton = button("申请加入相册", new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestJoinFromInput();
            }
        });
        root.addView(joinButton);

        statusText = new TextView(this);
        statusText.setText("准备好收朋友视角了");
        statusText.setTextSize(15);
        root.addView(statusText);

        setContentView(scroll);
        handleJoinIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleJoinIntent(intent);
    }

    private EditText input(String hint, String text) {
        EditText editText = new EditText(this);
        editText.setHint(hint);
        editText.setText(text);
        editText.setSingleLine(true);
        return editText;
    }

    private Button button(String text, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setOnClickListener(listener);
        return button;
    }

    private void handleJoinIntent(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data == null) return;
        String code = inviteCodeFrom(data.toString());
        if (!code.isEmpty()) {
            inviteCodeInput.setText(code);
            statusText.setText("已识别相册码：" + code + "，登录后可申请加入。");
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
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    JSONObject body = new JSONObject();
                    body.put("username", username);
                    body.put("password", password);
                    JSONObject response = requestJson("POST", "/api/auth/login", body, false, false);
                    saveTokens(response);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            statusText.setText("登录成功");
                            loadAlbums();
                        }
                    });
                } catch (final Exception error) {
                    showError("登录失败", error);
                }
            }
        }).start();
    }

    private void loadAlbums() {
        statusText.setText("正在读取相册...");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    final JSONObject response = requestJson("GET", "/api/albums", null, true, true);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            albumsText.setText(formatAlbums(response));
                            statusText.setText("相册已更新");
                        }
                    });
                } catch (final Exception error) {
                    showError("读取相册失败", error);
                }
            }
        }).start();
    }

    private void requestJoinFromInput() {
        final String code = inviteCodeFrom(inviteCodeInput.getText().toString());
        if (code.isEmpty()) {
            statusText.setText("请填写相册码或分享链接");
            return;
        }
        statusText.setText("正在提交加入申请...");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    requestJson("GET", "/api/invites/" + code, null, true, true);
                    requestJson("POST", "/api/invites/" + code + "/request", new JSONObject(), true, true);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            statusText.setText("已提交加入申请，等待相册管理员审批");
                        }
                    });
                } catch (final Exception error) {
                    showError("申请加入失败", error);
                }
            }
        }).start();
    }

    private void pickFiles() {
        if (albumIdInput.getText().toString().trim().isEmpty()) {
            statusText.setText("请先填写相册 ID");
            return;
        }
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"image/*", "video/*", "application/octet-stream"});
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(intent, REQUEST_PICK_FILES);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_PICK_FILES || resultCode != RESULT_OK || data == null) {
            return;
        }

        final List<Uri> uris = new ArrayList<>();
        if (data.getClipData() != null) {
            for (int i = 0; i < data.getClipData().getItemCount(); i++) {
                uris.add(data.getClipData().getItemAt(i).getUri());
            }
        } else if (data.getData() != null) {
            uris.add(data.getData());
        }

        statusText.setText("正在准备直传 " + uris.size() + " 个文件...");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    directUpload(uris);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            statusText.setText("上传完成，后台开始整理");
                            loadAlbums();
                        }
                    });
                } catch (final Exception error) {
                    showError("上传失败", error);
                }
            }
        }).start();
    }

    private void directUpload(List<Uri> uris) throws Exception {
        String albumId = albumIdInput.getText().toString().trim();
        String uploader = uploaderInput.getText().toString().trim();
        if (uploader.isEmpty()) uploader = usernameInput.getText().toString().trim();
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
        JSONObject init = requestJson("POST", "/api/albums/" + albumId + "/uploads/init", initBody, true, true);
        JSONArray uploads = init.optJSONArray("uploads");
        if (uploads == null || uploads.length() == 0) {
            throw new IllegalStateException("没有可上传的文件");
        }

        for (int i = 0; i < uploads.length(); i++) {
            JSONObject upload = uploads.getJSONObject(i);
            putSignedResource(upload.getJSONObject("image"), uriById);
            if (!upload.isNull("video")) {
                putSignedResource(upload.getJSONObject("video"), uriById);
            }
        }

        JSONObject completeBody = new JSONObject();
        completeBody.put("uploader", uploader);
        completeBody.put("uploads", uploads);
        requestJson("POST", "/api/albums/" + albumId + "/uploads/complete", completeBody, true, true);
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
        if (!mimeType.isEmpty()) {
            connection.setRequestProperty("Content-Type", mimeType);
        }

        OutputStream output = connection.getOutputStream();
        InputStream input = getContentResolver().openInputStream(uri);
        if (input == null) throw new IllegalStateException("无法读取 " + resource.optString("originalName"));
        byte[] buffer = new byte[1024 * 64];
        int read;
        while ((read = input.read(buffer)) != -1) {
            output.write(buffer, 0, read);
        }
        input.close();
        output.flush();
        output.close();

        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) {
            throw new IllegalStateException(readAll(connection.getErrorStream(), "OSS 上传失败：" + code));
        }
    }

    private JSONObject requestJson(String method, String path, JSONObject body, boolean auth, boolean retryRefresh) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(PRODUCTION_BASE_URL + path).openConnection();
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept", "application/json");
        if (auth) {
            String token = prefs.getString("accessToken", "");
            if (!token.isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + token);
            }
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
        if (code == 401 && auth && retryRefresh && refreshTokens()) {
            return requestJson(method, path, body, true, false);
        }
        if (code < 200 || code >= 300) {
            throw new IllegalStateException(text.isEmpty() ? ("请求失败：" + code) : text);
        }
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

    private String formatAlbums(JSONObject response) {
        JSONArray albums = response.optJSONArray("albums");
        if (albums == null || albums.length() == 0) {
            return "暂无相册。";
        }
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < albums.length(); i++) {
            JSONObject album = albums.optJSONObject(i);
            if (album == null) continue;
            builder.append(album.optString("name", "未命名相册"))
                    .append("  ID: ")
                    .append(album.optString("id"))
                    .append("\n");
            if (i == 0 && albumIdInput.getText().toString().trim().isEmpty()) {
                albumIdInput.setText(album.optString("id"));
            }
        }
        return builder.toString().trim();
    }

    private String inviteCodeFrom(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) return "";
        int index = value.indexOf("/join/");
        if (index >= 0) {
            value = value.substring(index + 6);
        }
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
        while ((read = input.read(buffer)) != -1) {
            output.write(buffer, 0, read);
        }
        return output.toString("UTF-8");
    }

    private void showError(final String prefix, final Exception error) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                statusText.setText(prefix + "：" + (error.getMessage() == null ? "未知错误" : error.getMessage()));
            }
        });
    }
}
