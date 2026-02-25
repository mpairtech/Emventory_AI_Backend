from sqlalchemy import create_engine, text

url = f"postgresql://postgres:sAkawat321@localhost:5432/Search"
engine = create_engine(url)

with engine.connect() as conn:
    # Check current database
    result = conn.execute(text("SELECT current_database();"))
    print(f"Current database: {result.fetchone()[0]}")
    
    # List ALL databases
    result = conn.execute(text("""
        SELECT datname FROM pg_database 
        WHERE datistemplate = false;
    """))
    databases = [row[0] for row in result.fetchall()]
    print(f"\nAll databases: {databases}")
    
    # Check all schemas in current database
    result = conn.execute(text("""
        SELECT schema_name 
        FROM information_schema.schemata;
    """))
    schemas = [row[0] for row in result.fetchall()]
    print(f"\nAll schemas: {schemas}")
    
    # List tables in ALL schemas
    result = conn.execute(text("""
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name;
    """))
    tables = result.fetchall()
    print(f"\nAll tables (schema.table):")
    for schema, table in tables:
        print(f"  {schema}.{table}")
    
    # Specifically check for product_vectors in public schema
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM pg_tables 
            WHERE schemaname = 'public' 
            AND tablename = 'product_vectors'
        );
    """))
    exists = result.fetchone()[0]
    print(f"\nproduct_vectors in public schema: {exists}")