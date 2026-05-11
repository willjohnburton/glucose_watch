package com.wb.bgapp.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "insulin_entries")
data class InsulinEntry(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val units: Int,
    val type: String,
    val timestampMs: Long,
    val glucoseMmol: Double?,
    val trend: String?,
) {
    companion object {
        const val TYPE_FAST = "fast"
        const val TYPE_SLOW = "slow"
    }
}
