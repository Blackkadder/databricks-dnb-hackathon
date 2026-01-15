
import psycopg
import os
import random
import uuid
from psycopg import sql
from psycopg_pool import ConnectionPool

# Database connection setup
postgres_password = "xxxx"
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
