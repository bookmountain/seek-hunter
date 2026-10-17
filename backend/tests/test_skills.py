from seekhunter.skills import extract_skills


def test_extracts_with_aliases_and_symbols():
    text = "We use React.js, Next.js, TypeScript, C# and .NET 8 on Postgres with Docker and k8s."
    assert extract_skills(text) >= {"React", "Next.js", "TypeScript", "C#", ".NET", "PostgreSQL",
                                    "Docker", "Kubernetes"}


def test_does_not_match_inside_words():
    assert "Java" not in extract_skills("JavaScript developer")
    assert "JavaScript" in extract_skills("JavaScript developer")
    assert "Go" not in extract_skills("Go to market")
    assert "React" not in extract_skills("reactive maintenance")


def test_case_insensitive():
    assert "Python" in extract_skills("PYTHON scripting")


def test_bare_node_and_spring_no_longer_match():
    assert "Node.js" not in extract_skills("a node in the network")
    assert "Spring" not in extract_skills("Spring 2026 intake")


def test_csharp_dotnet_combo():
    found = extract_skills("C#.NET developer")
    assert "C#" in found
    assert ".NET" in found


def test_ms_sql_matches_sql_server():
    assert "SQL Server" in extract_skills("MS SQL")


def test_spring_matches_springboot_and_spring_ai():
    assert "Spring" in extract_skills("We use SpringBoot in production")
    assert "Spring" in extract_skills("Experience with Spring AI is a plus")


def test_resume_2026_10_skills():
    text = ("React Native, Expo Router, ASP.NET Core, SignalR, Cloudflare Workers, PostGIS, "
            "LangChain4j, LangGraph4j, MCP, Tool Calling, Prometheus/Grafana, DynamoDB")
    expected = {"React Native", "React", "Expo", ".NET", "SignalR", "Cloudflare", "PostGIS",
                "LangChain", "LangGraph", "MCP", "AI Agents", "Prometheus/Grafana", "DynamoDB"}
    assert extract_skills(text) >= expected
    assert "Expo" not in extract_skills("Visit our careers expo")
