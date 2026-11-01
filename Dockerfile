FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY mesh ./mesh
COPY agents ./agents
COPY apps ./apps
COPY mcp_servers ./mcp_servers
# streamlit is included so the ui profile works from the same image;
# the agent/MCP services do not use it.
RUN pip install --no-cache-dir fastapi uvicorn pydantic httpx yfinance streamlit langchain-core langchain-openai mcp
EXPOSE 8000
CMD ["python", "-c", "print('Set command in docker-compose.yml')"]
