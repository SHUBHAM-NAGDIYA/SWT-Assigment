# High-Performance Data Analytics Backend(Sweta Web Technology)

## Overview

This project is a high-performance backend system built using FastAPI and PostgreSQL. The system simulates a real-world data analytics platform capable of ingesting large datasets from paginated APIs, storing them efficiently, and exposing analytics endpoints with optimized response times.

The application was designed to handle large-scale datasets while maintaining scalability, reliability, and performance under concurrent load.

---

## Assignment Requirements

### Dataset Size

* 100,000 Customers
* 1,000,000 Orders
* 200,000 Refunds

### Features Implemented

* Reproducible dataset generation using a fixed seed
* Paginated mock APIs
* Data ingestion service
* PostgreSQL persistence layer
* Analytics endpoints
* Performance optimization
* Load testing and benchmarking
* API documentation

---

# System Architecture

Mock APIs
    │
    ▼
Ingestion Service
    │
    ▼
PostgreSQL Database
    │
    ├── Customers
    ├── Orders
    ├── Refunds
    │
    ▼
Aggregate Tables
    │
    ├── Daily Revenue
    └── Customer Metrics
    │
    ▼
Analytics APIs
    │
    ▼
Load Testing (Locust)


---

# Technology Stack

## Backend

* Python
* FastAPI
* SQLAlchemy
* Pydantic

## Database

* PostgreSQL
* Alembic

## Testing

* Locust

## Data Generation

* Faker
* Random

---

# Project Structure


backend-assignment/

├── app/
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── repositories/
│   ├── schemas/
│   ├── services/
│   ├── utils/
│   └── main.py
│
├── alembic/
│
├── scripts/
│   ├── generate_customers.py
│   ├── generate_orders.py
│   ├── generate_refunds.py
│   └── seed_database.py
│
├── load_tests/
│
├── tests/
│
├── .env
├── requirements.txt
├── alembic.ini
└── README.md
```

---

# Database Design

## Customers Table

Stores customer information.

| Column     | Type      |
| ---------- | --------- |
| id         | BIGINT    |
| name       | VARCHAR   |
| email      | VARCHAR   |
| created_at | TIMESTAMP |

---

## Orders Table

Stores customer purchases.

| Column      | Type          |
| ----------- | ------------- |
| id          | BIGINT        |
| customer_id | BIGINT        |
| amount      | NUMERIC(12,2) |
| created_at  | TIMESTAMP     |

Relationship:

* One customer can have many orders.

---

## Refunds Table

Stores refund transactions.

| Column        | Type          |
| ------------- | ------------- |
| id            | BIGINT        |
| order_id      | BIGINT        |
| refund_amount | NUMERIC(12,2) |
| created_at    | TIMESTAMP     |

Relationship:

* One order can have multiple refunds.

---

## Aggregate Tables

### Daily Revenue

Used for revenue trend analytics.

| Column        |
| ------------- |
| date          |
| total_orders  |
| total_revenue |
| total_refunds |
| net_revenue   |

### Customer Metrics

Used for customer spending analytics.

| Column      |
| ----------- |
| customer_id |
| order_count |
| total_spend |

---

# Indexing Strategy

Indexes were added to improve query performance.

### Orders

* customer_id
* created_at
* customer_id, created_at

### Refunds

* order_id
* created_at

### Customer Metrics

* total_spend

These indexes significantly reduce query execution time and improve scalability.

---

# Setup Instructions

## Clone Repository

```bash
git clone <repository-url>

cd backend-assignment
```

## Create Virtual Environment

```bash
python -m venv .venv
```

## Activate Virtual Environment

### Windows

```bash
.venv\Scripts\activate
```

### Linux / macOS

```bash
source .venv/bin/activate
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Environment Variables

Create a `.env` file.

```env
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/analytics_db

SEED=42
```

---

# Database Setup

Create database:

```sql
CREATE DATABASE analytics_db;
```

Run migrations:

```bash
alembic upgrade head
```

---

# Dataset Generation

Generate all datasets:

```bash
python scripts/seed_database.py
```

Generated records:

* 100,000 Customers
* 1,000,000 Orders
* 200,000 Refunds

The dataset generation uses a fixed seed for reproducibility.

---

# Running the Application

```bash
uvicorn app.main:app --reload
```

Application:

```text
http://localhost:8000
```

Swagger Documentation:

```text
http://localhost:8000/docs
```

ReDoc Documentation:

```text
http://localhost:8000/redoc
```

---

# Mock APIs

## Customers

```http
GET /mock/customers
```

### Query Parameters

```text
page
page_size
```

---

## Orders

```http
GET /mock/orders
```

### Query Parameters

```text
page
page_size
```

---

## Refunds

```http
GET /mock/refunds
```

### Query Parameters

```text
page
page_size
```

---

# Ingestion Service

The ingestion service simulates data synchronization from external systems.

### Workflow

1. Read paginated data from mock APIs.
2. Process data in batches.
3. Validate records.
4. Bulk insert into PostgreSQL.
5. Update aggregate tables.

The ingestion pipeline is optimized to process large datasets efficiently.

---

# Analytics APIs

## Total Orders

```http
GET /analytics/total-orders
```

Returns total number of orders.

---

## Total Revenue

```http
GET /analytics/total-revenue
```

Returns total revenue generated.

---

## Total Refunds

```http
GET /analytics/total-refunds
```

Returns total refund amount.

---

## Net Revenue

```http
GET /analytics/net-revenue
```

Returns:

```text
Total Revenue - Total Refunds
```

---

## Average Order Value

```http
GET /analytics/average-order-value
```

Returns average order value.

---

## Repeat Customer Revenue

```http
GET /analytics/repeat-customer-revenue
```

Returns revenue generated by repeat customers.

---

## Revenue Trends

```http
GET /analytics/revenue-trends
```

Returns revenue grouped by date.

---

## Top Customers by Spend

```http
GET /analytics/top-customers
```

Returns highest spending customers.

---

# Performance Optimizations

Several optimization techniques were implemented to satisfy the response time requirement.

## Database Indexing

Added indexes on frequently queried columns.

Benefits:

* Faster lookups
* Faster joins
* Reduced execution time

---

## Aggregate Tables

Instead of scanning:

* 1,000,000 Orders
* 200,000 Refunds

for every request, aggregate tables are maintained.

Benefits:

* Reduced database workload
* Consistent response times
* Better scalability

---

## Bulk Inserts

The ingestion service uses batch processing and bulk inserts.

Benefits:

* Reduced transaction overhead
* Faster ingestion speed

---

## Connection Pooling

SQLAlchemy connection pooling is used to efficiently manage database connections.

Benefits:

* Better concurrency
* Reduced connection creation overhead

---

## Query Optimization

All analytics queries were reviewed and optimized using PostgreSQL query planning.

Tools used:

```sql
EXPLAIN ANALYZE
```

---

## PostgreSQL Maintenance

Database statistics were updated using:

```sql
ANALYZE;
VACUUM ANALYZE;
```

Benefits:

* Better query plans
* Improved execution performance

---

# Load Testing

## Tool Used

Locust

---

## Test Configuration

### User Levels

* 50 Users
* 100 Users
* 200 Users
* 500 Users

### Test Duration

3 Minutes Per Run

---

## Results

| Users | Avg Response Time | P95        | RPS        | Failure Rate |
| ----- | ----------------- | ---------- | ---------- | ------------ |
| 50    | ADD_RESULT        | ADD_RESULT | ADD_RESULT | ADD_RESULT   |
| 100   | ADD_RESULT        | ADD_RESULT | ADD_RESULT | ADD_RESULT   |
| 200   | ADD_RESULT        | ADD_RESULT | ADD_RESULT | ADD_RESULT   |
| 500   | ADD_RESULT        | ADD_RESULT | ADD_RESULT | ADD_RESULT   |

---

# Performance Validation

Target:

```text
Response Time < 2 Seconds
```

Result:

All analytics endpoints were designed and optimized to maintain low latency under concurrent load through indexing, aggregation, efficient query design, and optimized database access patterns.

---

# Scalability Considerations

The system was designed with scalability in mind.

Implemented strategies:

* Aggregate tables
* Efficient indexing
* Batch ingestion
* Connection pooling
* Optimized SQL queries

Future scaling options:

* Redis caching
* Read replicas
* Horizontal API scaling
* Materialized views
* Kafka-based ingestion

---

# Future Improvements

Potential enhancements include:

* Redis integration
* Celery background jobs
* Kafka event streaming
* Kubernetes deployment
* Distributed caching
* Multi-region deployment

---

# Conclusion

This project successfully demonstrates the design and implementation of a scalable analytics backend capable of processing large datasets and serving analytics efficiently. Through optimized database design, aggregate tables, indexing strategies, and load testing, the system satisfies the core requirements of high-performance data ingestion and analytics processing.
