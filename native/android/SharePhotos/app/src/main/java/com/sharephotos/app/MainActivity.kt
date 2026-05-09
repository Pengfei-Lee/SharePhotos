package com.sharephotos.app

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val api = SharePhotosApi()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    SharePhotosScreen(activity = this@MainActivity, api = api)
                }
            }
        }
    }
}

@Composable
private fun SharePhotosScreen(activity: ComponentActivity, api: SharePhotosApi) {
    val scope = rememberCoroutineScope()
    var albumId by remember { mutableStateOf("") }
    var uploader by remember { mutableStateOf("访客") }
    var status by remember { mutableStateOf("Android 端会尽量保留系统返回的原始文件") }

    val picker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments()
    ) { uris: List<Uri> ->
        if (albumId.isBlank()) {
            status = "请先填写相册 ID"
            return@rememberLauncherForActivityResult
        }
        scope.launch {
            runCatching {
                val files = uris.map { uri ->
                    val name = activity.contentResolver.displayName(uri)
                    val type = activity.contentResolver.getType(uri) ?: contentTypeFromName(name)
                    PickedUploadFile(uri = uri, filename = name, contentType = type)
                }
                api.upload(albumId = albumId, uploader = uploader, files = files, contentResolver = activity.contentResolver)
            }.onSuccess {
                status = "上传完成，后台开始整理"
            }.onFailure {
                status = it.localizedMessage ?: "上传失败"
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        verticalArrangement = Arrangement.Top
    ) {
        Text("SharePhotos", style = MaterialTheme.typography.headlineLarge)
        Text("朋友拍的你，一键收齐", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(24.dp))
        OutlinedTextField(
            value = albumId,
            onValueChange = { albumId = it },
            label = { Text("相册 ID") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = uploader,
            onValueChange = { uploader = it },
            label = { Text("上传者，不填则访客") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(20.dp))
        Button(
            onClick = {
                picker.launch(arrayOf("image/*", "video/*", "application/octet-stream"))
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("选择照片 / 视频 / Motion Photo")
        }
        Spacer(Modifier.height(16.dp))
        Text(status, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private fun contentTypeFromName(filename: String): String {
    return when (filename.substringAfterLast('.', "").lowercase()) {
        "heic", "heif" -> "image/heic"
        "jpg", "jpeg" -> "image/jpeg"
        "png" -> "image/png"
        "mov" -> "video/quicktime"
        "mp4" -> "video/mp4"
        else -> "application/octet-stream"
    }
}
