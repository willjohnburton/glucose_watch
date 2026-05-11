package com.wb.bgapp.data

data class GlucoseReading(
    val mmol: Double,
    val trend: GlucoseTrend,
    val timestampMs: Long,
)

enum class GlucoseTrend(val symbol: String) {
    RisingFast("↑"),
    Rising("↗"),
    Stable("→"),
    Falling("↘"),
    FallingFast("↓"),
    Unknown("?");

    companion object {
        fun fromRateMmolPerMin(rate: Double): GlucoseTrend = when {
            rate > 0.15 -> RisingFast
            rate > 0.05 -> Rising
            rate < -0.15 -> FallingFast
            rate < -0.05 -> Falling
            else -> Stable
        }

        fun fromJugglucoRate(rate: Float?): GlucoseTrend {
            if (rate == null) return Unknown
            return fromRateMmolPerMin(rate.toDouble())
        }

        fun fromNightscoutDirection(direction: String?): GlucoseTrend = when (direction) {
            "DoubleUp" -> RisingFast
            "SingleUp", "FortyFiveUp" -> Rising
            "Flat" -> Stable
            "FortyFiveDown", "SingleDown" -> Falling
            "DoubleDown" -> FallingFast
            else -> Unknown
        }
    }
}
