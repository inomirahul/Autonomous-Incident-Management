import re
import math
import json
import ast
from typing import List, Dict, Any, Optional

Message = Dict[str, Any]  # {"role": "user"/"assistant"/"system", "content": str|list|dict}

def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))

class MonitorContext:
    def __init__(
        self,
        *,
        max_context_tokens: int = 3000,
        keep_last_user: int = 2,
        keep_last_assistant: int = 2,
        min_length: int = 3,            # allow short but meaningful lines
        drop_raw_tool_use: bool = True, # drop tool_use blocks (invocations), keep results
        drop_logs: bool = True,
    ):
        self.max_context_tokens = max_context_tokens
        self.keep_last_user = keep_last_user
        self.keep_last_assistant = keep_last_assistant
        self.min_length = min_length
        self.drop_raw_tool_use = drop_raw_tool_use
        self.drop_logs = drop_logs

    @staticmethod
    def _try_parse_serialized_messages(obj: Any) -> Optional[List[Message]]:
        # If someone accidentally passed a JSON/text dump, try to recover a list
        if not isinstance(obj, str):
            return None
        text = obj.strip()
        # quick reject
        if not (text.startswith("[") or text.startswith("(") or text.startswith("{")):
            return None
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(text)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                continue
        return None

    @staticmethod
    def _is_log(text: str) -> bool:
        return bool(re.search(r"\b(INFO|DEBUG|TRACE|ERROR|log\.|traceback|stack)\b", text, re.I))

    @staticmethod
    def _is_raw_tool_use_block(block: Any) -> bool:
        # ToolUseBlock objects or dicts with type == 'tool_use'
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return True
        if hasattr(block, "type") and getattr(block, "type") == "tool_use":
            return True
        return False

    @staticmethod
    def _is_tool_result_block(block: Any) -> bool:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            return True
        # SDK objects may not be dicts; heuristics:
        if hasattr(block, "type") and getattr(block, "type") == "tool_result":
            return True
        # some tool results come in structured dicts inside 'content' lists
        if isinstance(block, dict) and "structured_content" in block:
            return True
        return False

    @staticmethod
    def _extract_text_from_block(block: Any) -> str:
        # TextBlock case
        if isinstance(block, dict):
            t = ""
            if block.get("type") == "text":
                return block.get("text", "")
            if block.get("type") == "tool_result":
                # try to summarise structured_content or content
                sc = block.get("structured_content")
                if isinstance(sc, dict):
                    parts = []
                    for k in ("id", "title", "severity", "project"):
                        if sc.get(k):
                            parts.append(f"{k}:{sc.get(k)}")
                    # also include a short reported_issue or summary if present
                    if sc.get("reported_issue"):
                        parts.append(sc.get("reported_issue"))
                    return " | ".join(parts)
                # fallback to raw content string
                return str(block.get("content", ""))
            # generic dict: try to find text fields
            for key in ("text", "content", "message", "summary"):
                if key in block and isinstance(block[key], str):
                    t = block[key]
                    break
            if t:
                return t
            # nested structured_content inside 'content' string (often JSON dumped)
            if "content" in block and isinstance(block["content"], str):
                return MonitorContext._try_extract_json_text(block["content"])
            return json.dumps(block)[:1000]
        # object with attributes
        if hasattr(block, "text"):
            return getattr(block, "text") or ""
        if hasattr(block, "content"):
            c = getattr(block, "content")
            if isinstance(c, str):
                return c
            # if content is list of TextContent
            if isinstance(c, list):
                return " ".join(
                    getattr(b, "text", str(b)) if not isinstance(b, dict) else MonitorContext._extract_text_from_block(b)
                    for b in c
                )
            return str(c)
        return str(block)

    @staticmethod
    def _try_extract_json_text(s: str) -> str:
        # often CallToolResult.text contains an embedded JSON string; try to extract primary fields
        # try to find the first JSON object in the string
        try:
            # fast path if it's pure JSON
            obj = json.loads(s)
            if isinstance(obj, dict):
                # build compact summary
                parts = []
                for k in ("id", "title", "severity", "project", "reported_issue"):
                    if obj.get(k):
                        parts.append(f"{k}:{obj.get(k)}")
                return " | ".join(parts) if parts else str(obj)[:1000]
        except Exception:
            pass
        # regex extract {...} and try to parse
        # parsing would matter if details are mentioned clearly
        # if detail aren't cleared, we would need to justify detail
        # within system
        m = re.search(r"(\{.*\})", s, re.DOTALL)
        if m:
            candidate = m.group(1)
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    parts = []
                    for k in ("id", "title", "severity", "project", "reported_issue"):
                        if obj.get(k):
                            parts.append(f"{k}:{obj.get(k)}")
                    return " | ".join(parts) if parts else str(obj)[:1000]
            except Exception:
                pass
        # last resort: return the string truncated
        return s[:1000]

    @staticmethod
    def extract_text(content: Any) -> str:
        # content can be str | list[blocks] | dict | sdk objects
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                # This will preserve tool_result blocks because _extract_text_from_block handles them
                # but will drop raw tool_use by returning empty string for them
                if MonitorContext._is_raw_tool_use_block(block):
                    # raw invocation - skip
                    continue
                parts.append(MonitorContext._extract_text_from_block(block))
            return " ".join(p for p in parts if p)
        # dict or object
        return MonitorContext._extract_text_from_block(content)

    def _score(self, msg: Message) -> float:
        text = (msg.get("content") or "") if isinstance(msg.get("content"), str) else MonitorContext.extract_text(msg.get("content"))
        score = 0.0
        role = msg.get("role", "")
        if role == "user":
            score += 1.0
        elif role == "assistant":
            score += 0.4
        elif role == "system":
            score += 0.6
        if re.search(r"\b(decide|decision|constraint|requirement|todo|must|never|always|severity|critical|high)\b", text, re.I):
            score += 0.5
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b|\bINC-[A-Z0-9-]+\b", text):
            score += 0.25
        # penalize raw logs slightly (but don't fully drop structured tool_result)
        if self.drop_logs and self._is_log(text):
            score -= 0.6
        return max(0.0, score)

    def prepare_context(self, messages: Any) -> List[Dict[str, str]]:
        # recover if caller accidentally passed serialized string
        if isinstance(messages, str):
            parsed = self._try_parse_serialized_messages(messages)
            if parsed is not None:
                messages = parsed
            else:
                # wrap single-string as user content
                messages = [{"role": "user", "content": messages}]

        if not isinstance(messages, list):
            # defensive fallback
            return []

        # Normalize: flatten content to plain text, but keep 'tool_result' summaries
        normalized: List[Dict[str, str]] = []
        for m in messages:
            role = m.get("role", "user")
            raw_content = m.get("content")
            # drop pure raw tool_use blocks (invocations) unless they have useful follow-up
            if isinstance(raw_content, list) and any(self._is_raw_tool_use_block(b) for b in raw_content):
                # if list has also tool_result blocks, allow those (extract_text will handle)
                if all(self._is_raw_tool_use_block(b) for b in raw_content):
                    # pure invocation, skip
                    continue
            text = MonitorContext.extract_text(raw_content)
            text = (text or "").strip()
            if not text:
                continue
            # low-signal filter: allow short incident ids/titles so threshold is low
            if len(text) < self.min_length:
                continue
            # log filtering (but keep tool_result that contain structured_content)
            if self.drop_logs and self._is_log(text) and not ("INC-" in text or "severity" in text.lower()):
                continue
            normalized.append({"role": role, "content": text})

        if not normalized:
            return []

        # Force-keep last N user & assistant messages (preserve order)
        last_users = [m for m in normalized if m["role"] == "user"][-self.keep_last_user:]
        last_assist = [m for m in normalized if m["role"] == "assistant"][-self.keep_last_assistant:]
        forced = last_users + last_assist
        forced_set = set()
        for f in forced:
            forced_set.add((f["role"], f["content"]))

        # Score the rest
        candidates = []
        for m in normalized:
            if (m["role"], m["content"]) in forced_set:
                continue
            candidates.append((m, self._score(m)))

        candidates.sort(key=lambda x: x[1], reverse=True)

        # Assemble under token budget
        budget = self.max_context_tokens
        selected: List[Dict[str, str]] = []

        def try_add(msg: Dict[str, str]) -> bool:
            nonlocal budget
            cost = estimate_tokens(msg["content"])
            if budget - cost < 0:
                return False
            budget -= cost
            selected.append(msg)
            return True

        # add forced first (preserve natural chronological order)
        forced_in_order = []
        for m in normalized:
            if (m["role"], m["content"]) in forced_set and (m not in forced_in_order):
                forced_in_order.append(m)
        for m in forced_in_order:
            try_add(m)

        # add scored candidates until budget
        for m, sc in candidates:
            if sc <= 0:
                continue
            if not try_add(m):
                # try to skip expensive messages and continue
                continue

        # preserve original ordering as much as possible
        # build index map from first occurrence in original normalized list
        index = { (m["role"], m["content"]) : i for i, m in enumerate(normalized) }
        selected.sort(key=lambda m: index.get((m["role"], m["content"]), 0))

        # final dedupe by content
        seen = set()
        out = []
        for m in selected:
            key = (m["role"], m["content"][:900])
            if key in seen:
                continue
            seen.add(key)
            out.append({"role": m["role"], "content": m["content"]})

        return out
