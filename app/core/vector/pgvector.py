from sqlalchemy import text

class VectorStore:
    @staticmethod
    def search(db, embedding):
        # Convert Python list to PostgreSQL vector format
        embedding_str = '[' + ','.join(map(str, embedding)) + ']'
        
        sql = text("""
            SELECT product_id,
                   name,
                   category,
                   price,
                   1 - (embedding <=> CAST(:q AS vector)) AS score
            FROM product_vectors
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT 10
        """)
        
        results = db.execute(sql, {"q": embedding_str}).fetchall()
        
        # Format results
        return [
            {
                "product_id": row[0],
                "name": row[1],
                "category": row[2],
                "price": float(row[3]),
                "similarity_score": float(row[4])
            }
            for row in results
        ]