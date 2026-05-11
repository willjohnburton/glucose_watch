package com.wb.bgapp.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface InsulinDao {
    @Insert
    suspend fun insert(entry: InsulinEntry): Long

    @Query("SELECT * FROM insulin_entries ORDER BY timestampMs DESC LIMIT 100")
    fun recent(): Flow<List<InsulinEntry>>
}
