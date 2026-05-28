package com.sharephotos.app

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

data class PickedUploadFile(
    val uri: Uri,
    val filename: String,
    val contentType: String
)

class SharePhotosApi(
    private val baseUrl: String = "https://picme.me",
    private val client: OkHttpClient = OkHttpClient()
) {
    suspend fun upload(
        albumId: String,
        uploader: String,
        files: List<PickedUploadFile>,
        contentResolver: ContentResolver
    ): String = withContext(Dispatchers.IO) {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("uploader", uploader.ifBlank { "访客" })

        files.forEach { file ->
            val bytes = contentResolver.openInputStream(file.uri)?.use { it.readBytes() }
                ?: error("无法读取 ${file.filename}")
            body.addFormDataPart(
                "photos",
                file.filename,
                bytes.toRequestBody(file.contentType.toMediaTypeOrNull())
            )
        }

        val request = Request.Builder()
            .url("$baseUrl/api/albums/$albumId/upload")
            .post(body.build())
            .build()

        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) error(text.ifBlank { "上传失败：${response.code}" })
            text
        }
    }

    suspend fun fetchAlbums(): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/albums").get().build()
        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) error(text.ifBlank { "读取相册失败：${response.code}" })
            text
        }
    }
}

fun ContentResolver.displayName(uri: Uri): String {
    query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
        val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (index >= 0 && cursor.moveToFirst()) {
            return cursor.getString(index)
        }
    }
    return uri.lastPathSegment?.substringAfterLast('/') ?: "upload-${System.currentTimeMillis()}"
}
