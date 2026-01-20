from sqlalchemy import text

class VectorStore:
    @staticmethod
    def search(db, embedding):
        sql = text("""
            SELECT product_id,
                   1 - (embedding <=> :q) AS score
            FROM product_vectors
            ORDER BY embedding <=> :q
            LIMIT 10
        """)
        return db.execute(sql, {"q": embedding}).fetchall()
