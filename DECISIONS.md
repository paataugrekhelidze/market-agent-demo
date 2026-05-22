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
    - LLM Scaling: Queue Count is a more accurate indicator of GPU saturation than just GPU utilization. With kubernetes, we can hook the Queue count metric to HPA. In a production Kubernetes environment, this metric would drive a Horizontal Pod Autoscaler (HPA) to scale pods and trigger the cluster autoscaler for extra GPU nodes. For this local demo, the system will focus on capturing and exposing this metric via telemetry logs without execution actions.
- Reliability, observability and safety from the infrastructural perspective?
    - Use Docker healthcheck to hault fastapi containers until the database and vector indexes are completely initialized and healthy
    - Launch the local Prefect UI dashboard directly within the Docker Compose environment



