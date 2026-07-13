package com.wb.bgapp.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface GlucoseDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: GlucoseEntry)

    @Query("SELECT COUNT(*) FROM glucose_entries")
    suspend fun count(): Int
}
