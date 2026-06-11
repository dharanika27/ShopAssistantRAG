-- ShopAssistantRAG — MySQL product schema (E2-S1)
-- Idempotent: CREATE TABLE IF NOT EXISTS; indexes declared inline so the whole
-- script is safe to run repeatedly (AC-3). Targets MySQL 8 (AC-5).

CREATE TABLE IF NOT EXISTS products (
  product_id   VARCHAR(64)   NOT NULL,
  name         VARCHAR(255)  NOT NULL,
  description  TEXT          NULL,
  brand        VARCHAR(128)  NULL,
  category     VARCHAR(32)   NOT NULL,
  gender       VARCHAR(16)   NULL,
  color        VARCHAR(64)   NULL,
  price        DECIMAL(10,2) NOT NULL,
  image_url    VARCHAR(1024) NULL,
  stock        INT           NOT NULL DEFAULT 0,
  tags         JSON          NULL,
  PRIMARY KEY (product_id),
  KEY idx_products_category (category),
  KEY idx_products_brand    (brand),
  KEY idx_products_gender   (gender),
  KEY idx_products_color    (color),
  KEY idx_products_price    (price),
  CONSTRAINT chk_category CHECK (category IN ('Shoes','Clothing','Accessories','Sportswear','Bags')),
  CONSTRAINT chk_gender   CHECK (gender IS NULL OR gender IN ('Men','Women','Unisex','Kids')),
  CONSTRAINT chk_price    CHECK (price >= 0),
  CONSTRAINT chk_stock    CHECK (stock >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
