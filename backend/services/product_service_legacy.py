"""
Product service for legacy ePerformance products table.
Business logic for product catalog management.
"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional

from backend.core.models_legacy import ProductLegacy
from backend.api.schemas_legacy import (
    ProductLegacyCreate,
    ProductLegacyUpdate,
)


class ProductServiceLegacy:
    """Service layer for product catalog management (legacy format)"""
    
    @staticmethod
    def create_product(db: Session, data: ProductLegacyCreate) -> ProductLegacy:
        """
        Create a new product.
        
        Args:
            db: Database session
            data: Product creation data
            
        Returns:
            Created product instance
        """
        from datetime import datetime
        
        product = ProductLegacy(
            slug=data.slug,
            nom=data.nom,
            description=data.description,
            type=data.type,
            category=data.category,
            prix_unitaire=data.prix_unitaire,
            devise=data.devise,
            billing_type=data.billing_type,
            features_json=data.features_json,
            quota_mensuel=data.quota_mensuel,
            is_active=data.is_active,
            is_visible=data.is_visible,
            requires_approval=data.requires_approval,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        
        db.add(product)
        db.commit()
        db.refresh(product)
        
        return product
    
    @staticmethod
    def get_product(db: Session, product_id: int) -> Optional[ProductLegacy]:
        """Get product by ID"""
        return db.query(ProductLegacy).filter(
            ProductLegacy.id == product_id
        ).first()
    
    @staticmethod
    def get_product_by_slug(db: Session, slug: str) -> Optional[ProductLegacy]:
        """Get product by slug"""
        return db.query(ProductLegacy).filter(
            ProductLegacy.slug == slug
        ).first()
    
    @staticmethod
    def list_products(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        type: Optional[str] = None,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_visible: Optional[bool] = None,
        billing_type: Optional[str] = None
    ) -> tuple[List[ProductLegacy], int]:
        """
        List all products with filters.
        
        Returns:
            Tuple of (products list, total count)
        """
        query = db.query(ProductLegacy)
        
        if type:
            query = query.filter(ProductLegacy.type == type)
        if category:
            query = query.filter(ProductLegacy.category == category)
        if is_active is not None:
            query = query.filter(ProductLegacy.is_active == is_active)
        if is_visible is not None:
            query = query.filter(ProductLegacy.is_visible == is_visible)
        if billing_type:
            query = query.filter(ProductLegacy.billing_type == billing_type)
        
        total = query.count()
        products = query.order_by(
            ProductLegacy.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return products, total
    
    @staticmethod
    def get_catalog(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        type: Optional[str] = None,
        category: Optional[str] = None
    ) -> tuple[List[ProductLegacy], int]:
        """
        Get public catalog (only active and visible products).
        
        Returns:
            Tuple of (products list, total count)
        """
        query = db.query(ProductLegacy).filter(
            and_(
                ProductLegacy.is_active == True,
                ProductLegacy.is_visible == True
            )
        )
        
        if type:
            query = query.filter(ProductLegacy.type == type)
        if category:
            query = query.filter(ProductLegacy.category == category)
        
        total = query.count()
        products = query.order_by(
            ProductLegacy.prix_unitaire.asc()  # Order by price ascending
        ).offset(skip).limit(limit).all()
        
        return products, total
    
    @staticmethod
    def update_product(
        db: Session,
        product_id: int,
        data: ProductLegacyUpdate
    ) -> Optional[ProductLegacy]:
        """
        Update product fields.
        
        Args:
            db: Database session
            product_id: Product ID
            data: Fields to update
            
        Returns:
            Updated product or None if not found
        """
        from datetime import datetime
        
        product = db.query(ProductLegacy).filter(
            ProductLegacy.id == product_id
        ).first()
        
        if not product:
            return None
        
        # Update fields if provided
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(product, field, value)
        
        product.updated_at = datetime.now()
        
        db.commit()
        db.refresh(product)
        
        return product
    
    @staticmethod
    def delete_product(db: Session, product_id: int) -> bool:
        """
        Soft delete a product (set is_active=False, is_visible=False).
        
        Args:
            db: Database session
            product_id: Product ID
            
        Returns:
            True if deleted, False if not found
        """
        from datetime import datetime
        
        product = db.query(ProductLegacy).filter(
            ProductLegacy.id == product_id
        ).first()
        
        if not product:
            return False
        
        product.is_active = False
        product.is_visible = False
        product.updated_at = datetime.now()
        
        db.commit()
        
        return True
    
    @staticmethod
    def search_products(
        db: Session,
        search_term: str,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[ProductLegacy], int]:
        """
        Search products by name or description.
        
        Args:
            db: Database session
            search_term: Search term
            skip: Offset for pagination
            limit: Max results
            
        Returns:
            Tuple of (products list, total count)
        """
        search_pattern = f"%{search_term}%"
        
        query = db.query(ProductLegacy).filter(
            and_(
                ProductLegacy.is_active == True,
                ProductLegacy.is_visible == True,
                or_(
                    ProductLegacy.nom.like(search_pattern),
                    ProductLegacy.description.like(search_pattern)
                )
            )
        )
        
        total = query.count()
        products = query.offset(skip).limit(limit).all()
        
        return products, total
