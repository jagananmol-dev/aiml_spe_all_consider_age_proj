# Synthetic Demo Data Guide

## Purpose

The accompanying JSONL file provides repeatable example records for local development,
dashboard prototyping, search demonstrations, filtering exercises, and automated tests.
Each line is one independent JSON object, so records can be streamed without loading the
entire file into memory.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_id` | string | Stable demo identifier |
| `created_date` | string | ISO 8601 calendar date |
| `category` | string | General support or engineering category |
| `priority` | string | Demonstration priority |
| `status` | string | Demonstration workflow state |
| `channel` | string | Source channel |
| `summary` | string | Synthetic short description |
| `customer_id` | string | Synthetic identifier, not a real person |
| `resolution_minutes` | integer or null | Illustrative resolution duration |
| `is_synthetic` | boolean | Always true for these generated records |

## Suggested exercises

1. Count records by category and priority.
2. Calculate the percentage of records in each status.
3. Filter records by date range.
4. Build a small dashboard with category and status charts.
5. Test behavior when optional values are null.
6. Stream the file one line at a time to avoid unnecessary memory usage.
7. Add schema validation and tests for missing or invalid fields.
8. Compare two generated datasets after changing the generator seed.

## Data quality notes

All records are generated for demonstration. The dates, summaries, identifiers, statuses,
and durations are randomly assigned from predefined options. The records do not describe
real events and must not be used to claim real operational performance.

## Suggested repository placement

Keep sample data under `demo-data/` and documentation under `docs/`. If the project is
unrelated to support analytics, rename the fields and categories to match the application's
actual domain before including this dataset.
