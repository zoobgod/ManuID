from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import crud
from app.bootstrap import load_source_catalog, seed_default_companies, seed_default_product_types
from app.config import Settings, get_settings
from app.database import get_db, init_db, SessionLocal
from app.schemas import (
    CompanyRead,
    IngestURLRequest,
    IngestURLResponse,
    ProductTypeRead,
    SearchVendorsRequest,
    SearchVendorsResponse,
    VendorDetailResponse,
    VerifyVendorRequest,
)
from app.security import verify_api_key
from app.services.ingestion import ingest_from_url


def _company_to_schema(company, score: float | None = None, reasons: list[str] | None = None) -> CompanyRead:
    payload = CompanyRead.model_validate(company)
    payload.score = score
    payload.score_reasons = reasons
    return payload


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_default_product_types(db)
        seed_default_companies(db)
        crud.seed_source_catalog(db, load_source_catalog())
    finally:
        db.close()
    yield


app = FastAPI(
    title="ManuID API",
    version="1.0.0",
    description="Procurement intelligence API for pharmacopeia-related product suppliers.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/product-types", response_model=list[ProductTypeRead], dependencies=[Depends(verify_api_key)])
def list_product_types(
    q: str | None = Query(default=None),
    pharmacopeia: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return crud.list_product_types(db, q=q, pharmacopeia=pharmacopeia, limit=limit)


@app.post(
    "/v1/search/vendors",
    response_model=SearchVendorsResponse,
    dependencies=[Depends(verify_api_key)],
)
def search_vendors(payload: SearchVendorsRequest, db: Session = Depends(get_db)):
    product_type, normalized_query, rows = crud.search_vendors(db, payload)
    companies = [_company_to_schema(company, score=score, reasons=reasons) for company, score, reasons in rows]
    product_type_schema = ProductTypeRead.model_validate(product_type) if product_type else None
    return SearchVendorsResponse(product_type=product_type_schema, normalized_query=normalized_query, data=companies)


@app.post(
    "/v1/ingestion/url",
    response_model=IngestURLResponse,
    dependencies=[Depends(verify_api_key)],
)
async def ingest_url(payload: IngestURLRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return await ingest_from_url(db, settings, payload)


@app.get(
    "/v1/vendors/{vendor_id}",
    response_model=VendorDetailResponse,
    dependencies=[Depends(verify_api_key)],
)
def vendor_detail(vendor_id: int, db: Session = Depends(get_db)):
    company, product_types, evidence_urls = crud.get_vendor_detail(db, vendor_id)
    if not company:
        raise HTTPException(status_code=404, detail="Vendor not found")

    return VendorDetailResponse(
        vendor=CompanyRead.model_validate(company),
        product_types=[ProductTypeRead.model_validate(item) for item in product_types],
        evidence_urls=evidence_urls,
    )


@app.post(
    "/v1/vendors/{vendor_id}/verify",
    response_model=CompanyRead,
    dependencies=[Depends(verify_api_key)],
)
def verify_vendor(vendor_id: int, payload: VerifyVendorRequest, db: Session = Depends(get_db)):
    company = crud.verify_vendor(db, vendor_id, payload)
    if not company:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return CompanyRead.model_validate(company)


@app.get(
    "/v1/source-catalog",
    dependencies=[Depends(verify_api_key)],
)
def source_catalog() -> dict[str, list[dict]]:
    return {"data": load_source_catalog()}
