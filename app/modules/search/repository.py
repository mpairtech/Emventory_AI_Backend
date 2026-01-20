from app.db.models.vector import ProductVector

class SearchRepository:
    @staticmethod
    def upsert(db, vector: ProductVector):
        db.merge(vector)
        db.commit()
