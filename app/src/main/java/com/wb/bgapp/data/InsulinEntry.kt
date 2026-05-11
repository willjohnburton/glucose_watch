package com.wb.bgapp.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "insulin_entries")
data class InsulinEntry(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val units: Int,
    val timestampMs: Long,
    val glucoseMmol: Double?,
    val trend: String?,
)
