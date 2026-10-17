import re

# canonical display name -> aliases (plain text, matched case-insensitively with symbol-aware boundaries)
SKILL_ALIASES: dict[str, list[str]] = {
    "TypeScript": ["typescript"],
    "JavaScript": ["javascript", "es6"],
    "Python": ["python"],
    "Java": ["java"],
    "C#": ["c#", "c sharp", "csharp"],
    ".NET": [".net", "dotnet", "asp.net", ".net core", "c#.net", "vb.net"],
    "C++": ["c++"],
    "Go": ["golang"],
    "Rust": ["rust"],
    "Kotlin": ["kotlin"],
    "Swift": ["swiftui", "swift developer", "ios swift"],
    "PHP": ["php"],
    "Ruby": ["ruby", "ruby on rails"],
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "Vue": ["vue", "vue.js", "vuejs"],
    "Angular": ["angular"],
    "Redux": ["redux"],
    "Node.js": ["node.js", "nodejs"],
    "NestJS": ["nestjs", "nest.js"],
    "Spring": ["spring boot", "spring framework", "spring mvc"],
    "Django": ["django"],
    "FastAPI": ["fastapi"],
    "Flask": ["flask"],
    "HTML/CSS": ["html", "css", "html5", "css3"],
    "Tailwind": ["tailwind", "tailwindcss"],
    "SQL": ["sql", "t-sql", "tsql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "SQL Server": ["sql server", "mssql", "ms sql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "GraphQL": ["graphql"],
    "REST APIs": ["rest api", "rest apis", "restful"],
    "Microservices": ["microservices", "microservice", "micro-services"],
    "RabbitMQ": ["rabbitmq"],
    "Kafka": ["kafka"],
    "gRPC": ["grpc"],
    "Azure": ["azure"],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "github actions", "azure devops", "jenkins", "gitlab ci"],
    "Linux": ["linux"],
    "Git": ["git"],
    "Jest": ["jest"],
    "Playwright": ["playwright"],
    "Selenium": ["selenium"],
    "LLM": ["llm", "llms", "large language model", "large language models"],
    "RAG": ["rag", "retrieval-augmented", "retrieval augmented"],
    "AI Agents": ["ai agent", "ai agents", "agentic"],
    "Prompt Engineering": ["prompt engineering"],
    "Ollama": ["ollama"],
    "OpenAI": ["openai"],
    "LangChain": ["langchain"],
    "pgvector": ["pgvector"],
    "Machine Learning": ["machine learning"],
    "PowerShell": ["powershell"],
}


def _compile(alias: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_.#+])" + re.escape(alias) + r"(?![A-Za-z0-9_#+])", re.IGNORECASE)


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, _compile(alias)) for name, aliases in SKILL_ALIASES.items() for alias in aliases
]


def extract_skills(text: str) -> set[str]:
    found: set[str] = set()
    for name, pattern in _PATTERNS:
        if name not in found and pattern.search(text):
            found.add(name)
    return found
