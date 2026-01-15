
import psycopg
import os
import random
import uuid
from psycopg import sql
from psycopg_pool import ConnectionPool

# Database connection setup
postgres_password = "eyJraWQiOiJiMDc2MzNlM2QwMGUyOTEzNDkwNmRhNGRiZDg2ZDYzNTEzMGJiNGUyYWNjOTMyZjA1ZmZlZTk2YTU4MWIyZDk1IiwidHlwIjoiYXQrand0IiwiYWxnIjoiUlMyNTYifQ.eyJjbGllbnRfaWQiOiJkYXRhYnJpY2tzLXNlc3Npb24iLCJzY29wZSI6ImlhbS5jdXJyZW50LXVzZXI6cmVhZCBpYW0uZ3JvdXBzOnJlYWQgaWFtLnNlcnZpY2UtcHJpbmNpcGFsczpyZWFkIGlhbS51c2VyczpyZWFkIiwiaXNzIjoiaHR0cHM6Ly9lMi1kb2dmb29kLnN0YWdpbmcuY2xvdWQuZGF0YWJyaWNrcy5jb20vb2lkYyIsImF1ZCI6IjYwNTE5MjE0MTg0MTg4OTMiLCJzdWIiOiJmaXJhcy5mYXJhaEBkYXRhYnJpY2tzLmNvbSIsImlhdCI6MTc1NDUyNTMyMSwiZXhwIjoxNzU0NTI4OTIxLCJqdGkiOiJiNjcwMmNhMy1kNjE2LTQ0ZjQtYTQ2YS00OWM4YTQyZmY0ZmIifQ.ZovW7M1tMnemMU4oO3IZmEDJgh7_lT4BpDJXQUWTwUYAY4vBRVlGnigJDIWI0_thYVWFHVDMtF9B8ulDr5veTgr9Be9SeC6WUgiJm8bp_VE634-crNX3mpVTgqxEDWwRlulBbctpWDxlHFz1h7sD-zxFwVKy_PKsDdxdVmfu-gF_1YE1N_ctkbtCXALS-qXq-6wyLEEN3nAOQxB6AqUeSC7G4pbjvA0qiNKP6YQdF1S67kvPGMB59H_psAxd3y-ZxrgkyOnRYKIXnesN45mKmTR4RXXx3_eLGzfy9WzDpnkJegTe_0LeVhMUKTkY1x3SU_DW8G2L19vImwuSGQaMLw"
connection_pool = None

def get_connection_pool():
    """Get or create the connection pool."""
    global connection_pool
    if connection_pool is None:
        conn_string = (
            f"dbname={os.getenv('PGDATABASE')} "
            f"user={os.getenv('PGUSER')} "
            f"password={postgres_password} "
            f"host={os.getenv('PGHOST')} "
            f"port={os.getenv('PGPORT')} "
            f"sslmode={os.getenv('PGSSLMODE', 'require')} "
            f"application_name={os.getenv('PGAPPNAME')}"
        )
        connection_pool = ConnectionPool(conn_string, min_size=2, max_size=10)
    return connection_pool

def get_connection():
    """Get a connection from the pool."""
    return get_connection_pool().connection()



def init_database():
    """Initialize database schema and tables."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                schema_name = "support"
                
                # Create schema if it doesn't exist
                print(f"🔄 Creating schema '{schema_name}' if it doesn't exist...")
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema_name)))
                print(f"✅ Schema '{schema_name}' is ready")
                
                # Drop and recreate incidents table (read-only)
                print("🔄 Creating incidents table...")
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.incidents").format(sql.Identifier(schema_name)))
                cur.execute(sql.SQL("""
                    CREATE TABLE {}.incidents (
                        incident_id TEXT PRIMARY KEY,
                        support_tier TEXT,
                        error_type TEXT,
                        severity_score REAL,
                        predicted_escalation INTEGER,
                        recommended_action TEXT
                    )
                """).format(sql.Identifier(schema_name)))
                
                # Drop and recreate user_updates table (writable)
                print("🔄 Creating user_updates table...")
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.user_updates").format(sql.Identifier(schema_name)))
                cur.execute(sql.SQL("""
                    CREATE TABLE {}.user_updates (
                        incident_id TEXT PRIMARY KEY,
                        owner TEXT,
                        comment TEXT,
                        status TEXT
                    )
                """).format(sql.Identifier(schema_name)))
                
                conn.commit()
                print("✅ All tables created successfully")
                return True
    except Exception as e:
        print(f"Database initialization error: {e}")
        return False

def insert_sample_data():
    """Insert sample incident data."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                schema_name = "support"
                
                # Sample data
                error_types = ["API_500", "Timeout", "Login_Failure", "Usage_Spike", "Rate_Limit", "DB_Error"]
                actions = ["escalate_to_L2", "investigate_queue", "log", "notify_dev", "deprioritize"]
                support_tiers = ["premium", "enterprise", "paygo"]

                for _ in range(100):
                    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
                    error_type = random.choice(error_types)
                    support_tier = random.choice(support_tiers)
                    score = round(random.uniform(0.2, 0.99), 2)
                    escalate = int(score > 0.7)
                    action = random.choice(actions)
                    
                    cur.execute(sql.SQL("INSERT INTO {}.incidents VALUES (%s, %s, %s, %s, %s, %s)").format(sql.Identifier(schema_name)), 
                                (incident_id, support_tier, error_type, score, escalate, action))

                conn.commit()
                return True
    except Exception as e:
        print(f"Sample data insertion error: {e}")
        return False

if __name__ == "__main__":
    print("🔄 Initializing PostgreSQL database...")
    
    if init_database():
        print("✅ Database schema created successfully")
        
        if insert_sample_data():
            print("✅ Database initialized with 100 sample incidents and user_updates table")
        else:
            print("❌ Failed to insert sample data")
    else:
        print("❌ Failed to initialize database")
    
    # Close the connection pool
    if connection_pool:
        connection_pool.close()
        print("🔌 Connection pool closed")
