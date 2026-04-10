import asyncio
import aiosqlite
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def migrate_data():
    sqlite_db = "ordertracker.db"
    if not os.path.exists(sqlite_db):
        print(f"SQLite database {sqlite_db} not found.")
        return

    # Connection params
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "password")
    host = os.getenv("POSTGRES_SERVER", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "ordertracker")
    
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    # Postgres connection
    pg_conn = await asyncpg.connect(dsn)

    # SQLite connection
    sl_conn = await aiosqlite.connect(sqlite_db)

    tables = [
        "tenants", "users", "invites", "orders", 
        "payments", "products", "global_config", "sheet_sync_queue"
    ]

    try:
        for table in tables:
            print(f"Migrating table: {table}...")
            
            # Get columns metadata
            async with sl_conn.execute(f"PRAGMA table_info({table})") as cursor:
                cols_info = await cursor.fetchall()
                cols = [col[1] for col in cols_info]
                types = [col[2].upper() for col in cols_info]
            
            # Get data from SQLite
            async with sl_conn.execute(f"SELECT * FROM {table}") as cursor:
                sl_rows = await cursor.fetchall()
            
            if not sl_rows:
                print(f"No data in {table}, skipping.")
                continue

            # Process rows to handle boolean conversion, JSON, and Datetime
            processed_rows = []
            for row in sl_rows:
                new_row = list(row)
                for i, (col_name, col_type) in enumerate(zip(cols, types)):
                    val = new_row[i]
                    # Convert 0/1 to False/True for BOOLEAN columns
                    if col_type == "BOOLEAN" and val is not None:
                        new_row[i] = bool(val)
                    # Handle JSON strings in SQLite to dict for asyncpg
                    if col_type == "JSON" and val is not None:
                        import json
                        if isinstance(val, dict) or isinstance(val, list):
                            new_row[i] = json.dumps(val)
                        elif isinstance(val, str):
                            # Already a string, leave as is (it's already JSON string in SQLite)
                            pass
                    
                    # Convert datetime strings to datetime objects
                    if ("DATETIME" in col_type or "TIMESTAMP" in col_type) and val is not None and isinstance(val, str):
                        from datetime import datetime
                        # Handle ISO format strings
                        try:
                            # Remove 'Z' if present for ISO parsing, or handle it
                            clean_val = val.replace("Z", "")
                            # Try multiple formats if needed, but ISO is standard here
                            new_row[i] = datetime.fromisoformat(clean_val)
                        except Exception as e:
                            print(f"Warning: Failed to parse datetime string '{val}' for column {col_name}: {e}")
                
                # FINAL TYPE CHECK: If we still have an error, we might need to cast to str for some columns
                # especially if Postgres expects a string for a text column but we gave it a dict.
                # But for now let's hope the above fix works for JSON columns.
                processed_rows.append(tuple(new_row))

            col_str = ", ".join([f'"{c}"' for c in cols])
            placeholders = ", ".join([f"${i+1}" for i in range(len(cols))])

            # Clear target table first (CASCADE to handle foreign keys if any)
            await pg_conn.execute(f'TRUNCATE TABLE "{table}" CASCADE')

            # Insert into Postgres
            insert_query = f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders})'
            
            # Batch insert
            await pg_conn.executemany(insert_query, processed_rows)
            print(f"Successfully migrated {len(sl_rows)} records for {table}.")

        print("Migration completed successfully!")
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        await sl_conn.close()
        await pg_conn.close()

if __name__ == "__main__":
    asyncio.run(migrate_data())
