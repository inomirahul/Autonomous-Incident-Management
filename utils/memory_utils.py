def should_store_memory(memory_type: str, content: dict) -> bool:
    if memory_type not in {"fact", "decision", "constraint"}:
        return False

    if not content:
        return False

    # reject procedural/tool noise
    if "arguments" in content and "result" in content:
        return False

    return True


def normalize_memory(memory_type: str, content: dict) -> str:
    if memory_type == "fact":
        return content["fact"]

    if memory_type == "decision":
        return f"{content['decision']} — reason: {content['reason']}"

    if memory_type == "constraint":
        return content["constraint"]

    return f"{memory_type}: {content}"
