# Search Quality Evaluation

## Overview

This document defines evaluation queries for testing Korean video search quality.
Use these queries to validate changes to the search pipeline.

## Test Queries

### 1. Product Announcement

| Query | Expected Behavior |
|-------|-------------------|
| `신제품 출시` | Segments about new product launches should rank higher |
| `할인 행사` | Discount/sale announcements should appear first |
| `무료 배송` | Free shipping mentions should be prioritized |

### 2. Technical Terms (Mixed Korean/English)

| Query | Expected Behavior |
|-------|-------------------|
| `API 연동` | Technical integration discussions should rank first |
| `SDK 설치 방법` | SDK installation tutorials should appear |
| `React 컴포넌트` | React component explanations should rank higher |

### 3. Short Queries (Phrase Matching)

| Query | Expected Behavior |
|-------|-------------------|
| `세일 기간` | Exact phrase "세일 기간" should boost over scattered terms |
| `사용 방법` | Usage instructions should appear first |
| `주문 취소` | Order cancellation segments prioritized |

### 4. Long-tail Queries

| Query | Expected Behavior |
|-------|-------------------|
| `이번 주 금요일까지 진행하는 특별 할인` | Semantic matching should find relevant content |
| `구매 후 7일 이내 반품 가능한지` | Return policy discussions should rank |

## Quality Metrics

### Primary: Precision@20

For each test query, measure:
- **Relevant results in top 20** / 20

Target: ≥ 0.6 (12+ relevant results in top 20)

### Secondary: Diversity

- **Unique videos in top 20**: Should be ≥ 5 unless one video dominates relevance
- **Diversification penalty rate**: Track how many results were demoted

## Debug Fields

Each result includes debug info for analysis:

```json
{
  "debug": {
    "lexical_rank": 5,
    "lexical_score": 12.34,
    "vector_rank": 3,
    "vector_score": 0.89,
    "lexical_contribution": 0.008,
    "vector_contribution": 0.012,
    "fused_score": 0.020,
    "quality_factor": 0.95,
    "adjusted_score": 0.019,
    "diversification_penalty": false
  }
}
```

### Field Explanations

| Field | Description |
|-------|-------------|
| `lexical_rank` | Position in BM25 results (1-based, null if not found) |
| `lexical_score` | Raw BM25 score from OpenSearch |
| `vector_rank` | Position in kNN results (1-based, null if not found) |
| `vector_score` | Cosine similarity score |
| `lexical_contribution` | `(1-alpha) * RRF(lexical_rank)` |
| `vector_contribution` | `alpha * RRF(vector_rank)` |
| `fused_score` | `lexical_contribution + vector_contribution` |
| `quality_factor` | 0.7-1.0 based on transcript length |
| `adjusted_score` | `fused_score * quality_factor` |
| `diversification_penalty` | True if demoted due to per-video limit |

## Evaluation Process

1. **Before changes**: Run all test queries, record top 20 results
2. **After changes**: Run same queries, compare results
3. **Check regressions**: Ensure previously-good results don't disappear
4. **Measure improvements**: Count newly-correct rankings

## Alpha Tuning Guide

| Alpha | Behavior | Best For |
|-------|----------|----------|
| 0.0 | Pure lexical (BM25) | Exact term matching |
| 0.3 | Lexical-heavy | Known keywords |
| 0.5 | Balanced (default) | General search |
| 0.7 | Vector-heavy | Conceptual queries |
| 1.0 | Pure vector | Semantic similarity |
