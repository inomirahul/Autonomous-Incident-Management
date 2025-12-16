from typing import List, Dict, Any, Optional
import os
from fastmcp import FastMCP
from github import Github, GithubException

mcp = FastMCP(name="github-tools")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN required in env")

gh = Github(GITHUB_TOKEN, per_page=100)

@mcp.tool()
def search_code(repo_full_name: str, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Return list of code hits: {path, repo, html_url}
    """
    q = f"{query} repo:{repo_full_name}"
    results = []
    for item in gh.search_code(q):
        results.append({"path": item.path, "repo": item.repository.full_name, "html_url": item.html_url})
        if len(results) >= max_results:
            break
    return results

@mcp.tool()
def create_branch_and_commit(repo_full_name: str, base_branch: str, new_branch: str,
                             file_path: str, file_content: str, commit_message: str) -> Dict[str, Any]:
    """
    Create branch (from base_branch), create or update file at file_path on new_branch.
    Returns commit sha and branch name.
    """
    repo = gh.get_repo(repo_full_name)
    base = repo.get_branch(base_branch)
    base_sha = base.commit.sha
    ref = f"refs/heads/{new_branch}"
    try:
        repo.create_git_ref(ref=ref, sha=base_sha)
    except GithubException as e:
        # if already exists, ignore
        if e.status != 422:
            raise

    try:
        create_res = repo.create_file(path=file_path, message=commit_message, content=file_content, branch=new_branch)
        sha = create_res["commit"].sha
    except GithubException as e:
        if e.status == 422:
            existing = repo.get_contents(file_path, ref=new_branch)
            update = repo.update_file(path=file_path, message=commit_message, content=file_content, sha=existing.sha, branch=new_branch)
            sha = update["commit"].sha
        else:
            raise
    return {"branch": new_branch, "commit_sha": sha}

@mcp.tool()
def create_pull_request(repo_full_name: str, title: str, body: str, head_branch: str, base_branch: str = "main") -> Dict[str, Any]:
    repo = gh.get_repo(repo_full_name)
    pr = repo.create_pull(title=title, body=body, head=head_branch, base=base_branch)
    return {"pr_number": pr.number, "pr_url": pr.html_url}

if __name__ == "__main__":
    mcp.run()
