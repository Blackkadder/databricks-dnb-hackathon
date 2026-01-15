# app.py
from flask import Flask, render_template, request, redirect
import psycopg
import os
import time
import plotly.graph_objs as go
import plotly.io as pio
from databricks import sdk
from psycopg import sql
from psycopg_pool import ConnectionPool

app = Flask(__name__)

# Database connection setup
workspace_client = sdk.WorkspaceClient()
postgres_password = None
last_password_refresh = 0
connection_pool = None

def refresh_oauth_token():
    """Refresh OAuth token if expired."""
    global postgres_password, last_password_refresh
    if postgres_password is None or time.time() - last_password_refresh > 900:
        print("Refreshing PostgreSQL OAuth token")
        try:
            # Check if we're in local testing mode
            local_testing_pwd = os.getenv('LOCAL_TESTING_PWD')
            if local_testing_pwd:
                print("🔧 Using local testing password from environment variable")
                postgres_password = local_testing_pwd
            else:
                print("☁️ Using Databricks OAuth token")
                postgres_password = workspace_client.config.oauth_token().access_token
            
            last_password_refresh = time.time()
        except Exception as e:
            print(f"❌ Failed to refresh OAuth token: {str(e)}")
            return False
    return True

def get_connection_pool():
    """Get or create the connection pool."""

    global connection_pool
    if connection_pool is None:
        print("Getting connection pool")
        refresh_oauth_token()
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
    print("Getting connection from pool")
    global connection_pool
    
    # Recreate pool if token expired
    if postgres_password is None or time.time() - last_password_refresh > 900:
        if connection_pool:
            connection_pool.close()
            connection_pool = None
    
    return get_connection_pool().connection()

# Utility: get unique error types from database
def get_error_types():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT DISTINCT error_type FROM support.incidents_w_preds_st WHERE error_type IS NOT NULL ORDER BY error_type"))
                error_types = [row[0] for row in cur.fetchall()]
                return error_types
    except Exception as e:
        print(f"Error fetching error types: {e}")
        return []

# Utility: get unique support tiers from database
def get_support_tiers():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT DISTINCT support_tier FROM support.incidents_w_preds_st WHERE support_tier IS NOT NULL ORDER BY support_tier"))
                support_tiers = [row[0] for row in cur.fetchall()]
                return support_tiers
    except Exception as e:
        print(f"Error fetching support tiers: {e}")
        return []

# Utility: get unique recommended actions from database
def get_recommended_actions():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT DISTINCT recommended_action FROM support.incidents_w_preds_st WHERE recommended_action IS NOT NULL ORDER BY recommended_action"))
                actions = [row[0] for row in cur.fetchall()]
                return actions
    except Exception as e:
        print(f"Error fetching recommended actions: {e}")
        return []

# Utility: get unique predicted escalation values from database
def get_predicted_escalations():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT DISTINCT predicted_escalation FROM support.incidents_w_preds_st WHERE predicted_escalation IS NOT NULL ORDER BY predicted_escalation"))
                escalations = [row[0] for row in cur.fetchall()]
                return escalations
    except Exception as e:
        print(f"Error fetching predicted escalations: {e}")
        return []

# Utility: fetch incidents from DB with comprehensive filtering
def get_incidents(min_score=0.0, status_filter=None, error_type_filter=None, owner_filter=None, support_tier_filter=None, predicted_escalation_filter=None):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Build dynamic query with LEFT JOIN to user_updates table
                query = sql.SQL("""
                    SELECT i.*, 
                           COALESCE(u.owner, 'Unassigned') as owner,
                           COALESCE(u.comment, '') as comment,
                           COALESCE(u.status, 'open') as status
                    FROM support.incidents_w_preds_st i
                    LEFT JOIN support.user_updates u ON i.incident_id = u.incident_id
                    WHERE 1=1
                """)
                params = []
                
                if min_score is not None:
                    query = sql.SQL("{} AND i.severity_score >= %s").format(query)
                    params.append(min_score)
                
                if status_filter:
                    query = sql.SQL("{} AND COALESCE(u.status, 'open') = %s").format(query)
                    params.append(status_filter)
                
                if error_type_filter:
                    query = sql.SQL("{} AND i.error_type = %s").format(query)
                    params.append(error_type_filter)
                
                if owner_filter:
                    if owner_filter == "unassigned":
                        query = sql.SQL("{} AND (u.owner IS NULL OR u.owner = '')").format(query)
                    else:
                        query = sql.SQL("{} AND u.owner = %s").format(query)
                        params.append(owner_filter)
                
                if support_tier_filter:
                    query = sql.SQL("{} AND i.support_tier = %s").format(query)
                    params.append(support_tier_filter)
                
                if predicted_escalation_filter:
                    query = sql.SQL("{} AND i.predicted_escalation = %s").format(query)
                    params.append(predicted_escalation_filter)
                
                query = sql.SQL("{} ORDER BY i.severity_score DESC").format(query)
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                # Convert to list of dictionaries for compatibility
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"Error fetching incidents: {e}")
        return []

# Utility: update owner for incident
def assign_owner(incident_id, owner):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check if record exists in user_updates
                cur.execute(sql.SQL("SELECT incident_id FROM support.user_updates WHERE incident_id = %s"), (incident_id,))
                exists = cur.fetchone()
                
                if exists:
                    # Update existing record
                    cur.execute(sql.SQL("UPDATE support.user_updates SET owner = %s WHERE incident_id = %s"), (owner, incident_id))
                else:
                    # Insert new record
                    cur.execute(sql.SQL("INSERT INTO support.user_updates (incident_id, owner, comment, status) VALUES (%s, %s, '', 'open')"), (incident_id, owner))
                
                conn.commit()
                return True
    except Exception as e:
        print(f"Error assigning owner: {e}")
        return False

# Utility: update comment and status
def update_comment_status(incident_id, comment, status):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check if record exists in user_updates
                cur.execute(sql.SQL("SELECT incident_id FROM support.user_updates WHERE incident_id = %s"), (incident_id,))
                exists = cur.fetchone()
                
                if exists:
                    # Update existing record
                    cur.execute(sql.SQL("UPDATE support.user_updates SET comment = %s, status = %s WHERE incident_id = %s"), (comment, status, incident_id))
                else:
                    # Insert new record
                    cur.execute(sql.SQL("INSERT INTO support.user_updates (incident_id, owner, comment, status) VALUES (%s, '', %s, %s)"), (incident_id, comment, status))
                
                conn.commit()
                return True
    except Exception as e:
        print(f"Error updating comment/status: {e}")
        return False

# Utility: get list of unique owners from user_updates table
def get_owners():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("""
                    SELECT DISTINCT u.owner 
                    FROM support.user_updates u
                    INNER JOIN support.incidents_w_preds_st i ON u.incident_id = i.incident_id
                    WHERE u.owner IS NOT NULL AND u.owner != '' 
                    ORDER BY u.owner
                """))
                owners = [row[0] for row in cur.fetchall()]
                return owners
    except Exception as e:
        print(f"Error fetching owners: {e}")
        return []

# Utility: generate Plotly bar chart for error type counts
def generate_error_chart(incidents=None):
    if incidents is None:
        # If no incidents provided, get all incidents
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("SELECT error_type, COUNT(*) FROM support.incidents_w_preds_st GROUP BY error_type"))
                    data = cur.fetchall()
        except Exception as e:
            print(f"Error generating error chart: {e}")
            data = []
    else:
        # Use provided incidents (filtered data)
        from collections import Counter
        error_types = [incident['error_type'] for incident in incidents]
        counter = Counter(error_types)
        data = list(counter.items())

    error_types = [row[0] for row in data]
    counts = [row[1] for row in data]

    fig = go.Figure([go.Bar(x=error_types, y=counts)])
    fig.update_layout(
        xaxis_title="Error Type",
        yaxis_title="Count",
        template="plotly_white",
        height=450
    )
    return pio.to_html(fig, full_html=False)

# Utility: generate Plotly pie chart for status distribution
def generate_status_chart(incidents=None):
    if incidents is None:
        # If no incidents provided, get all incidents
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("""
                        SELECT COALESCE(u.status, 'open') as status, COUNT(*) 
                        FROM support.incidents_w_preds_st i
                        LEFT JOIN support.user_updates u ON i.incident_id = u.incident_id
                        GROUP BY COALESCE(u.status, 'open')
                    """))
                    data = cur.fetchall()
        except Exception as e:
            print(f"Error generating status chart: {e}")
            data = []
    else:
        # Use provided incidents (filtered data)
        from collections import Counter
        statuses = [incident['status'] for incident in incidents]
        counter = Counter(statuses)
        data = list(counter.items())

    statuses = [row[0].replace('_', ' ').title() for row in data]
    counts = [row[1] for row in data]
    
    # Define colors for each status
    colors = ['#e74c3c', '#f39c12', '#27ae60']  # Red for open, Orange for in progress, Green for resolved

    fig = go.Figure(data=[go.Pie(labels=statuses, values=counts, hole=0.3)])
    fig.update_traces(
        textposition='inside',
        textinfo='percent+label',
        marker=dict(colors=colors)
    )
    fig.update_layout(
        template="plotly_white",
        height=450,
        showlegend=False
    )
    return pio.to_html(fig, full_html=False)

@app.route("/")
def index():
    # Get filter parameters from request
    min_score = float(request.args.get("min_score", 0.0))
    status_filter = request.args.get("status_filter", "")
    error_type_filter = request.args.get("error_type_filter", "")
    owner_filter = request.args.get("owner_filter", "")
    support_tier_filter = request.args.get("support_tier_filter", "")
    predicted_escalation_filter = request.args.get("predicted_escalation_filter", "")
    
    # Convert empty strings to None for filtering
    status_filter = status_filter if status_filter else None
    error_type_filter = error_type_filter if error_type_filter else None
    owner_filter = owner_filter if owner_filter else None
    support_tier_filter = support_tier_filter if support_tier_filter else None
    predicted_escalation_filter = predicted_escalation_filter if predicted_escalation_filter else None
    
    incidents = get_incidents(min_score, status_filter, error_type_filter, owner_filter, support_tier_filter, predicted_escalation_filter)
    chart_html = generate_error_chart(incidents)
    status_chart_html = generate_status_chart(incidents)
    
    # Get dynamic dropdown values
    owners = get_owners()
    error_types = get_error_types()
    support_tiers = get_support_tiers()
    predicted_escalations = get_predicted_escalations()
    
    return render_template("incidents.html", 
                         incidents=incidents, 
                         chart_html=chart_html, 
                         status_chart_html=status_chart_html, 
                         owners=owners,
                         error_types=error_types,
                         support_tiers=support_tiers,
                         predicted_escalations=predicted_escalations)

@app.route("/test")
def test_filters():
    """Test route to verify filters work"""
    # Test different filter combinations
    test_cases = [
        {"min_score": 0.7, "description": "High severity only"},
        {"status_filter": "open", "description": "Open incidents only"},
        {"error_type_filter": "API_TIMEOUT", "description": "API_TIMEOUT errors only"},
        {"owner_filter": "Firas", "description": "Firas incidents only"},
        {"min_score": 0.5, "status_filter": "open", "description": "Open incidents with severity >= 0.5"},
    ]
    
    results = []
    for test in test_cases:
        incidents = get_incidents(**{k: v for k, v in test.items() if k != "description"})
        results.append(f"{test['description']}: {len(incidents)} incidents")
    
    return "<br>".join(results)

@app.route("/debug")
def debug_db():
    """Debug route to check database contents"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get some sample data
                cur.execute(sql.SQL("""
                    SELECT i.incident_id, i.error_type, i.severity_score, 
                           COALESCE(u.status, 'open') as status, 
                           COALESCE(u.owner, 'Unassigned') as owner 
                    FROM support.incidents_w_preds_st i
                    LEFT JOIN support.user_updates u ON i.incident_id = u.incident_id
                    LIMIT 5
                """))
                sample_data = cur.fetchall()
                
                # Get counts by status
                cur.execute(sql.SQL("""
                    SELECT COALESCE(u.status, 'open') as status, COUNT(*) 
                    FROM support.incidents_w_preds_st i
                    LEFT JOIN support.user_updates u ON i.incident_id = u.incident_id
                    GROUP BY COALESCE(u.status, 'open')
                """))
                status_counts = cur.fetchall()
                
                # Get counts by error type
                cur.execute(sql.SQL("SELECT error_type, COUNT(*) FROM support.incidents_w_preds_st GROUP BY error_type"))
                error_counts = cur.fetchall()
                
                # Get counts by owner
                cur.execute(sql.SQL("""
                    SELECT COALESCE(u.owner, 'Unassigned') as owner, COUNT(*) 
                    FROM support.incidents_w_preds_st i
                    LEFT JOIN support.user_updates u ON i.incident_id = u.incident_id
                    GROUP BY COALESCE(u.owner, 'Unassigned')
                """))
                owner_counts = cur.fetchall()
        
        result = "<h2>Database Debug Info</h2>"
        result += "<h3>Sample Data:</h3>"
        for row in sample_data:
            result += f"<p>{dict(zip(['incident_id', 'error_type', 'severity_score', 'status', 'owner'], row))}</p>"
        
        result += "<h3>Status Counts:</h3>"
        for row in status_counts:
            result += f"<p>{row[0]}: {row[1]}</p>"
        
        result += "<h3>Error Type Counts:</h3>"
        for row in error_counts:
            result += f"<p>{row[0]}: {row[1]}</p>"
        
        result += "<h3>Owner Counts:</h3>"
        for row in owner_counts:
            result += f"<p>{row[0] or 'None'}: {row[1]}</p>"
        
        return result
    except Exception as e:
        return f"<h2>Database Debug Error</h2><p>Error: {e}</p>"

@app.route("/assign", methods=["POST"])
def assign():
    incident_id = request.form["incident_id"]
    owner = request.form["owner"]
    assign_owner(incident_id, owner)
    return redirect("/")

@app.route("/comment", methods=["POST"])
def comment():
    incident_id = request.form["incident_id"]
    comment = request.form["comment"]
    status = request.form["status"]
    update_comment_status(incident_id, comment, status)
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)
