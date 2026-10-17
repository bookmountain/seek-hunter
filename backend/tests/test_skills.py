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
