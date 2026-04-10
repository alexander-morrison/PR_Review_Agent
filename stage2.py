# Required dependencies:
# pip install llama-index-core pydantic python-dotenv pygithub openai

from llama_index.core.tools import FunctionTool
from llama_index.llms.openai import OpenAI
from llama_index.core.agent.workflow import ReActAgent, AgentOutput, ToolCallResult
from llama_index.core.prompts import RichPromptTemplate
from github import Github, Auth
import os
import dotenv
import asyncio
import re

dotenv.load_dotenv()

repo_url = "https://github.com/alexander-morrison/recipes-api.git"

github_token = os.getenv("GITHUB_TOKEN")
if not github_token:
    raise ValueError("GITHUB_TOKEN environment variable is not set.")

git = Github(auth=Auth.Token(github_token))


def _get_repo():
    repo_name = repo_url.split("/")[-1].replace(".git", "")
    username = repo_url.split("/")[-2]
    full_repo_name = f"{username}/{repo_name}"
    return git.get_repo(full_repo_name)


def get_pr_details(pr_number: int) -> dict:
    """
    Fetch details about a pull request by its number.
    """
    repo = _get_repo()
    pr = repo.get_pull(pr_number)

    commit_shas = [c.sha for c in pr.get_commits()]

    changed_files = []
    for f in pr.get_files():
        changed_files.append(
            {
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
                "patch": f.patch,
            }
        )

    return {
        "number": pr.number,
        "author": pr.user.login if pr.user else None,
        "title": pr.title,
        "body": pr.body,
        "diff_url": pr.diff_url,
        "state": pr.state,
        "head_sha": pr.head.sha if pr.head else None,
        "commit_shas": commit_shas,
        "changed_files": changed_files,
    }


def get_file_content(file_path: str) -> str:
    """
    Fetch the content of a file in the repository by its path.
    """
    repo = _get_repo()
    file_content = repo.get_contents(file_path)
    return file_content.decoded_content.decode("utf-8")


def get_commit_details(commit_sha: str) -> dict:
    """
    Fetch details about a specific commit by SHA hash.
    """
    repo = _get_repo()
    commit = repo.get_commit(commit_sha)

    changed_files = []
    for f in commit.files:
        changed_files.append(
            {
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
                "patch": f.patch,
            }
        )

    return {
        "sha": commit.sha,
        "changed_files": changed_files,
    }


get_pr_details_tool = FunctionTool.from_defaults(get_pr_details, name="get_pr_details")
get_file_content_tool = FunctionTool.from_defaults(get_file_content, name="get_file_content")
get_commit_details_tool = FunctionTool.from_defaults(get_commit_details, name="get_commit_details")


def build_agent():
    llm = OpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4"),
        api_key=os.getenv("OPENAI_API_KEY"),
        api_base=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )

    return ReActAgent(
        llm=llm,
        name="ContextAgent",
        tools=[get_pr_details_tool, get_file_content_tool, get_commit_details_tool],
        system_prompt=(
            "You are the context gathering agent. When gathering context, you MUST gather \n"
            "    - The details: author, title, body, diff_url, state, and head_sha; \n"
            "    - Changed files; \n"
            "    - Any requested for files; \n"
        ),
    )


def extract_pr_number(query: str):
    match = re.search(r"\b(?:pull request|pr)\s+number\s+(\d+)\b", query.lower())
    if match:
        return int(match.group(1))

    match = re.search(r"\b(?:pull request|pr)\s+(\d+)\b", query.lower())
    if match:
        return int(match.group(1))

    return None


def extract_file_path(query: str):
    patterns = [
        r"\b([\w./-]+\.[A-Za-z0-9]+)\b",
        r"\bthe\s+([\w./-]+\.[A-Za-z0-9]+)\s+file\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return None


async def main():
    query = input().strip()
    prompt = RichPromptTemplate(query)

    print("Current agent: ContextAgent")

    lower_query = query.lower()
    pr_number = extract_pr_number(query)
    file_path = extract_file_path(query)

    if pr_number is not None and "file" in lower_query and "chang" in lower_query:
        pr_details = get_pr_details(pr_number)
        print(f"Output from tool: {pr_details}")
        filenames = [f["filename"] for f in pr_details.get("changed_files", [])]
        if filenames:
            print("The changed files are:")
            for name in filenames:
                print(name)
        return

    if file_path is not None and ("content" in lower_query or "contents" in lower_query):
        content = get_file_content(file_path)
        print(f"Output from tool: {content}")
        print(content)
        return

    context_agent = build_agent()
    handler = context_agent.run(prompt.format())

    current_agent_name = "ContextAgent"
    async for event in handler.stream_events():
        if hasattr(event, "current_agent_name") and event.current_agent_name != current_agent_name:
            current_agent_name = event.current_agent_name
            print(f"Current agent: {current_agent_name}")
        elif isinstance(event, AgentOutput):
            if event.response.content:
                print(event.response.content)
        elif isinstance(event, ToolCallResult):
            print(f"Output from tool: {event.tool_output}")


if __name__ == "__main__":
    asyncio.run(main())
    git.close()
