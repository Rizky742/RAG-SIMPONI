-- ============================================================
-- Example Schema: TikTok Shop & Shopee Central Database
-- Run this to set up a sample database for testing
-- ============================================================

-- ── Data Sources ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_sources (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE,  -- 'tiktok_shop' | 'shopee'
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE data_sources IS 'E-commerce platform data sources';

INSERT INTO data_sources (name, description) VALUES
    ('tiktok_shop', 'TikTok Shop platform orders and products'),
    ('shopee',      'Shopee marketplace orders and products')
ON CONFLICT DO NOTHING;


-- ── Products ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id          SERIAL PRIMARY KEY,
    source_id   INT NOT NULL REFERENCES data_sources(id),
    sku         VARCHAR(100) NOT NULL,
    name        VARCHAR(500) NOT NULL,
    category    VARCHAR(200),
    brand       VARCHAR(200),
    price       NUMERIC(15, 2) NOT NULL,
    stock       INT DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_id, sku)
);

COMMENT ON TABLE products IS 'Product catalog from TikTok Shop and Shopee';
COMMENT ON COLUMN products.price IS 'Price in IDR (Indonesian Rupiah)';


-- ── Customers ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id          SERIAL PRIMARY KEY,
    source_id   INT NOT NULL REFERENCES data_sources(id),
    external_id VARCHAR(100) NOT NULL,  -- Platform-specific customer ID
    name        VARCHAR(300),
    email       VARCHAR(300),
    city        VARCHAR(200),
    province    VARCHAR(200),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_id, external_id)
);

COMMENT ON TABLE customers IS 'Customers from TikTok Shop and Shopee';


-- ── Orders ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    source_id       INT NOT NULL REFERENCES data_sources(id),
    order_number    VARCHAR(100) NOT NULL,
    customer_id     INT REFERENCES customers(id),
    status          VARCHAR(50) NOT NULL,  -- 'pending','processing','shipped','delivered','cancelled','returned'
    total_amount    NUMERIC(15, 2) NOT NULL,
    discount_amount NUMERIC(15, 2) DEFAULT 0,
    shipping_fee    NUMERIC(15, 2) DEFAULT 0,
    payment_method  VARCHAR(100),
    ordered_at      TIMESTAMPTZ NOT NULL,
    shipped_at      TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_id, order_number)
);

COMMENT ON TABLE orders IS 'Orders from TikTok Shop and Shopee';
COMMENT ON COLUMN orders.total_amount IS 'Total order value in IDR';
COMMENT ON COLUMN orders.status IS 'pending | processing | shipped | delivered | cancelled | returned';


-- ── Order Items ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INT NOT NULL REFERENCES products(id),
    quantity    INT NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(15, 2) NOT NULL,
    subtotal    NUMERIC(15, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

COMMENT ON TABLE order_items IS 'Line items within each order';


-- ── Indexes ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_orders_source      ON orders (source_id);
CREATE INDEX IF NOT EXISTS idx_orders_status      ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_ordered_at  ON orders (ordered_at);
CREATE INDEX IF NOT EXISTS idx_products_source    ON products (source_id);
CREATE INDEX IF NOT EXISTS idx_products_category  ON products (category);
CREATE INDEX IF NOT EXISTS idx_order_items_order  ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_customers_source   ON customers (source_id);
