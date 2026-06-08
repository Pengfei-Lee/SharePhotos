package com.sharephotos.app;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Arrays;
import java.util.Comparator;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 图片磁盘缓存，对齐 iOS 端 PhotoDiskCache：
 * - 用「去掉 query/fragment 的 URL」做稳定标识，OSS 签名 URL 换 token 也能命中。
 * - 文件名用 FNV-1a 64 位哈希，和 iOS 同一套 key 规则。
 * - 容量上限 + 按最后访问时间 LRU 清理。
 * - 同一 key 并发只下载一次（in-flight 去重）。
 */
final class PhotoDiskCache {
    private final File dir;
    private final long maxBytes;
    private final ConcurrentHashMap<String, Object> locks = new ConcurrentHashMap<>();
    private volatile long lastTrim = 0L;

    PhotoDiskCache(Context context, long maxBytes) {
        File base = context.getCacheDir();
        this.dir = new File(base, "PicMePhotoCache");
        this.maxBytes = maxBytes;
        if (!dir.exists()) dir.mkdirs();
    }

    /** 去掉 query/fragment，得到稳定标识。 */
    private static String stableIdentifier(String url) {
        if (url == null) return "";
        int q = url.indexOf('?');
        if (q >= 0) url = url.substring(0, q);
        int h = url.indexOf('#');
        if (h >= 0) url = url.substring(0, h);
        return url;
    }

    private static String keyFor(String identifier) {
        long hash = 0xcbf29ce484222325L; // FNV-1a 64
        for (int i = 0; i < identifier.length(); i++) {
            hash ^= identifier.charAt(i);
            hash *= 0x100000001b3L;
        }
        return Long.toHexString(hash);
    }

    /** 自定义下载器：把资源写入给定的临时文件。用于 Live 视频等需要先解析签名 URL 的场景。 */
    interface Downloader {
        void writeTo(File out) throws Exception;
    }

    private File fileForId(String identifier) {
        return new File(dir, keyFor(identifier) + ".img");
    }

    /** 仅查磁盘命中(按 URL)，不发起下载。 */
    File peek(String absoluteUrl) {
        return peekId(stableIdentifier(absoluteUrl));
    }

    /** 仅查磁盘命中(按自定义标识)，不发起下载；命中则刷新访问时间。 */
    File peekId(String identifier) {
        File f = fileForId(identifier);
        if (f.exists() && f.length() > 0) {
            f.setLastModified(System.currentTimeMillis());
            return f;
        }
        return null;
    }

    /** 按 URL 命中直接返回；否则从该 URL 下载到磁盘。 */
    File fetch(String absoluteUrl) throws Exception {
        return fetch(stableIdentifier(absoluteUrl), out -> downloadUrl(absoluteUrl, out));
    }

    /** 按自定义标识命中直接返回；否则用 downloader 下载到磁盘。同一标识并发只下载一次，统一受容量/LRU 管理。 */
    File fetch(String identifier, Downloader downloader) throws Exception {
        File dest = fileForId(identifier);
        if (dest.exists() && dest.length() > 0) {
            dest.setLastModified(System.currentTimeMillis());
            return dest;
        }
        Object lock = locks.computeIfAbsent(identifier, k -> new Object());
        synchronized (lock) {
            try {
                if (dest.exists() && dest.length() > 0) {
                    dest.setLastModified(System.currentTimeMillis());
                    return dest;
                }
                File tmp = new File(dir, dest.getName() + "." + Thread.currentThread().getId() + ".tmp");
                try {
                    downloader.writeTo(tmp);
                    if (tmp.length() <= 0 || !tmp.renameTo(dest)) {
                        throw new IllegalStateException("cache write failed");
                    }
                } finally {
                    if (tmp.exists()) tmp.delete();
                }
                dest.setLastModified(System.currentTimeMillis());
            } finally {
                locks.remove(identifier, lock);
            }
        }
        trimIfNeeded();
        return dest;
    }

    /** 默认的 URL 下载实现。 */
    private static void downloadUrl(String absoluteUrl, File out) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(absoluteUrl).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestMethod("GET");
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) {
            connection.disconnect();
            throw new IllegalStateException("HTTP " + code);
        }
        InputStream input = connection.getInputStream();
        FileOutputStream output = new FileOutputStream(out);
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

    /** 容量超限时按最后访问时间删除最旧文件；限频 30s，避免频繁全目录扫描。 */
    private void trimIfNeeded() {
        long now = System.currentTimeMillis();
        if (now - lastTrim < 30_000L) return;
        lastTrim = now;
        File[] files = dir.listFiles();
        if (files == null) return;
        long total = 0L;
        for (File f : files) total += f.length();
        if (total <= maxBytes) return;
        Arrays.sort(files, Comparator.comparingLong(File::lastModified));
        for (File f : files) {
            if (total <= maxBytes) break;
            long size = f.length();
            if (f.delete()) total -= size;
        }
    }

    void clear() {
        File[] files = dir.listFiles();
        if (files == null) return;
        for (File f : files) f.delete();
    }
}
