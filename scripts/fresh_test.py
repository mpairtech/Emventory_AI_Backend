from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


url = "postgresql://postgres:sAkawat321@localhost:5433/Search"
engine = create_engine(url, poolclass=NullPool)

print("Testing Docker PostgreSQL on port 5433...\n")

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT tablename 
        FROM pg_tables 
        WHERE tablename = 'product_vectors' 
        AND schemaname = 'public';
    """))
    
    tables = result.fetchall()
    print(f"Result: {tables}")
    
    if tables:
        print("✅ SUCCESS! Table found in Docker PostgreSQL!")
        
   
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'product_vectors'
            ORDER BY ordinal_position;
        """))
        columns = result.fetchall()
        print("\nTable structure:")
        for col in columns:
            print(f"  {col[0]}: {col[1]}")
    else:
        print("❌ Table not found")

engine.dispose()