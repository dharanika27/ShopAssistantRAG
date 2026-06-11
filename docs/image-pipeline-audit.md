# Image Pipeline Audit — Evidence Report

**Date:** 2026-06-12
**Scope:** End-to-end image trace for **P1001 — Nike Revolution 6** (a shoe),
plus a residual `picsum.photos` scan across CSV, MySQL, API responses, and
frontend state. Audit only — no code was modified.

## P1001 `image_url` at each layer

| # | Layer | Source of truth | `image_url` value | Method |
|---|-------|-----------------|-------------------|--------|
| 1 | CSV | `data/products.csv` | `https://loremflickr.com/600/600/shoes?lock=1001` | parsed row P1001 |
| 2 | MySQL | Docker `shopassistant.products` | `https://loremflickr.com/600/600/shoes?lock=1001` | `SELECT image_url WHERE product_id='P1001'` |
| 3 | API | `GET /api/products` and `POST /api/chat` | `https://loremflickr.com/600/600/shoes?lock=1001` | live responses |
| 4 | ProductView mapping | `frontend/api_client.py:223` | pass-through `image_url=_optional_str(data.get("image_url"))` (field declared `:54`) | code |
| 5 | Render | `frontend/components/product_card.py:51` | `st.image(image_source_for(product.image_url, product.category), …)`; live resolver returned **PASSTHROUGH** → renders `…/shoes?lock=1001` | code + runtime probe in container |

The value is identical and correct (`shoes?lock=1001`) at every layer, and the
running UI resolves it to passthrough (the real shoe image, not a fallback).

## Residual `picsum.photos` scan

| Location | Result |
|----------|--------|
| CSV (`data/products.csv`) | 0 occurrences |
| MySQL (`image_url LIKE '%picsum%'`) | 0 rows |
| API (`GET /api/products`, all 30) | 0 products with picsum; all 30 are `loremflickr` |
| API (`POST /api/chat` shoe query) | 0 picsum |
| Source/config repo-wide (`*.py/.csv/.md/.json/.yml/.txt/.example`) | none |
| Running frontend container (`/app/frontend`) | none baked in |

**Conclusion:** no `picsum.photos` URLs exist anywhere in the live pipeline
(CSV, MySQL, API responses, frontend code, or the running container). Nothing to
fix.

## Notes

- Pinecone stores no image field (only `brand/category/color/gender/price`), so
  it is structurally incapable of carrying an image value.
- Layer 5 behavior: if a `loremflickr` URL were ever unreachable, the resolver
  (`frontend/components/placeholders.image_source_for`) substitutes the category
  placeholder (shoe), never a picsum URL.
- The string `picsum` may still appear only in git history (original commits);
  it does not affect the live pipeline.

**Verdict:** image pipeline is clean and consistent end-to-end; zero residual
picsum references. No fix required.
