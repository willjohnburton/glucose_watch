package com.wb.bgapp.watchface

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import androidx.wear.watchface.editor.EditorSession
import kotlinx.coroutines.launch

class WatchFaceConfigActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lifecycleScope.launch {
            EditorSession.createOnWatchEditorSession(this@WatchFaceConfigActivity)
            finish()
        }
    }
}
