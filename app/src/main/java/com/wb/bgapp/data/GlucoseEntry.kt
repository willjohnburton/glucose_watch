package com.wb.bgapp.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One persisted glucose reading. Keyed by epoch minute (timestampMs / 60000) so
 * that the many broadcasts Juggluco emits within the same minute collapse to a
 * single row on insert (OnConflictStrategy.REPLACE keeps the latest).
 */
@Entity(tableName = "glucose_entries")
data class GlucoseEntry(
    @PrimaryKey val minuteEpoch: Long,
    val mmol: Double,
    val trend: String,
)
