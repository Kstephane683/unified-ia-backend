"""
Product routes for legacy ePerformance products table.
REST API endpoints for product catalog management.
Phase 1-S1.2: Routes CRUD Products
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

from backend.core.database import get_db
from backend.core.models_legacy import ProductLegacy
from backend.services.product_service_legacy import ProductServiceLegacy
from backend.api.schemas_legacy import (
    ProductLegacyCreate,
    ProductLegacyUpdate,
    ProductLegacyResponse,
    ProductLegacyList,
)


router = APIRouter(prefix="/api/products", tags=["Products"])


def _product_to_response(product: ProductLegacy) -> ProductLegacyResponse:
    """Helper to convert SQLAlchemy model to Pydantic response"""
    return ProductLegacyResponse(
        id=product.id,
        slug=product.slug,
        nom=product.nom,
        description=product.description,
        type=product.type,
        category=product.category,
        prix_unitaire=float(product.prix_unitaire),
        devise=product.devise,
        billing_type=product.billing_type,
        features_json=product.features_json,
        quota_mensuel=product.quota_mensuel,
        is_active=product.is_active,
        is_visible=product.is_visible,
        requires_approval=product.requires_approval,
        created_at=product.created_at,
        updated_at=product.updated_at
    )


@router.post("", response_model=ProductLegacyResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    data: ProductLegacyCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new product (admin only).
    
    - **slug**: Unique URL-friendly identifier
    - **nom**: Product name
    - **type**: site_web, module, formation, or service
    - **prix_unitaire**: Price in currency units
    - **billing_type**: one_time, monthly, or yearly
    """
    # Check if slug already exists
    existing = ProductServiceLegacy.get_product_by_slug(db, data.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product with slug '{data.slug}' already exists"
        )
    
    product = ProductServiceLegacy.create_product(db, data)
    return _product_to_response(product)


@router.get("/catalog", response_model=ProductLegacyList)
def get_catalog(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    type: Optional[str] = Query(None, description="Filter by type"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db)
):
    """
    Get public product catalog (only active and visible products).
    
    This is the main endpoint for customers to browse products.
    """
    skip = (page - 1) * page_size
    
    products, total = ProductServiceLegacy.get_catalog(
        db, skip=skip, limit=page_size, type=type, category=category
    )
    
    product_responses = [_product_to_response(p) for p in products]
    
    return ProductLegacyList(
        total=total,
        page=page,
        page_size=page_size,
        products=product_responses
    )


@router.get("/search", response_model=ProductLegacyList)
def search_products(
    q: str = Query(..., min_length=2, description="Search term"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    Search products by name or description.
    """
    skip = (page - 1) * page_size
    
    products, total = ProductServiceLegacy.search_products(
        db, search_term=q, skip=skip, limit=page_size
    )
    
    product_responses = [_product_to_response(p) for p in products]
    
    return ProductLegacyList(
        total=total,
        page=page,
        page_size=page_size,
        products=product_responses
    )


@router.get("/{product_id}", response_model=ProductLegacyResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a product by ID.
    """
    product = ProductServiceLegacy.get_product(db, product_id)
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found"
        )
    
    return _product_to_response(product)


@router.get("/slug/{slug}", response_model=ProductLegacyResponse)
def get_product_by_slug(
    slug: str,
    db: Session = Depends(get_db)
):
    """
    Get a product by slug (URL-friendly identifier).
    """
    product = ProductServiceLegacy.get_product_by_slug(db, slug)
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with slug '{slug}' not found"
        )
    
    return _product_to_response(product)


@router.get("", response_model=ProductLegacyList)
def list_products(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    type: Optional[str] = Query(None, description="Filter by type"),
    category: Optional[str] = Query(None, description="Filter by category"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_visible: Optional[bool] = Query(None, description="Filter by visibility"),
    billing_type: Optional[str] = Query(None, description="Filter by billing type"),
    db: Session = Depends(get_db)
):
    """
    List all products with filters (admin function).
    
    Unlike /catalog, this shows all products including inactive/hidden ones.
    """
    skip = (page - 1) * page_size
    
    products, total = ProductServiceLegacy.list_products(
        db, 
        skip=skip, 
        limit=page_size, 
        type=type, 
        category=category,
        is_active=is_active,
        is_visible=is_visible,
        billing_type=billing_type
    )
    
    product_responses = [_product_to_response(p) for p in products]
    
    return ProductLegacyList(
        total=total,
        page=page,
        page_size=page_size,
        products=product_responses
    )


@router.patch("/{product_id}", response_model=ProductLegacyResponse)
def update_product(
    product_id: int,
    data: ProductLegacyUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a product (admin only).
    
    Can update: nom, description, category, prix_unitaire, billing_type, 
    features_json, quota_mensuel, is_active, is_visible, requires_approval
    """
    product = ProductServiceLegacy.update_product(db, product_id, data)
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found"
        )
    
    return _product_to_response(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Soft delete a product (admin only).
    
    Sets is_active=False and is_visible=False instead of hard delete.
    """
    deleted = ProductServiceLegacy.delete_product(db, product_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found"
        )
    
    return None
