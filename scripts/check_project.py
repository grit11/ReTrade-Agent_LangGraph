"""Offline source/data integrity check; never calls provider APIs."""
import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {"crewai", "sentence_transformers", "torch"}

def main():
    problems = []
    paths = sorted((ROOT / "src").rglob("*.py"))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
                if any(a.name in {"StrOutputParser", "ChatPromptTemplate"} for a in node.names):
                    problems.append(str(path.relative_to(ROOT)) + ": legacy prompt/parser import")
            else:
                continue
            if FORBIDDEN.intersection(modules) or "app" in modules:
                problems.append(str(path.relative_to(ROOT)) + ": forbidden runtime import")
    expected = {
        "resources/knowledge/knowledge_base.md": "b5e63dc90222519a1ad54a672322b6c923ef8c6e",
        "eval/datasets/qa.jsonl": "f760b8c8023a31f68dd766a5c37c8c8d528b065d",
    }
    for name, digest in expected.items():
        value = (ROOT / name).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
        if actual != digest:
            problems.append(name + ": upstream data changed (update provenance if intentional)")
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"PASS: {len(paths)} Python source files; no old runtime/local-model imports; migrated data match.")

if __name__ == "__main__":
    main()
