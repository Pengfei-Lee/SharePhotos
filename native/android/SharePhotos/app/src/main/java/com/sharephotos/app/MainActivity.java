package com.sharephotos.app;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

public class MainActivity extends Activity {
    private static final int REQUEST_PICK_FILES = 1001;

    private EditText baseUrlInput;
    private EditText albumIdInput;
    private EditText uploaderInput;
    private TextView statusText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 60, 40, 40);
        root.setGravity(Gravity.TOP);

        TextView title = new TextView(this);
        title.setText("SharePhotos");
        title.setTextSize(30);
        title.setGravity(Gravity.START);
        root.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("朋友拍的你，一键收齐");
        subtitle.setTextSize(16);
        root.addView(subtitle);

        baseUrlInput = input("服务地址，例如 http://192.168.0.175:8000", "http://localhost:8000");
        albumIdInput = input("相册 ID", "");
        uploaderInput = input("上传者，不填则访客", "访客");
        root.addView(baseUrlInput);
        root.addView(albumIdInput);
        root.addView(uploaderInput);

        Button pickButton = new Button(this);
        pickButton.setText("选择照片 / 视频 / Motion Photo");
        pickButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                pickFiles();
            }
        });
        root.addView(pickButton);

        statusText = new TextView(this);
        statusText.setText("Android 会上传系统选择器返回的原始文件；如拿到同名图片+视频，后端会识别为 Live Photo。");
        statusText.setTextSize(15);
        root.addView(statusText);

        setContentView(root);
    }

    private EditText input(String hint, String text) {
        EditText editText = new EditText(this);
        editText.setHint(hint);
        editText.setText(text);
        editText.setSingleLine(true);
        return editText;
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

        statusText.setText("正在上传 " + uris.size() + " 个文件...");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    upload(uris);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            statusText.setText("上传完成，后台开始整理");
                        }
                    });
                } catch (final Exception error) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            statusText.setText("上传失败：" + error.getMessage());
                        }
                    });
                }
            }
        }).start();
    }

    private void upload(List<Uri> uris) throws Exception {
        String baseUrl = baseUrlInput.getText().toString().trim();
        String albumId = albumIdInput.getText().toString().trim();
        String uploader = uploaderInput.getText().toString().trim();
        if (uploader.isEmpty()) uploader = "访客";

        String boundary = "Boundary-" + UUID.randomUUID();
        URL url = new URL(baseUrl + "/api/albums/" + albumId + "/upload");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);

        OutputStream output = connection.getOutputStream();
        writeField(output, boundary, "uploader", uploader);
        for (Uri uri : uris) {
            writeFile(output, boundary, uri);
        }
        output.write(("--" + boundary + "--\r\n").getBytes("UTF-8"));
        output.flush();
        output.close();

        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) {
            throw new IllegalStateException(readAll(connection.getErrorStream()));
        }
    }

    private void writeField(OutputStream output, String boundary, String name, String value) throws Exception {
        output.write(("--" + boundary + "\r\n").getBytes("UTF-8"));
        output.write(("Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n").getBytes("UTF-8"));
        output.write((value + "\r\n").getBytes("UTF-8"));
    }

    private void writeFile(OutputStream output, String boundary, Uri uri) throws Exception {
        String filename = displayName(uri);
        String mimeType = getContentResolver().getType(uri);
        if (mimeType == null) mimeType = contentTypeFromName(filename);

        output.write(("--" + boundary + "\r\n").getBytes("UTF-8"));
        output.write(("Content-Disposition: form-data; name=\"photos\"; filename=\"" + filename + "\"\r\n").getBytes("UTF-8"));
        output.write(("Content-Type: " + mimeType + "\r\n\r\n").getBytes("UTF-8"));

        InputStream input = getContentResolver().openInputStream(uri);
        if (input == null) throw new IllegalStateException("无法读取 " + filename);
        byte[] buffer = new byte[8192];
        int read;
        while ((read = input.read(buffer)) != -1) {
            output.write(buffer, 0, read);
        }
        input.close();
        output.write("\r\n".getBytes("UTF-8"));
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

    private String contentTypeFromName(String filename) {
        String lower = filename.toLowerCase();
        if (lower.endsWith(".heic") || lower.endsWith(".heif")) return "image/heic";
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
        if (lower.endsWith(".png")) return "image/png";
        if (lower.endsWith(".mov")) return "video/quicktime";
        if (lower.endsWith(".mp4")) return "video/mp4";
        return "application/octet-stream";
    }

    private String readAll(InputStream input) throws Exception {
        if (input == null) return "";
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int read;
        while ((read = input.read(buffer)) != -1) {
            output.write(buffer, 0, read);
        }
        return output.toString("UTF-8");
    }
}
