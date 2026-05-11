package com.wb.bgapp.watchface

import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.view.SurfaceHolder
import androidx.wear.watchface.CanvasType
import androidx.wear.watchface.ComplicationSlotsManager
import androidx.wear.watchface.Renderer
import androidx.wear.watchface.TapEvent
import androidx.wear.watchface.TapType
import androidx.wear.watchface.WatchFace
import androidx.wear.watchface.WatchFaceService
import androidx.wear.watchface.WatchFaceType
import androidx.wear.watchface.WatchState
import androidx.wear.watchface.style.CurrentUserStyleRepository
import androidx.wear.watchface.style.UserStyleSchema
import com.wb.bgapp.data.GlucoseReading
import com.wb.bgapp.data.GlucoseRepository
import com.wb.bgapp.ui.InsulinLoggerActivity
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

class BgWatchFaceService : WatchFaceService() {

    override fun createUserStyleSchema(): UserStyleSchema = UserStyleSchema(emptyList())

    override fun createComplicationSlotsManager(
        currentUserStyleRepository: CurrentUserStyleRepository
    ): ComplicationSlotsManager = ComplicationSlotsManager(emptyList(), currentUserStyleRepository)

    override suspend fun createWatchFace(
        surfaceHolder: SurfaceHolder,
        watchState: WatchState,
        complicationSlotsManager: ComplicationSlotsManager,
        currentUserStyleRepository: CurrentUserStyleRepository,
    ): WatchFace {
        val renderer = BgRenderer(surfaceHolder, watchState, currentUserStyleRepository)
        return WatchFace(WatchFaceType.DIGITAL, renderer)
            .setTapListener(object : WatchFace.TapListener {
                override fun onTapEvent(
                    tapType: Int,
                    tapEvent: TapEvent,
                    complicationSlot: androidx.wear.watchface.ComplicationSlot?,
                ) {
                    if (tapType == TapType.UP && renderer.glucoseHitRect.contains(tapEvent.xPos, tapEvent.yPos)) {
                        val intent = Intent(this@BgWatchFaceService, InsulinLoggerActivity::class.java)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        startActivity(intent)
                    }
                }
            })
    }
}

private class BgRenderer(
    surfaceHolder: SurfaceHolder,
    watchState: WatchState,
    userStyle: CurrentUserStyleRepository,
) : Renderer.CanvasRenderer2<BgRenderer.Shared>(
    surfaceHolder,
    userStyle,
    watchState,
    CanvasType.HARDWARE,
    INTERACTIVE_UPDATE_RATE_MS,
    clearWithBackgroundTintBeforeRenderingHighlightLayer = false,
) {
    class Shared : Renderer.SharedAssets {
        override fun onDestroy() = Unit
    }

    val glucoseHitRect = Rect()

    private val zone = ZoneId.systemDefault()
    private val timeFmt = DateTimeFormatter.ofPattern("HH:mm")

    private val bgPaint = Paint().apply { color = Color.BLACK }
    private val timePaint = Paint().apply {
        color = Color.WHITE
        isAntiAlias = true
        textAlign = Paint.Align.CENTER
    }
    private val glucosePaint = Paint().apply {
        isAntiAlias = true
        textAlign = Paint.Align.CENTER
    }
    private val trendPaint = Paint().apply {
        isAntiAlias = true
        textAlign = Paint.Align.LEFT
    }
    private val smallPaint = Paint().apply {
        color = Color.LTGRAY
        isAntiAlias = true
        textAlign = Paint.Align.CENTER
    }
    private val stalePaint = Paint().apply {
        color = Color.RED
        isAntiAlias = true
    }
    private val ambientDimPaint = Paint().apply {
        color = Color.WHITE
        isAntiAlias = true
        textAlign = Paint.Align.CENTER
    }

    override suspend fun createSharedAssets(): Shared = Shared()

    override fun render(canvas: Canvas, bounds: Rect, zonedDateTime: ZonedDateTime, sharedAssets: Shared) {
        canvas.drawRect(bounds, bgPaint)

        val cx = bounds.exactCenterX()
        val w = bounds.width().toFloat()
        val isAmbient = renderParameters.drawMode == androidx.wear.watchface.DrawMode.AMBIENT

        val timeText = zonedDateTime.withZoneSameInstant(zone).format(timeFmt)
        timePaint.textSize = w * 0.30f
        val timeY = bounds.exactCenterY() - w * 0.05f
        canvas.drawText(timeText, cx, timeY, timePaint)

        val reading = GlucoseRepository.latest.value
        val nowMs = System.currentTimeMillis()

        val glucoseBaseY = bounds.exactCenterY() + w * 0.20f
        if (reading == null) {
            glucosePaint.color = Color.LTGRAY
            glucosePaint.textSize = w * 0.18f
            canvas.drawText("--", cx, glucoseBaseY, glucosePaint)
            glucoseHitRect.set((cx - w * 0.25f).toInt(), (glucoseBaseY - w * 0.20f).toInt(),
                (cx + w * 0.25f).toInt(), (glucoseBaseY + w * 0.05f).toInt())
        } else {
            glucosePaint.color = if (isAmbient) Color.WHITE else colourFor(reading.mmol)
            glucosePaint.textSize = w * 0.22f
            val glucoseText = String.format("%.1f", reading.mmol)
            canvas.drawText(glucoseText, cx, glucoseBaseY, glucosePaint)

            val textWidth = glucosePaint.measureText(glucoseText)
            trendPaint.color = glucosePaint.color
            trendPaint.textSize = w * 0.16f
            val trendX = cx + textWidth / 2f + w * 0.02f
            canvas.drawText(reading.trend.symbol, trendX, glucoseBaseY, trendPaint)

            glucoseHitRect.set((cx - w * 0.30f).toInt(), (glucoseBaseY - w * 0.22f).toInt(),
                (cx + w * 0.30f).toInt(), (glucoseBaseY + w * 0.05f).toInt())

            if (!isAmbient) {
                val minsAgo = ((nowMs - reading.timestampMs) / 60_000L).toInt().coerceAtLeast(0)
                smallPaint.textSize = w * 0.07f
                canvas.drawText("$minsAgo min", cx, bounds.bottom - w * 0.10f, smallPaint)

                if (minsAgo >= 5) {
                    val r = w * 0.018f
                    canvas.drawCircle(cx, bounds.bottom - w * 0.18f, r, stalePaint)
                }
            }
        }
    }

    override fun renderHighlightLayer(
        canvas: Canvas,
        bounds: Rect,
        zonedDateTime: ZonedDateTime,
        sharedAssets: Shared,
    ) {
        val paint = Paint().apply {
            color = renderParameters.highlightLayer?.backgroundTint ?: Color.argb(80, 255, 255, 255)
            style = Paint.Style.STROKE
            strokeWidth = 4f
        }
        canvas.drawRect(RectF(glucoseHitRect), paint)
    }

    private fun colourFor(mmol: Double): Int = when {
        mmol < 3.5 || mmol > 13.0 -> Color.rgb(255, 80, 80)
        mmol < 4.0 || mmol > 10.0 -> Color.rgb(255, 180, 0)
        else -> Color.rgb(80, 220, 100)
    }

    companion object {
        private const val INTERACTIVE_UPDATE_RATE_MS = 1000L
    }
}
