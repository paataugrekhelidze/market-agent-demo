# Market Agent

The project designs an end-to-end AI agent infrastructure that leverages external market data (NYSE) and News headlines. The project is split between solving algorithmic and infrastructural challenges and each phase focuses on one of these tasks:

Phases:
1. Data & DBs
2. MCP Tools
3. Core Agent
4. Orchestration

Algorithmic Tasks (Phase 2 and 3):
- How to extract external data from NYSE and News headlines so it's easily consumable by an agent?
    - NYSE (Structured): Consists of tabular data. Prefect’s FastMCP will be used to define SQL-based tools, allowing the agent to dynamically query structured NYSE tables.
    - News Headlines (Unstructured): Consists of text data requiring semantic search. Various strategies, such as dimensionality reduction, approximate nearest neighbor techniques, keyword matching, reranker, etc. can be incorporated for efficient document retrieval. Some of those techniques will be explored in the project. For simplicity, headlines will be embedded using a fast embedding pipeline and exposed to the agent via a dedicated FastMCP semantic search tool. 
- What components of agentic design should be used?
    - ReAct (reason + act) Framework - iterative loops between: Thought, Action, Observation
        - Use Prefect to handle standard ReAct mechanics and state preservation
    - Guardrails to prevent infinitie loops / non-deterministic behavior and fail gracefully (e.g. max_iterations=5)
    - Ability to recover from a failed state in a multi-stage agentic flow and start from the last successful step (via Prefect tasks)
- what agentic framework/tool to use? why?
    - Prefect / FastMCP
- Reliability, observability, and safety from the algorithmic perspective?
    - JSON format enforcement for all tool outputs
    - LLM tool call validation (possibly at the expense of a higher token consumption)
    - Request timeouts
    - token consumption limits (per tool call, for overall chat history, ...)

Infrastructure (Phase 1 and 4):
- which independent services will be needed to support the application?
    - Data initializer for SQL and Vector DB
        - Start with PostgreSQL to keep it simple
    - A FastAPI instance housing the agent logic and FastMCP tools
- what are the resource considerations for each service?
    - LLM Scaling: Queue Count is a more accurate indicator of GPU saturation than just GPU utilization. With kubernetes, we can hook the Queue count metric to HPA. In a production Kubernetes environment, this metric would drive a Horizontal Pod Autoscaler (HPA) to scale pods and trigger the cluster autoscaler for extra GPU nodes. **Partially implemented** — a named Prefect Global Concurrency Limit (`agent-pipeline`) is auto-created at startup from a configurable env var (`AGENT_CONCURRENCY_LIMIT`). The Prefect UI exposes active slot count and queue depth in real time. Prometheus metrics endpoint and k8s HPA wiring were left out — out of scope for local demo.
- Reliability, observability and safety from the infrastructural perspective?
    - Use Docker healthcheck to halt fastapi containers until the database and vector indexes are completely initialized and healthy. **Implemented** (all services have healthchecks; `agent` depends on `db` healthy + `prefect-server` healthy + `init-db` completed successfully)
    - Launch the local Prefect UI dashboard directly within the Docker Compose environment. **Implemented** (`prefect-server` service exposed on port 4200)

### Towards Production
- **Prometheus `/metrics` endpoint**: expose `agent_active_requests` and `agent_queue_depth` as standard Prometheus gauges. Kubernetes can then read queue depth and automatically scale pods up or down.
- **Secrets management**: replace plaintext env vars (`POSTGRES_PASSWORD`, `OPENAI_API_KEY`, etc.) in docker-compose with a secrets backend (k8s Secrets) before moving off local.
- **Persistent Prefect result storage**: the current setup writes Prefect task results to local disk (`PREFECT_RESULTS_PERSIST_BY_DEFAULT=true`). Need a more consistent storage to survive pod restart in k8s. 
- **Work pool**: submitting flows to a Prefect work pool (instead of running them in-process) would decouple the HTTP request lifecycle from the flow execution, allow the API to return a run ID immediately, and enable horizontal scaling of workers independently of the API layer. WOrk pools enable more flexibility to control queue priorities and concurrency.

From Prefect [Documentation](https://docs.prefect.io/v3/concepts/work-pools#precise-control-with-priority-and-concurrency):

- *a "low" queue with priority 10 and no concurrency limit*
- *a "high" queue with priority 5 and a concurrency limit of 3*
- *a "critical" queue with priority 1 and a concurrency limit of 1*



### Instructions

In order to run the application, OPENAI_API_KEY must be provided inside .env file, other parameters are optional

```bash
# start the environment
docker compose up -d

# wait for the containers to build and start running (takes a few mins...)

# once all the containers are up and healthy, an agent endpoint will be exposed on localhost at port 8080
# use test_agent.py to test the application
# options: --max-tasks (Max pipeline steps, default: 5), --url (default: http://localhost:8080)
python test_agent.py "Find top 3 companies with 8% stock moves in 2014. See if the there are news explaining this behavior."

# to test multiple/concurrent calls
python test_concurrent_agent.py

# to track application logs
docker logs agent_runner --follow

# Prefect UI exposed at http://localhost:4200
```