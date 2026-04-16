# Azure OpenAI API Cost Estimation & Cold Start Optimization

## 1. Current Application Configuration

| Parameter | Current Value |
|---|---|
| **Chat Model** | `gpt-35-turbo-16k` (deployment: `turbo16k`) |
| **Embedding Model** | `text-embedding-ada-002` |
| **Max Output Tokens** | 1,000 |
| **Temperature** | 0 (deterministic) |
| **Streaming** | Enabled |
| **Answer Caching** | Enabled (90% similarity threshold) |
| **App Service SKU** | B1 (Basic) |
| **Cosmos DB** | Serverless / Provisioned |
| **Azure AI Search** | Standard tier (if RAG enabled) |
| **Provisioned TPM** | 30K tokens/min (chat), 30K tokens/min (embedding) |

---

## 2. Assumptions for Cost Estimation

| Assumption | Value |
|---|---|
| Messages per user per month | 25 |
| Avg input tokens per request (system prompt + user msg + history) | 500 |
| Avg output tokens per request | 400 |
| Embedding tokens per request (if RAG enabled) | 100 |
| Cache hit rate (reduces API calls) | ~15-20% |
| Title generation calls (per conversation) | 1 call, 64 max tokens |
| Avg conversations per user per month | 5 (5 msgs each) |

### Token Volume by User Scale

| Users/Month | Messages/Month | Input Tokens | Output Tokens | Embedding Tokens |
|---|---|---|---|---|
| **300** | 7,500 | 3.75M | 3.0M | 0.75M |
| **1,000** | 25,000 | 12.5M | 10.0M | 2.5M |
| **5,000** | 125,000 | 62.5M | 50.0M | 12.5M |
| **10,000** | 250,000 | 125.0M | 100.0M | 25.0M |
| **20,000** | 500,000 | 250.0M | 200.0M | 50.0M |

> **Note:** With ~15-20% cache hit rate, effective API call volume is reduced proportionally. The estimates below use the **full (uncached)** volume for conservative worst-case pricing.

---

## 3. Azure OpenAI Model Pricing (Per 1M Tokens, Standard)

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Context Window |
|---|---|---|---|
| **GPT-4** (8K) | $30.00 | $60.00 | 8,192 |
| **GPT-4** (32K) | $60.00 | $120.00 | 32,768 |
| **GPT-4 Turbo** | $10.00 | $30.00 | 128,000 |
| **GPT-4o** | $2.50 | $10.00 | 128,000 |
| **GPT-4o-mini** | $0.15 | $0.60 | 128,000 |
| **GPT-3.5-Turbo-16K** (current) | $0.50 | $1.50 | 16,384 |
| **text-embedding-ada-002** | $0.10 | N/A | 8,191 |

> Prices reflect Azure OpenAI standard (pay-as-you-go) rates. Provisioned Throughput Units (PTU) pricing differs. Check [Azure OpenAI pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/) for the latest rates.

---

## 4. Monthly API Cost Estimates by Model

### GPT-4 (8K Context)

| Users | Input Cost | Output Cost | **Total API Cost** |
|---|---|---|---|
| 300 | $112.50 | $180.00 | **$292.50** |
| 1,000 | $375.00 | $600.00 | **$975.00** |
| 5,000 | $1,875.00 | $3,000.00 | **$4,875.00** |
| 10,000 | $3,750.00 | $6,000.00 | **$9,750.00** |
| 20,000 | $7,500.00 | $12,000.00 | **$19,500.00** |

### GPT-4 Turbo (128K Context)

| Users | Input Cost | Output Cost | **Total API Cost** |
|---|---|---|---|
| 300 | $37.50 | $90.00 | **$127.50** |
| 1,000 | $125.00 | $300.00 | **$425.00** |
| 5,000 | $625.00 | $1,500.00 | **$2,125.00** |
| 10,000 | $1,250.00 | $3,000.00 | **$4,250.00** |
| 20,000 | $2,500.00 | $6,000.00 | **$8,500.00** |

### GPT-4o (128K Context) -- Recommended for Quality + Cost Balance

| Users | Input Cost | Output Cost | **Total API Cost** |
|---|---|---|---|
| 300 | $9.38 | $30.00 | **$39.38** |
| 1,000 | $31.25 | $100.00 | **$131.25** |
| 5,000 | $156.25 | $500.00 | **$656.25** |
| 10,000 | $312.50 | $1,000.00 | **$1,312.50** |
| 20,000 | $625.00 | $2,000.00 | **$2,625.00** |

### GPT-4o-mini (128K Context) -- Best Budget Option

| Users | Input Cost | Output Cost | **Total API Cost** |
|---|---|---|---|
| 300 | $0.56 | $1.80 | **$2.36** |
| 1,000 | $1.88 | $6.00 | **$7.88** |
| 5,000 | $9.38 | $30.00 | **$39.38** |
| 10,000 | $18.75 | $60.00 | **$78.75** |
| 20,000 | $37.50 | $120.00 | **$157.50** |

### GPT-3.5-Turbo-16K (Current Default)

| Users | Input Cost | Output Cost | **Total API Cost** |
|---|---|---|---|
| 300 | $1.88 | $4.50 | **$6.38** |
| 1,000 | $6.25 | $15.00 | **$21.25** |
| 5,000 | $31.25 | $75.00 | **$106.25** |
| 10,000 | $62.50 | $150.00 | **$212.50** |
| 20,000 | $125.00 | $300.00 | **$425.00** |

---

## 5. Embedding Costs (text-embedding-ada-002, $0.10/1M tokens)

| Users | Embedding Tokens | **Embedding Cost** |
|---|---|---|
| 300 | 0.75M | **$0.08** |
| 1,000 | 2.5M | **$0.25** |
| 5,000 | 12.5M | **$1.25** |
| 10,000 | 25.0M | **$2.50** |
| 20,000 | 50.0M | **$5.00** |

> Embedding costs are negligible relative to chat completion costs.

---

## 6. Infrastructure Costs (Monthly)

Infrastructure costs scale with the number of concurrent users, not total monthly users. Assume ~5-10% of monthly users are active concurrently during peak hours.

| Component | 300 Users | 1,000-5,000 Users | 10,000-20,000 Users |
|---|---|---|---|
| **App Service Plan** | B1: ~$13 | S1: ~$70 / P1v2: ~$80 | P1v3: ~$110 (2-3 instances: $220-$330) |
| **Azure Cosmos DB** | Serverless: ~$5-10 | 400 RU/s: ~$24 | 1000+ RU/s: ~$60-200 |
| **Azure AI Search** (if RAG) | Standard: ~$250 | Standard: ~$250 | Standard S2: ~$500 |
| **Application Insights** | Free tier | Free/$2.30/GB | ~$10-50 |
| **Azure OpenAI Resource** | S0 (no base cost) | S0 | S0 |
| **Infra Subtotal** | **~$18-278** | **~$96-426** | **~$400-1,080** |

> Azure AI Search is the single largest infrastructure cost. If RAG is not used, infrastructure costs drop substantially.

---

## 7. Total Estimated Monthly Cost (API + Infrastructure)

### With RAG (Azure AI Search enabled)

| Users | GPT-4 | GPT-4 Turbo | GPT-4o | GPT-4o-mini | GPT-3.5-Turbo |
|---|---|---|---|---|---|
| **300** | $571 | $406 | $318 | $281 | $285 |
| **1,000** | $1,301 | $751 | $457 | $334 | $347 |
| **5,000** | $5,301 | $2,551 | $1,083 | $466 | $533 |
| **10,000** | $10,490 | $4,990 | $2,053 | $819 | $953 |
| **20,000** | $20,580 | $9,580 | $3,705 | $1,238 | $1,505 |

### Without RAG (No Azure AI Search)

| Users | GPT-4 | GPT-4 Turbo | GPT-4o | GPT-4o-mini | GPT-3.5-Turbo |
|---|---|---|---|---|---|
| **300** | $311 | $146 | $58 | $21 | $25 |
| **1,000** | $1,071 | $521 | $227 | $104 | $117 |
| **5,000** | $4,971 | $2,221 | $752 | $135 | $202 |
| **10,000** | $10,150 | $4,650 | $1,713 | $479 | $613 |
| **20,000** | $20,080 | $9,080 | $3,205 | $738 | $1,005 |

---

## 8. Model Comparison & Recommendation

| Model | Quality | Cost Efficiency | Best For |
|---|---|---|---|
| **GPT-4 (8K)** | Highest reasoning | Most expensive | Complex advisory, legal, financial analysis |
| **GPT-4 Turbo** | Near GPT-4 quality | ~56% cheaper than GPT-4 | Complex tasks with long context |
| **GPT-4o** | Excellent, multimodal | ~87% cheaper than GPT-4 | **Best quality-to-cost ratio for most apps** |
| **GPT-4o-mini** | Good for simple tasks | ~99% cheaper than GPT-4 | High-volume, simple Q&A, chatbots |
| **GPT-3.5-Turbo** | Adequate, aging model | Very cheap | Legacy support, simple conversations |

### Recommendation

For the MilVet Navigator use case (conversational assistant with RAG):

- **300-1,000 users:** Start with **GPT-4o** -- excellent quality at ~$320-460/month with RAG. Upgrade to GPT-4 Turbo only if users report quality gaps in complex reasoning.
- **1,000-5,000 users:** **GPT-4o** remains cost-effective at ~$460-1,080/month. Consider **GPT-4o-mini** for non-critical interactions (FAQs, greetings).
- **5,000-20,000 users:** Use a **tiered approach** -- route simple queries to GPT-4o-mini and complex advisory queries to GPT-4o. This can reduce costs by 40-60%.

---

## 9. Cold Start Analysis & Improvements

### Current Cold Start Timeline

| Phase | Duration | Description |
|---|---|---|
| Container pull & start | ~1-3s | Docker image boot on App Service |
| Python interpreter + imports | ~2-5s | Loading dependencies (azure-identity, openai, quart, etc.) |
| CosmosDB connection init | ~1-3s | `init_cosmosdb_client()` in `@app.before_serving` |
| First request (OpenAI client init) | ~1-2s | Lazy-initialized on first `/conversation` call |
| **Total cold start** | **~5-13s** | User experiences delay on first request |

### Current Cold Start Mitigations Already in Place

1. **Multi-stage Docker build** -- frontend pre-built, no runtime compilation
2. **Async framework (Quart + Uvicorn)** -- handles concurrent requests efficiently
3. **`alwaysOn: true`** in Bicep -- prevents App Service from sleeping (requires Standard+ tier)
4. **Gunicorn worker recycling** -- `max_requests=1000` prevents memory leaks

### Recommended Improvements

#### A. Pre-warm the Azure OpenAI Client at Startup (High Impact, Easy)

Currently, the Azure OpenAI client is lazily initialized on the first request. Move initialization to the `@app.before_serving` hook.

```python
# In app.py - @app.before_serving hook
@app.before_serving
async def init():
    # Existing: CosmosDB init
    app.cosmos_conversation_client = await init_cosmosdb_client()
    cosmos_db_ready.set()

    # ADD: Pre-warm OpenAI client
    app.openai_client = await init_openai_client()

    # ADD: Send a lightweight warm-up request
    try:
        await app.openai_client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
    except Exception:
        pass  # Warm-up failure is non-critical
```

**Impact:** Eliminates ~1-2s delay on the first user request.

#### B. Add a Health Check Endpoint (High Impact, Easy)

```python
@bp.route("/health", methods=["GET"])
async def health_check():
    return jsonify({"status": "healthy"}), 200
```

Then set in Bicep:
```bicep
healthCheckPath: '/health'
```

**Impact:** Azure App Service will route traffic only to healthy instances, preventing users from hitting cold containers.

#### C. Optimize the Docker Image (Medium Impact, Moderate)

Current image uses `python:3.11-alpine` which is good, but can be improved:

```dockerfile
# Pre-compile Python bytecode during build
RUN pip install --no-cache-dir -r /usr/src/app/requirements.txt \
    && python -m compileall /usr/local/lib/python3.11/ -q \
    && python -m compileall /usr/src/app/ -q \
    && rm -rf /root/.cache

# Remove build deps after install
RUN apk del .build-deps
```

**Impact:** Reduces Python import time by ~0.5-1s (bytecode is pre-compiled, not compiled at import time).

#### D. Use Deployment Slots for Zero-Downtime Deployments (High Impact, Moderate)

```bicep
// Add a staging slot
resource stagingSlot 'Microsoft.Web/sites/slots@2022-03-01' = {
  parent: appService
  name: 'staging'
  location: location
  properties: {
    serverFarmId: appServicePlanId
    siteConfig: appService.properties.siteConfig
  }
}
```

Deploy to the staging slot first, let it warm up, then swap to production. Users never experience cold start.

**Impact:** Eliminates cold starts during deployments entirely. Requires Standard tier or higher.

#### E. Upgrade App Service Plan for High User Counts (High Impact)

| User Range | Recommended SKU | Why |
|---|---|---|
| 300 | B1 ($13/mo) | Sufficient, but **no deployment slots** and alwaysOn may not work reliably |
| 1,000-5,000 | S1 ($70/mo) or P1v2 ($80/mo) | Deployment slots, reliable alwaysOn, auto-scale |
| 5,000-10,000 | P1v3 ($110/mo, 2 instances) | More CPU/RAM, faster cold starts |
| 10,000-20,000 | P1v3 ($110/mo, 3+ instances) with auto-scale | Handle burst traffic |

#### F. Reduce Python Dependencies (Low Impact, Easy)

Audit `requirements.txt` and remove unused packages. Each import adds to cold start time. Consider:
- Remove `azure-storage-blob` if not using blob storage
- Remove `azure-search-documents` if not using AI Search
- Remove data-prep dependencies from production image

#### G. Consider Azure Container Apps (Alternative Architecture)

For 10,000+ users, Azure Container Apps offers:
- **Min replicas > 0**: Always-warm containers
- **Scale-to-zero with fast startup**: KEDA-based autoscaling
- **Built-in revision management**: Blue-green deployments
- **Cost model**: Per-second billing (can be cheaper at scale)

```yaml
# container-app config example
scale:
  minReplicas: 1         # Always keep 1 warm
  maxReplicas: 10
  rules:
    - name: http-scaling
      http:
        metadata:
          concurrentRequests: "50"
```

#### H. Connection Pooling for Cosmos DB (Medium Impact)

Ensure the Cosmos DB client is configured with connection pooling:

```python
# In cosmosdbservice.py
self.cosmosdb_client = CosmosClient(
    self.cosmosdb_endpoint,
    credential=credential,
    connection_config={
        "max_connection_pool_size": 100,
        "retry_on_status_codes": [429, 503],
    }
)
```

---

## 10. Cold Start Improvement Priority Matrix

| Improvement | Impact | Effort | Priority |
|---|---|---|---|
| Pre-warm OpenAI client at startup | High | Low | **P0 - Do First** |
| Add health check endpoint | High | Low | **P0 - Do First** |
| Use deployment slots | High | Medium | **P1 - Do Soon** |
| Pre-compile Python bytecode in Docker | Medium | Low | **P1 - Do Soon** |
| Upgrade App Service SKU (scale-appropriate) | High | Low (config) | **P1 - Do Soon** |
| Connection pooling for Cosmos DB | Medium | Low | **P2 - Nice to Have** |
| Trim unused dependencies | Low | Low | **P2 - Nice to Have** |
| Migrate to Container Apps (10K+ users) | High | High | **P3 - Future** |

---

## 11. Cost Optimization Strategies

1. **Leverage the existing answer cache** -- The app already caches similar answers (90% threshold). Monitor cache hit rates and consider lowering the threshold to 0.85 for higher hit rates.

2. **Implement conversation history trimming** -- Currently, full history is sent with each request. Add a token budget (e.g., 4,000 input tokens) and trim older messages to reduce input token costs.

3. **Use model routing** -- Route simple questions (greetings, FAQs) to GPT-4o-mini and complex ones to GPT-4o. This can reduce API costs by 40-60%.

4. **Reduce max output tokens** -- The current 1,000 token limit is conservative. The system prompt already instructs concise responses (120 words ~ 160 tokens). Consider lowering to 500 for most interactions.

5. **Provisioned Throughput (PTU)** -- For 10,000+ users with predictable traffic, Azure PTU pricing can be 30-50% cheaper than pay-as-you-go. Requires capacity planning.

6. **Monitor and alert** -- Use Application Insights to track token usage, cache hit rates, and costs per user to identify optimization opportunities.
