"""LATS - Language Agent Tree Search.

다중 경로 탐색:
1. 후보 생성 (Branch)
2. 후보 평가 (Evaluate)
3. 경로 선택 (Select)
4. 백트래킹 (Backtrack)
"""
import logging
import math
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("REZE.lats")


class NodeStatus(Enum):
    PENDING = "pending"       # 아직 확장 안 함
    EXPANDED = "expanded"     # 자식 노드 생성됨
    TERMINAL = "terminal"     # 최종 노드 (성공 또는 실패)
    PRUNED = "pruned"         # 가지치기됨


@dataclass
class SearchNode:
    """탐색 트리 노드."""
    id: int = 0
    parent_id: Optional[int] = None
    depth: int = 0
    thought: str = ""
    tool: str = ""
    tool_input: Any = ""
    observation: str = ""
    score: float = 0.0
    visits: int = 0
    value: float = 0.0
    status: NodeStatus = NodeStatus.PENDING
    is_success: bool = False
    children: List['SearchNode'] = field(default_factory=list)


@dataclass
class SearchResult:
    """탐색 결과."""
    success: bool
    best_path: List[SearchNode]
    best_score: float
    total_nodes: int
    explored_nodes: int
    final_answer: str = ""


class LATSEngine:
    """Language Agent Tree Search Engine."""

    def __init__(
        self,
        ssot=None,
        router=None,
        tools=None,
        branch_factor: int = 3,
        max_depth: int = 10,
        exploration_weight: float = 1.4,
        min_score_threshold: float = 0.3
    ):
        self.ssot = ssot
        self.router = router
        self.tools = tools
        self.branch_factor = branch_factor
        self.max_depth = max_depth
        self.exploration_weight = exploration_weight
        self.min_score_threshold = min_score_threshold
        self._session_id: Optional[int] = None
        self._nodes: Dict[int, SearchNode] = {}
        self._node_counter = 0

    # === 메인 탐색 ===

    async def search(
        self,
        task: str,
        task_id: str = None,
        system_prompt: str = "",
        context: Dict[str, Any] = None
    ) -> SearchResult:
        """
        트리 탐색 실행.

        Args:
            task: 태스크 설명
            task_id: 태스크 ID
            system_prompt: 시스템 프롬프트
            context: 추가 컨텍스트

        Returns:
            SearchResult
        """
        context = context or {}

        # 세션 초기화
        self._session_id = self._create_session(task_id, task)
        self._nodes.clear()
        self._node_counter = 0

        # 루트 노드 생성
        root = self._create_node(
            parent_id=None,
            depth=0,
            thought=f"Task: {task}",
            tool="",
            tool_input=""
        )

        # MCTS 스타일 탐색
        best_path = []
        best_score = 0.0
        explored = 0

        max_iterations = self.max_depth * self.branch_factor * 2

        for iteration in range(max_iterations):
            # 1. Selection: UCB1으로 노드 선택
            selected = self._select_node(root)
            if not selected:
                # 모든 노드가 확장됨 - 최고 터미널 노드 찾기
                break

            # 2. Expansion: 후보 생성
            if selected.status == NodeStatus.PENDING and selected.depth < self.max_depth:
                candidates = await self._expand_node(selected, task, system_prompt, context)
                explored += len(candidates)

                # 3. Evaluation: 각 후보 평가
                for candidate in candidates:
                    score = await self._evaluate_node(candidate, task, context)
                    candidate.score = score

                    # 가지치기
                    if score < self.min_score_threshold:
                        candidate.status = NodeStatus.PRUNED
                        logger.debug(f"[LATS] Pruned node {candidate.id} (score={score:.2f})")
                        continue

                    # 4. Simulation: 실제 실행
                    if candidate.tool and candidate.tool != "final_answer":
                        observation = await self._simulate_node(candidate)
                        candidate.observation = observation

                        # 성공/실패 판단
                        if "ERROR" in observation or "BLOCKED" in observation:
                            candidate.value = -0.5
                        else:
                            candidate.value = score

                    # final_answer 체크
                    if candidate.tool == "final_answer":
                        candidate.status = NodeStatus.TERMINAL
                        candidate.is_success = True
                        path = self._get_path_to_node(candidate)
                        path_score = sum(n.score for n in path) / len(path) if path else 0
                        if path_score > best_score:
                            best_score = path_score
                            best_path = path
                            logger.info(f"[LATS] New best path found: score={path_score:.2f}, depth={len(path)}")

            # 5. Backpropagation: 값 전파
            self._backpropagate(selected)

            # 조기 종료 조건
            if best_score > 0.9:
                logger.info(f"[LATS] Early termination: best_score={best_score:.2f}")
                break

        # 결과 정리
        final_answer = ""
        if best_path:
            for node in best_path:
                if node.tool == "final_answer":
                    final_answer = str(node.tool_input)
                    break

        self._complete_session(best_path, best_score)

        logger.info(f"[LATS] Search complete: nodes={len(self._nodes)}, explored={explored}, best_score={best_score:.2f}")

        return SearchResult(
            success=bool(final_answer),
            best_path=best_path,
            best_score=best_score,
            total_nodes=len(self._nodes),
            explored_nodes=explored,
            final_answer=final_answer
        )

    # === Selection (UCB1) ===

    def _select_node(self, root: SearchNode) -> Optional[SearchNode]:
        """UCB1 기반 노드 선택."""
        node = root

        while node.children and node.status == NodeStatus.EXPANDED:
            # UCB1 점수로 자식 선택
            best_child = None
            best_ucb = -float('inf')

            for child in node.children:
                if child.status == NodeStatus.PRUNED:
                    continue
                if child.status == NodeStatus.TERMINAL:
                    continue

                ucb = self._ucb1_score(child, node.visits)
                if ucb > best_ucb:
                    best_ucb = ucb
                    best_child = child

            if not best_child:
                break
            node = best_child

        return node if node.status == NodeStatus.PENDING else None

    def _ucb1_score(self, node: SearchNode, parent_visits: int) -> float:
        """UCB1 점수 계산."""
        if node.visits == 0:
            return float('inf')  # 미방문 노드 우선

        exploitation = node.value / node.visits
        exploration = self.exploration_weight * math.sqrt(
            math.log(parent_visits + 1) / node.visits
        )
        return exploitation + exploration

    # === Expansion ===

    async def _expand_node(
        self,
        node: SearchNode,
        task: str,
        system_prompt: str,
        context: Dict
    ) -> List[SearchNode]:
        """노드 확장 - 여러 후보 생성."""
        candidates = []

        if not self.router:
            # 라우터 없으면 기본 후보 생성
            default_actions = [
                {"thought": "Search for information", "tool": "web_search", "input": task[:50]},
                {"thought": "Provide answer", "tool": "final_answer", "input": "Unable to process without LLM"},
            ]
            for action in default_actions[:self.branch_factor]:
                child = self._create_node(
                    parent_id=node.id,
                    depth=node.depth + 1,
                    thought=action["thought"],
                    tool=action["tool"],
                    tool_input=action["input"]
                )
                node.children.append(child)
                candidates.append(child)
            node.status = NodeStatus.EXPANDED
            return candidates

        # 현재까지의 경로를 컨텍스트로
        path = self._get_path_to_node(node)
        history = self._path_to_messages(path)

        # LLM에 여러 후보 요청
        prompt = f"""Task: {task}

Previous steps:
{self._format_history(history)}

Generate {self.branch_factor} different possible next actions.
For each action, provide:
1. Thought: your reasoning
2. Tool: one of (web_search, web_fetch, shell, python, http, code_edit, final_answer)
3. Input: the input for the tool

Format as JSON array:
[{{"thought": "...", "tool": "...", "input": "..."}}, ...]

Important:
- If the task is complete, use "final_answer" as tool with the answer as input
- Each action should be meaningfully different
- Consider both exploration and exploitation"""

        try:
            response = await self.router.call(
                "planning",
                prompt,
                system=system_prompt or "You are a planning assistant.",
                temperature=0.7  # 다양성을 위해 온도 높임
            )

            # 응답 파싱
            text = response.text if hasattr(response, 'text') else str(response)
            actions = self._parse_candidates(text)

            for action in actions[:self.branch_factor]:
                child = self._create_node(
                    parent_id=node.id,
                    depth=node.depth + 1,
                    thought=action.get("thought", ""),
                    tool=action.get("tool", ""),
                    tool_input=action.get("input", "")
                )
                node.children.append(child)
                candidates.append(child)

            node.status = NodeStatus.EXPANDED

        except Exception as e:
            logger.warning(f"[LATS] Expansion failed: {e}")
            node.status = NodeStatus.EXPANDED  # 실패해도 확장 완료로 표시

        return candidates

    def _parse_candidates(self, text: str) -> List[Dict]:
        """후보 응답 파싱."""
        # JSON 배열 추출
        try:
            if "[" in text:
                start = text.find("[")
                end = text.rfind("]") + 1
                json_str = text[start:end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # 단일 객체 시도
        try:
            if "{" in text:
                start = text.find("{")
                end = text.rfind("}") + 1
                obj = json.loads(text[start:end])
                return [obj]
        except json.JSONDecodeError:
            pass

        return []

    # === Evaluation ===

    async def _evaluate_node(
        self,
        node: SearchNode,
        task: str,
        context: Dict
    ) -> float:
        """노드 평가 점수 계산."""
        score = 0.5  # 기본 점수

        # Factor 1: 도구 적합성
        tool_relevance = self._assess_tool_relevance(node.tool, task)
        score += tool_relevance * 0.3

        # Factor 2: 입력 품질
        input_quality = self._assess_input_quality(node.tool, node.tool_input)
        score += input_quality * 0.2

        # Factor 3: final_answer면 높은 점수
        if node.tool == "final_answer":
            score += 0.3

        # Factor 4: 깊이 페널티 (너무 깊으면 감점)
        depth_penalty = node.depth * 0.02
        score -= depth_penalty

        return max(0.0, min(1.0, score))

    def _assess_tool_relevance(self, tool: str, task: str) -> float:
        """도구 적합성 평가."""
        task_lower = task.lower()

        relevance_map = {
            "web_search": ["search", "find", "look up", "research", "what is", "how to"],
            "web_fetch": ["fetch", "get", "download", "read url", "website", "page"],
            "shell": ["run", "execute", "command", "check", "list", "install", "status"],
            "python": ["calculate", "compute", "analyze", "process", "parse", "convert"],
            "code_edit": ["edit", "modify", "change", "update", "fix", "write code"],
            "http": ["api", "request", "post", "endpoint"],
            "final_answer": ["answer", "result", "done", "complete", "summary"],
        }

        keywords = relevance_map.get(tool, [])
        matches = sum(1 for kw in keywords if kw in task_lower)
        return min(1.0, matches * 0.25 + 0.4)

    def _assess_input_quality(self, tool: str, tool_input: Any) -> float:
        """입력 품질 평가."""
        if not tool_input:
            return 0.3

        input_str = str(tool_input)
        score = 0.5

        # 길이 체크
        if len(input_str) > 10:
            score += 0.2
        if len(input_str) > 50:
            score += 0.1

        # 위험 패턴 감점
        danger_patterns = ["rm -rf", "drop table", "delete *", "sudo rm"]
        for pattern in danger_patterns:
            if pattern in input_str.lower():
                score -= 0.3

        return max(0.0, min(1.0, score))

    # === Simulation ===

    async def _simulate_node(self, node: SearchNode) -> str:
        """노드 실제 실행."""
        if not self.tools:
            return "(simulation: no tools available)"

        try:
            observation = await self.tools.execute(
                node.tool,
                node.tool_input,
                source="lats"
            )
            return observation[:2000]
        except Exception as e:
            return f"ERROR: {e}"

    # === Backpropagation ===

    def _backpropagate(self, node: SearchNode):
        """값 역전파."""
        value = node.value if node.value != 0 else node.score
        current = node

        while current:
            current.visits += 1
            current.value += value
            # 부모로 이동
            if current.parent_id and current.parent_id in self._nodes:
                current = self._nodes[current.parent_id]
            else:
                break

    # === 헬퍼 메서드 ===

    def _create_node(
        self,
        parent_id: Optional[int],
        depth: int,
        thought: str,
        tool: str,
        tool_input: Any
    ) -> SearchNode:
        """새 노드 생성."""
        self._node_counter += 1
        node = SearchNode(
            id=self._node_counter,
            parent_id=parent_id,
            depth=depth,
            thought=thought,
            tool=tool,
            tool_input=tool_input
        )
        self._nodes[node.id] = node

        # DB 저장
        if self.ssot and self._session_id:
            try:
                self.ssot.conn.execute("""
                    INSERT INTO lats_nodes
                    (session_id, parent_id, depth, action, tool, tool_input, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    self._session_id,
                    parent_id,
                    depth,
                    thought[:500],
                    tool,
                    str(tool_input)[:500],
                    node.status.value
                ))
                self.ssot.conn.commit()
            except Exception as e:
                logger.debug(f"[LATS] Node save failed: {e}")

        return node

    def _get_path_to_node(self, node: SearchNode) -> List[SearchNode]:
        """루트부터 노드까지의 경로."""
        path = []
        current = node

        while current:
            path.append(current)
            if current.parent_id and current.parent_id in self._nodes:
                current = self._nodes[current.parent_id]
            else:
                break

        return list(reversed(path))

    def _path_to_messages(self, path: List[SearchNode]) -> List[Dict]:
        """경로를 메시지 형식으로 변환."""
        messages = []
        for node in path:
            if node.tool:
                messages.append({
                    "role": "assistant",
                    "content": f"Thought: {node.thought}\nTool: {node.tool}\nInput: {node.tool_input}"
                })
                if node.observation:
                    messages.append({
                        "role": "user",
                        "content": f"Observation: {node.observation}"
                    })
        return messages

    def _format_history(self, messages: List[Dict]) -> str:
        """메시지 히스토리 포맷팅."""
        lines = []
        for msg in messages[-6:]:  # 최근 6개만
            content = msg.get('content', '')[:200]
            lines.append(f"[{msg['role']}] {content}")
        return "\n".join(lines) if lines else "(no history)"

    def _create_session(self, task_id: str, task: str) -> int:
        """탐색 세션 생성."""
        if not self.ssot:
            return 0

        try:
            cursor = self.ssot.conn.execute("""
                INSERT INTO lats_sessions (task_id, task, status)
                VALUES (?, ?, 'active')
            """, (task_id or "unknown", task[:500]))
            self.ssot.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.debug(f"[LATS] Session create failed: {e}")
            return 0

    def _complete_session(self, best_path: List[SearchNode], best_score: float):
        """세션 완료."""
        if not self.ssot or not self._session_id:
            return

        try:
            path_json = json.dumps([
                {"tool": n.tool, "input": str(n.tool_input)[:100], "score": n.score}
                for n in best_path
            ])
            self.ssot.conn.execute("""
                UPDATE lats_sessions SET
                    status = 'completed',
                    total_nodes = ?,
                    explored_nodes = ?,
                    best_path = ?,
                    best_score = ?,
                    completed_at = datetime('now')
                WHERE id = ?
            """, (
                len(self._nodes),
                sum(1 for n in self._nodes.values() if n.status == NodeStatus.EXPANDED),
                path_json,
                best_score,
                self._session_id
            ))
            self.ssot.conn.commit()
        except Exception as e:
            logger.debug(f"[LATS] Session complete failed: {e}")

    # === 통계 ===

    def get_stats(self) -> Dict[str, Any]:
        """LATS 통계."""
        return {
            "branch_factor": self.branch_factor,
            "max_depth": self.max_depth,
            "exploration_weight": self.exploration_weight,
            "min_score_threshold": self.min_score_threshold,
            "current_nodes": len(self._nodes),
        }

    def get_tree_summary(self) -> Dict[str, Any]:
        """현재 탐색 트리 요약."""
        if not self._nodes:
            return {"nodes": 0, "max_depth": 0}

        depths = [n.depth for n in self._nodes.values()]
        statuses = {}
        for n in self._nodes.values():
            status_key = n.status.value
            statuses[status_key] = statuses.get(status_key, 0) + 1

        return {
            "total_nodes": len(self._nodes),
            "max_depth": max(depths) if depths else 0,
            "avg_depth": sum(depths) / len(depths) if depths else 0,
            "by_status": statuses
        }

    def get_best_paths(self, top_k: int = 3) -> List[Dict]:
        """상위 K개 경로 반환."""
        terminal_nodes = [
            n for n in self._nodes.values()
            if n.status == NodeStatus.TERMINAL and n.is_success
        ]

        paths = []
        for node in terminal_nodes:
            path = self._get_path_to_node(node)
            path_score = sum(n.score for n in path) / len(path) if path else 0
            paths.append({
                "score": path_score,
                "depth": len(path),
                "path": [{"tool": n.tool, "input": str(n.tool_input)[:50]} for n in path]
            })

        return sorted(paths, key=lambda x: x["score"], reverse=True)[:top_k]
