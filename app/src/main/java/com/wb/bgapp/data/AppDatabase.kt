package com.wb.bgapp.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [InsulinEntry::class, GlucoseEntry::class], version = 3, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun insulinDao(): InsulinDao
    abstract fun glucoseDao(): GlucoseDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        // v2 -> v3: add glucose_entries without touching existing insulin data.
        // Column types must match what Room generates for GlucoseEntry.
        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS `glucose_entries` (" +
                        "`minuteEpoch` INTEGER NOT NULL, " +
                        "`mmol` REAL NOT NULL, " +
                        "`trend` TEXT NOT NULL, " +
                        "PRIMARY KEY(`minuteEpoch`))"
                )
            }
        }

        fun get(context: Context): AppDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                AppDatabase::class.java,
                "bg.db",
            )
                .addMigrations(MIGRATION_2_3)
                .fallbackToDestructiveMigration()
                .build()
                .also { instance = it }
        }
    }
}
