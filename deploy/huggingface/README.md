---
title: TrendScout AI API
emoji: 📈
colorFrom: gray
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# TrendScout AI — API

FastAPI backend for [TrendScout AI](https://github.com/premtheganesh/TrendScout-AI).
Built from the repository's `Dockerfile`; indexes are rebuilt from MongoDB
at boot. Configure these **Space secrets**:

| Secret | Value |
|---|---|
| `MONGODB_URI` | Atlas connection string for a **read-only** user |
| `MONGODB_DB` | `trendscout_ai` |
| `GROQ_API_KEY` | Groq key |
| `ADMIN_TOKEN` | same value the pipeline uses to call `/admin/reload` |
| `CORS_ORIGINS` | `https://<your-vercel-app>.vercel.app` |

`INDEX_DIR=/tmp/index` and `INDEX_BUILD_ON_BOOT=true` are set in the image.
