# 🤖 Text-to-SQL Chatbot API

RAG Chatbot yang menggunakan teknik **Text-to-SQL** dengan PostgreSQL, FastAPI, dan OpenAI (GPT-5.4 mini).

Arsitektur mengikuti diagram berikut:
```
Data Layer (TikTok Shop + Shopee)
    → Central PostgreSQL Database
        → Schema Understanding Layer
            → Text-to-SQL Processing Layer (LLM)
                → SQL Validation & Security Check
                    → Database Execution Layer
                        → Generation Layer (LLM Narration)
                            → Response ke User
```

---

## 📁 Struktur Project

```
text2sql-chatbot/
├── main.py                  # FastAPI app entry point
├── requirements.txt
├── .env.example             # Contoh konfigurasi environment
├── schema_example.sql       # Contoh schema PostgreSQL (TikTok Shop + Shopee)
└── app/
    ├── config.py            # Konfigurasi & settings
    ├── database.py          # Koneksi async PostgreSQL (SQLAlchemy)
    ├── schema_layer.py      # Schema Understanding Layer
    ├── llm_service.py       # LLM calls (Text-to-SQL & Narration)
    ├── sql_validator.py     # SQL Validation & Security Check
    ├── db_executor.py       # Database Execution Layer
    ├── models.py            # Pydantic request/response models
    └── routers/
        ├── chat.py          # POST /api/v1/chat  ← pipeline utama
        └── schema.py        # GET  /api/v1/schema
```

---

## 🚀 Setup & Instalasi

### 1. Clone & Install Dependencies

```bash
cd text2sql-chatbot
pip install -r requirements.txt
```

### 2. Konfigurasi Environment

```bash
cp .env.example .env
```

Edit `.env`:
```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/central_db
OPENAI_API_KEY=sk-xxxx
LLM_MODEL=gpt-5.4-mini
MAX_ROWS_RETURNED=500
SQL_TIMEOUT_SECONDS=30
```

### 3. Setup Database PostgreSQL

```bash
# Buat database
createdb central_db

# Jalankan contoh schema (opsional, untuk testing)
psql -d central_db -f schema_example.sql
```

### 4. Jalankan Server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs tersedia di: http://localhost:8000/docs

---

## 💬 Contoh Penggunaan

### Chat Endpoint

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Berapa total pendapatan dari TikTok Shop bulan ini?",
    "show_sql": true
  }'
```

**Response:**
```json
{
  "answer": "Total pendapatan dari TikTok Shop bulan ini adalah Rp 125.450.000 dari 342 pesanan yang berhasil diselesaikan.",
  "sql_query": "SELECT SUM(total_amount) FROM orders o JOIN data_sources ds ON o.source_id = ds.id WHERE ds.name = 'tiktok_shop' AND DATE_TRUNC('month', ordered_at) = DATE_TRUNC('month', NOW()) AND status = 'delivered'",
  "row_count": 1,
  "source_tables": ["orders", "data_sources"]
}
```

### Multi-turn Conversation

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Bandingkan dengan bulan lalu",
    "history": [
      {"role": "user", "content": "Berapa total pendapatan dari TikTok Shop bulan ini?"},
      {"role": "assistant", "content": "Total pendapatan bulan ini adalah Rp 125.450.000..."}
    ]
  }'
```

### Schema Inspection

```bash
# Lihat semua tabel
curl http://localhost:8000/api/v1/schema/tables

# Refresh schema cache
curl -X POST http://localhost:8000/api/v1/schema/refresh
```

---

## 🔒 Keamanan SQL

Sistem memiliki lapisan validasi yang memblokir query berbahaya:
- Hanya `SELECT` yang diizinkan (no INSERT/UPDATE/DELETE/DROP)
- Deteksi SQL injection patterns
- Timeout query (default 30 detik)
- Limit jumlah baris (default 500 rows)
- Blokir multiple statements (semicolon stacking)

---

## 🔧 Konfigurasi Lanjutan

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `DATABASE_URL` | - | PostgreSQL async connection string |
| `OPENAI_API_KEY` | - | API key dari platform.openai.com |
| `MAX_ROWS_RETURNED` | 500 | Batas maksimal baris query |
| `SQL_TIMEOUT_SECONDS` | 30 | Timeout eksekusi query (detik) |
| `LLM_MODEL` | gpt-5.4-mini | Model OpenAI (gpt-5.4-mini / gpt-5.5 / gpt-5-mini) |
| `APP_ENV` | development | `development` atau `production` |
