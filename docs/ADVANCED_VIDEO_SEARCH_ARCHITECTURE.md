# 🎬 Advanced Search from Video & Device Media Architecture (meta-llama/llama-3.3-70b-instruct)

### Python Backend Implementation

We'll implement the `/api/v1/search/by-media` endpoint in `viewer.py` using Python's standard library and SQLite for the database.

```python
# viewer.py
import sqlite3
import re
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# Connect to the SQLite database
conn = sqlite3.connect('catalog.db')
cursor = conn.cursor()

# Create the FTS5 table if it doesn't exist
cursor.execute('''
    CREATE VIRTUAL TABLE IF NOT EXISTS catalog USING fts5(
        title,
        duration,
        aspect_ratio,
        audio_stream_metadata
    );
''')

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/v1/search/by-media':
            query_params = parse_qs(parsed_path.query)
            title = query_params.get('title', [''])[0]
            duration = float(query_params.get('duration', ['0'])[0])
            aspect_ratio = query_params.get('aspect_ratio', [''])[0]
            audio_stream_metadata = query_params.get('audio_stream_metadata', [''])[0]

            # Sanitize the title
            sanitized_title = re.sub(r'[^a-zA-Z0-9\s]', '', title)

            # Query the database
            cursor.execute('''
                SELECT * FROM catalog
                WHERE title MATCH :sanitized_title
                AND duration BETWEEN :min_duration AND :max_duration
                AND aspect_ratio = :aspect_ratio
                AND audio_stream_metadata = :audio_stream_metadata
            ''', {
                'sanitized_title': sanitized_title,
                'min_duration': duration * 0.9,
                'max_duration': duration * 1.1,
                'aspect_ratio': aspect_ratio,
                'audio_stream_metadata': audio_stream_metadata
            })

            results = cursor.fetchall()
            if results:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'title': results[0][0],
                    'duration': results[0][1],
                    'aspect_ratio': results[0][2],
                    'audio_stream_metadata': results[0][3],
                    'streaming_url': 'https://example.com/streaming',
                    'download_url': 'https://example.com/download'
                }).encode())
            else:
                self.send_response(404)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': 'No matching title found'
                }).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Invalid endpoint'
            }).encode())

def run_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, RequestHandler)
    print('Server running on port 8000...')
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
```

### Kotlin Jetpack Compose Implementation

We'll implement the local video file picker and metadata extraction in `DeviceVideoSearchScreen.kt`.

```kotlin
// DeviceVideoSearchScreen.kt
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.Button
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import java.io.File

class DeviceVideoSearchScreen : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            DeviceVideoSearchScreenContent()
        }
    }
}

@Composable
fun DeviceVideoSearchScreenContent() {
    var videoUri by remember { mutableStateOf<Uri?>(null) }
    var videoMetadata by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
           .fillMaxSize()
           .padding(16.dp)
    ) {
        Button(onClick = {
            val intent = Intent(Intent.ACTION_PICK, MediaStore.Video.Media.EXTERNAL_CONTENT_URI)
            startActivityForResult(intent, 1)
        }) {
            Text("Select Video")
        }

        if (videoUri!= null) {
            val metadata = extractVideoMetadata(videoUri!!)
            videoMetadata = metadata
            Text("Video Metadata: $metadata")
        }

        if (videoMetadata!= null) {
            Button(onClick = {
                // Query the backend API with the video metadata
                val title = videoMetadata!!.split(",")[0]
                val duration = videoMetadata!!.split(",")[1].toFloat()
                val aspectRatio = videoMetadata!!.split(",")[2]
                val audioStreamMetadata = videoMetadata!!.split(",")[3]

                val url = "http://localhost:8000/api/v1/search/by-media?title=$title&duration=$duration&aspect_ratio=$aspectRatio&audio_stream_metadata=$audioStreamMetadata"
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                startActivity(intent)
            }) {
                Text("Search for Video")
            }
        }
    }
}

fun extractVideoMetadata(videoUri: Uri): String {
    val mediaMetadataRetriever = MediaMetadataRetriever()
    mediaMetadataRetriever.setDataSource(applicationContext, videoUri)

    val title = mediaMetadataRetriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE)
    val duration = mediaMetadataRetriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
    val aspectRatio = mediaMetadataRetriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH) + "," + mediaMetadataRetriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
    val audioStreamMetadata = mediaMetadataRetriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_AUDIO_CODEC)

    return "$title,$duration,$aspectRatio,$audioStreamMetadata"
}
```

### Kotlin Implementation for In-Player X-Ray Scene Inspect Sheet

We'll implement the in-player X-Ray scene inspect sheet in `PlayerScreen.kt`.

```kotlin
// PlayerScreen.kt
import android.os.Bundle
import android.view.View
import android.widget.Button
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.Button as ComposeButton
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class PlayerScreen : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            PlayerScreenContent()
        }
    }
}

@Composable
fun PlayerScreenContent() {
    var workId by remember { mutableStateOf<String?>(null) }
    var currentTimestamp by remember { mutableStateOf<Long?>(null) }
    var sceneMetadata by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
           .fillMaxSize()
           .padding(16.dp)
    ) {
        ComposeButton(onClick = {
            // Get the current work ID and timestamp
            workId = "12345"
            currentTimestamp = 100L

            // Query the backend API for scene metadata
            val retrofit = Retrofit.Builder()
               .baseUrl("http://localhost:8000/")
               .build()
            val api = retrofit.create(Api::class.java)
            api.getSceneMetadata(workId!!, currentTimestamp!!).enqueue(object : Callback<SceneMetadata> {
                override fun onResponse(call: Call<SceneMetadata>, response: Response<SceneMetadata>) {
                    sceneMetadata = response.body()?.toString()
                }

                override fun onFailure(call: Call<SceneMetadata>, t: Throwable) {
                    sceneMetadata = "Error: $t"
                }
            })
        }) {
            Text("Inspect Scene")
        }

        if (sceneMetadata!= null) {
            Text("Scene Metadata: $sceneMetadata")
        }
    }
}

interface Api {
    @GET("api/v1/scene/metadata")
    fun getSceneMetadata(@Query("work_id") workId: String, @Query("current_timestamp") currentTimestamp: Long): Call<SceneMetadata>
}

data class SceneMetadata(
    val castMembers: List<String>,
    val sceneContext: String,
    val audioLanguage: String,
    val subtitle: String
)
```

Note: The above code is a basic implementation and may need to be modified to fit your specific requirements. Additionally, you will need to implement the `Api` interface and the `SceneMetadata` data class to match your backend API.