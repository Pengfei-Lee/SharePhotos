package com.sharephotos.app;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobService;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashSet;
import java.util.Set;

public class MessageNotificationJobService extends JobService {
    private static final String BASE_URL = "https://picme.me";
    private static final String PREFS = "picme-auth";
    private static final String NOTIFIED_IDS = "notifiedMessageIds";
    private static final String CHANNEL_ID = "picme_messages";
    private static final int PERIODIC_JOB_ID = 4101;
    private static final int IMMEDIATE_JOB_ID = 4102;

    public static void schedule(Context context) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        ComponentName service = new ComponentName(context, MessageNotificationJobService.class);
        JobInfo periodic = new JobInfo.Builder(PERIODIC_JOB_ID, service)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .build();
        JobInfo immediate = new JobInfo.Builder(IMMEDIATE_JOB_ID, service)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setMinimumLatency(1_000L)
                .setOverrideDeadline(8_000L)
                .build();
        scheduler.schedule(periodic);
        scheduler.schedule(immediate);
    }

    public static void cancel(Context context) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        scheduler.cancel(PERIODIC_JOB_ID);
        scheduler.cancel(IMMEDIATE_JOB_ID);
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            try {
                syncUnreadMessages();
            } catch (Exception ignored) {
            } finally {
                jobFinished(params, false);
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }

    private void syncUnreadMessages() throws Exception {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String accessToken = prefs.getString("accessToken", "");
        if (accessToken.isEmpty() && !refreshAccessToken(prefs)) {
            cancel(this);
            return;
        }
        accessToken = prefs.getString("accessToken", "");
        Response response = request("GET", "/api/messages?unread=true", null, accessToken);
        if (response.code == 401 && refreshAccessToken(prefs)) {
            response = request("GET", "/api/messages?unread=true", null, prefs.getString("accessToken", ""));
        }
        if (response.code < 200 || response.code >= 300 || response.body.isEmpty()) return;
        JSONArray messages = new JSONObject(response.body).optJSONArray("messages");
        if (messages == null) return;
        Set<String> notified = new HashSet<>(prefs.getStringSet(NOTIFIED_IDS, new HashSet<>()));
        Set<String> next = new HashSet<>(notified);
        int shown = 0;
        for (int i = 0; i < messages.length(); i++) {
            JSONObject message = messages.optJSONObject(i);
            if (message == null || message.optBoolean("isRead", false)) continue;
            String id = message.optString("id", "");
            if (id.isEmpty() || notified.contains(id)) continue;
            if (shown < 5) {
                showNotification(message);
                shown++;
            }
            next.add(id);
        }
        if (next.size() > 120) {
            next.clear();
            for (int i = 0; i < Math.min(messages.length(), 100); i++) {
                JSONObject message = messages.optJSONObject(i);
                if (message != null && !message.optString("id", "").isEmpty()) next.add(message.optString("id"));
            }
        }
        prefs.edit().putStringSet(NOTIFIED_IDS, next).apply();
    }

    private boolean refreshAccessToken(SharedPreferences prefs) {
        String refreshToken = prefs.getString("refreshToken", "");
        if (refreshToken.isEmpty()) return false;
        try {
            JSONObject body = new JSONObject();
            body.put("refreshToken", refreshToken);
            Response response = request("POST", "/api/auth/refresh", body, "");
            if (response.code < 200 || response.code >= 300) return false;
            JSONObject payload = new JSONObject(response.body);
            SharedPreferences.Editor editor = prefs.edit();
            if (payload.has("accessToken")) editor.putString("accessToken", payload.optString("accessToken"));
            if (payload.has("refreshToken")) editor.putString("refreshToken", payload.optString("refreshToken"));
            editor.apply();
            return !payload.optString("accessToken", "").isEmpty();
        } catch (Exception ignored) {
            return false;
        }
    }

    private void showNotification(JSONObject message) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(new NotificationChannel(
                    CHANNEL_ID,
                    "PicMe 消息提醒",
                    NotificationManager.IMPORTANCE_DEFAULT
            ));
        }
        String id = message.optString("id", "");
        Intent intent = new Intent(this, MainActivity.class)
                .putExtra("messageId", id)
                .putExtra("messageType", message.optString("type", ""))
                .putExtra("albumId", message.optString("albumId", ""))
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this,
                id.hashCode(),
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        android.app.Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new android.app.Notification.Builder(this, CHANNEL_ID)
                : new android.app.Notification.Builder(this);
        android.app.Notification notification = builder
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(message.optString("title", "PicMe 消息"))
                .setContentText(message.optString("body", "打开 PicMe 查看详情"))
                .setStyle(new android.app.Notification.BigTextStyle().bigText(message.optString("body", "打开 PicMe 查看详情")))
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .build();
        manager.notify(id.hashCode(), notification);
    }

    private Response request(String method, String path, JSONObject body, String accessToken) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(BASE_URL + path).openConnection();
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept", "application/json");
        if (accessToken != null && !accessToken.isEmpty()) {
            connection.setRequestProperty("Authorization", "Bearer " + accessToken);
        }
        if (body != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body.toString().getBytes("UTF-8"));
            }
        }
        int code = connection.getResponseCode();
        InputStream input = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
        return new Response(code, readAll(input));
    }

    private String readAll(InputStream input) throws Exception {
        if (input == null) return "";
        try (InputStream stream = input; java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = stream.read(buffer)) != -1) output.write(buffer, 0, read);
            return output.toString("UTF-8");
        }
    }

    private static final class Response {
        final int code;
        final String body;

        Response(int code, String body) {
            this.code = code;
            this.body = body == null ? "" : body;
        }
    }
}
