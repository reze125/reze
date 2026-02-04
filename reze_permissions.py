"""REZE Permissions — 보안 게이트웨이"""
import re
import ast
import io
import os
import contextlib
import threading
from pathlib import Path
from typing import Optional

import config

import logging
logger = logging.getLogger("REZE.permissions")


# === 권한 등급 ===
class PermissionTier:
    AUTO_APPROVE = "auto_approve"
    STANDARD = "standard"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


# === 체이닝 연산자 패턴 (v5.0: trusted source는 | && 허용) ===
# 항상 차단: ; ` $() ${} > >> < << <( >( \n \r \x00
STRICT_CHAIN_OPERATORS = re.compile(
    r';|`|\$\(|\$\{|>{1,2}\s*/|<{1,2}\s|<\(|>\(|\x00|\n|\r'
)
# untrusted에서 추가 차단: | ||  &&
PIPE_OPERATORS = re.compile(r'\|{1,2}|&&')

# 위험 명령 블랙리스트 (항상 차단)
DANGEROUS_COMMANDS = [
    'rm -rf /', 'rm -rf /*', 'rm -rf ~',
    'mkfs', 'dd if=', 'dd of=/',
    ':(){ :|:& };:', 'chmod -R 777 /',
    'chmod 777 /', '> /dev/sda', '> /dev/null',
    'mv /* ', 'mv / ', 'wget | sh', 'curl | sh',
    'wget | bash', 'curl | bash',
]


class PermissionSystem:
    """shell/python/http/filesystem/web_search 명령의 위험 등급 판정."""

    def assess(self, tool: str, tool_input, source: str = "api") -> str:
        """범용 위험 판단 진입점."""
        if tool == "shell":
            return self._assess_shell(str(tool_input), source)
        elif tool == "python":
            return PermissionTier.STANDARD  # SecurePythonREPL이 자체 검사
        elif tool == "http":
            return self._assess_http(tool_input)
        elif tool == "filesystem":
            return self._assess_filesystem(tool_input)
        elif tool == "web_search":
            return PermissionTier.AUTO_APPROVE
        elif tool == "web_fetch":
            return PermissionTier.AUTO_APPROVE  # v5.0: 웹페이지 읽기는 안전
        elif tool == "code_edit":
            return PermissionTier.STANDARD  # v5.0: 경로 체크는 도구 내부에서
        elif tool == "final_answer":
            return PermissionTier.AUTO_APPROVE
        return PermissionTier.STANDARD

    # v5.0: 확장된 trusted sources
    TRUSTED_SOURCES = (
        "api", "schedule", "judgment", "autonomous_loop",
        "self_healing", "agent_supervisor", "discovery",
        "analyzer", "planner", "capability", "feedback"
    )

    def _assess_shell(self, command: str, source: str) -> str:
        """shell 명령 4단계 검사 (v5.0: trusted source는 파이프 허용)."""
        # Step 1: bash -c / sh -c 내부 추출
        payload = self._extract_shell_c_payload(command)
        cmd_lower = payload.lower()

        # Step 2: 위험 명령 블랙리스트 — 무조건 차단
        for dangerous in DANGEROUS_COMMANDS:
            if dangerous.lower() in cmd_lower:
                logger.warning(f"CRITICAL: dangerous command '{dangerous}' in '{payload[:80]}'")
                return PermissionTier.CRITICAL

        # Step 3: 체이닝 연산자 검사
        # 3a: 항상 차단되는 연산자 (; ` $() ${} > < 등)
        if STRICT_CHAIN_OPERATORS.search(payload):
            logger.warning(f"DANGEROUS: strict chain operator in '{payload[:80]}'")
            return PermissionTier.DANGEROUS

        # 3b: 파이프/AND 연산자는 trusted source만 허용
        if PIPE_OPERATORS.search(payload):
            if source not in self.TRUSTED_SOURCES:
                logger.warning(f"DANGEROUS: pipe/and operator from untrusted source in '{payload[:80]}'")
                return PermissionTier.DANGEROUS
            # trusted source면 통과 (아래에서 STANDARD 반환)

        # Step 4: 자동 승인 스크립트
        cmd_stripped = payload.strip()
        for approved in config.SHELL_AUTO_APPROVE:
            if cmd_stripped.startswith(approved):
                return PermissionTier.AUTO_APPROVE

        # Step 5: 읽기 전용 화이트리스트
        for readonly in config.SHELL_READ_ONLY:
            if cmd_lower.startswith(readonly.lower()):
                return PermissionTier.AUTO_APPROVE

        # Step 6: source 기반 판단
        if source in self.TRUSTED_SOURCES:
            return PermissionTier.STANDARD
        return PermissionTier.CRITICAL

    def _assess_http(self, request) -> str:
        """HTTP 요청 위험 판단."""
        if isinstance(request, dict):
            url = request.get("url", "")
        else:
            url = str(request)
        # 내부/외부 모두 STANDARD (CredentialStore가 인증 관리)
        return PermissionTier.STANDARD

    def _assess_filesystem(self, request) -> str:
        """파일시스템 작업 위험 판단."""
        if isinstance(request, dict):
            op = request.get("operation", "read")
            path = request.get("path", "")
        else:
            op = "read"
            path = str(request)

        if op == "read" or op == "list":
            return PermissionTier.AUTO_APPROVE

        # 쓰기: 허용 경로 내인지 확인
        try:
            resolved = Path(path).expanduser().resolve()
            for allowed in config.WRITE_ALLOWED_PATHS:
                try:
                    resolved.relative_to(Path(allowed).resolve())
                    return PermissionTier.STANDARD
                except ValueError:
                    continue
        except Exception:
            pass
        return PermissionTier.DANGEROUS

    def _extract_shell_c_payload(self, command: str) -> str:
        """bash -c '...' 또는 bash -c "..." 에서 내부 명령 추출."""
        patterns = [
            r'(?:bash|sh)\s+-c\s+"((?:[^"\\]|\\.)*)"',
            r"(?:bash|sh)\s+-c\s+'((?:[^'\\]|\\.)*)'",
        ]
        for p in patterns:
            m = re.search(p, command)
            if m:
                return m.group(1)
        return command


class SecurePythonREPL:
    """AST 검증 + 타임아웃 기반 안전한 Python 실행.

    기존 apex_final.py SecurePythonREPL(845-967줄) 기반.
    SAFE_MODE 항상 True (데몬이므로).
    v5.0: whitelist import 허용.
    """

    # v5.0: 허용된 import 목록
    ALLOWED_IMPORTS = {
        'json', 're', 'math', 'datetime', 'collections', 'itertools',
        'csv', 'pathlib', 'hashlib', 'base64',
        'statistics', 'textwrap', 'difflib', 'sqlite3',
        'time', 'functools', 'operator', 'string', 'copy',
        'random', 'decimal', 'fractions', 'numbers',
        'html', 'xml', 'urllib', 'urllib.parse',
    }

    FORBIDDEN_CALLS = {
        'eval', 'exec', 'compile', 'open',
        'input', 'breakpoint', 'help', 'credits', 'license', 'copyright',
        'getattr', 'setattr', 'delattr', 'hasattr',
        'globals', 'locals', 'vars', 'dir',
        'memoryview', 'bytearray',
        '__import__', 'importlib',
    }

    FORBIDDEN_ATTRS = {
        '__class__', '__bases__', '__subclasses__', '__mro__',
        '__globals__', '__code__', '__closure__', '__dict__',
        '__builtins__', '__import__', '__loader__', '__spec__',
    }

    # v5.0: FORBIDDEN_NODES에서 Import/ImportFrom 제거 (whitelist로 관리)
    FORBIDDEN_NODES = set()

    def __init__(self, timeout: int = None):
        self.timeout = timeout or config.REPL_TIMEOUT
        self.globals = {
            '__builtins__': {
                'print': print, 'len': len, 'range': range, 'str': str,
                'int': int, 'float': float, 'bool': bool, 'list': list,
                'dict': dict, 'set': set, 'tuple': tuple, 'type': type,
                'sum': sum, 'min': min, 'max': max, 'abs': abs, 'round': round,
                'sorted': sorted, 'reversed': reversed, 'enumerate': enumerate,
                'zip': zip, 'map': map, 'filter': filter, 'all': all, 'any': any,
                'isinstance': isinstance, 'issubclass': issubclass,
                'True': True, 'False': False, 'None': None,
                'pow': pow, 'divmod': divmod, 'hex': hex, 'oct': oct, 'bin': bin,
                'chr': chr, 'ord': ord, 'repr': repr, 'ascii': ascii,
                'format': format, 'slice': slice,
                # v5.0: import 지원을 위한 __import__ 제한적 허용
                '__import__': self._safe_import,
            }
        }
        # v5.0: 허용된 모듈 사전 로드
        import math, json, re, datetime, collections, itertools
        import csv, pathlib, hashlib, base64, statistics
        import textwrap, difflib, sqlite3, time, functools
        import operator, string, copy, random, decimal, html
        self.globals['math'] = math
        self.globals['json'] = json
        self.globals['re'] = re
        self.globals['datetime'] = datetime
        self.globals['collections'] = collections
        self.globals['itertools'] = itertools
        self.globals['csv'] = csv
        self.globals['pathlib'] = pathlib
        self.globals['hashlib'] = hashlib
        self.globals['base64'] = base64
        self.globals['statistics'] = statistics
        self.globals['textwrap'] = textwrap
        self.globals['difflib'] = difflib
        self.globals['sqlite3'] = sqlite3
        self.globals['time'] = time
        self.globals['functools'] = functools
        self.globals['operator'] = operator
        self.globals['string'] = string
        self.globals['copy'] = copy
        self.globals['random'] = random
        self.globals['decimal'] = decimal
        self.globals['html'] = html

    def _safe_import(self, name, *args, **kwargs):
        """v5.0: whitelist import만 허용하는 __import__ 래퍼."""
        module = name.split('.')[0]
        if module not in self.ALLOWED_IMPORTS:
            raise ImportError(f"Import '{name}' not allowed")
        return __builtins__['__import__'](name, *args, **kwargs)

    def run(self, code: str) -> str:
        """execute의 별칭."""
        return self.execute(code)

    def _validate_ast(self, code: str) -> Optional[str]:
        """AST 분석으로 코드 검증. 문제 있으면 에러 메시지 반환."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"Syntax error: {e}"

        for node in ast.walk(tree):
            # 금지된 노드 타입
            if type(node) in self.FORBIDDEN_NODES:
                return f"Forbidden: {type(node).__name__} not allowed"

            # v5.0: import 검사 - whitelist 허용
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if module not in self.ALLOWED_IMPORTS:
                        return f"Forbidden: import '{alias.name}' not allowed (whitelist: {', '.join(sorted(self.ALLOWED_IMPORTS)[:10])}...)"

            if isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split('.')[0]
                    if module not in self.ALLOWED_IMPORTS:
                        return f"Forbidden: from '{node.module}' import not allowed"

            # 함수 호출 검사
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_CALLS:
                        return f"Forbidden: '{node.func.id}()' not allowed"
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in self.FORBIDDEN_CALLS:
                        return f"Forbidden: '.{node.func.attr}()' not allowed"

            # 속성 접근 검사
            if isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRS:
                    return f"Forbidden: '.{node.attr}' access not allowed"

            # 문자열 내 위험 패턴 검사
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for attr in self.FORBIDDEN_ATTRS:
                    if attr in node.value:
                        return f"Forbidden: string contains '{attr}'"

        return None

    def execute(self, code: str, source: str = "unknown") -> str:
        """Python 코드 실행. AST 검증 → 타임아웃 스레드 실행."""
        # v6.0 Phase 2D-2: VIGIL 코드 검사
        try:
            from manus.vigil import get_vigil
            vigil = get_vigil()
            vigil_result = vigil.check_code(code, "python", source)
            if not vigil_result.allowed:
                return f"BLOCKED by VIGIL: {vigil_result.reason}"
        except ImportError:
            pass  # VIGIL 모듈 없으면 스킵

        error = self._validate_ast(code)
        if error:
            return f"ERROR: {error}"

        result_container = {"output": "", "error": None}

        def _run():
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    try:
                        exec(code, self.globals)
                    except SyntaxError:
                        result = eval(code, self.globals)
                        if result is not None:
                            print(result)
                result_container["output"] = buf.getvalue()
            except Exception as e:
                result_container["error"] = f"{type(e).__name__}: {e}"
            finally:
                buf.close()

        thread = threading.Thread(target=_run)
        thread.daemon = True
        thread.start()
        thread.join(timeout=self.timeout)

        if thread.is_alive():
            return f"ERROR: Execution timeout ({self.timeout}s)"

        if result_container["error"]:
            return f"ERROR: {result_container['error']}"

        output = result_container["output"]
        return output if output else "Executed successfully (no output)"


class FilesystemTool:
    """파일시스템 읽기/쓰기. 쓰기는 WRITE_ALLOWED_PATHS 내에서만.

    기존 apex_final.py Sandbox(791-842줄) 기반.
    """

    BLOCKED_PATTERNS = [".env", ".git", "__pycache__", ".ssh", ".aws",
                        "id_rsa", "credentials", "secret"]

    def read(self, path: str, max_size: int = 100_000) -> str:
        """파일 읽기. 경로 제한 없음 (읽기는 안전)."""
        try:
            target = Path(path).expanduser().resolve()
            if not target.exists():
                return f"ERROR: File not found: {path}"
            if target.is_dir():
                return self.list_dir(path)
            if target.stat().st_size > max_size:
                return f"ERROR: File too large (max {max_size} bytes)"
            return target.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            return f"ERROR: {e}"

    def write(self, path: str, content: str, source: str = "unknown") -> str:
        """파일 쓰기. WRITE_ALLOWED_PATHS 내에서만 + VIGIL 검사."""
        # v6.0 Phase 2D-2: VIGIL 파일 및 콘텐츠 검사
        try:
            from manus.vigil import get_vigil
            vigil = get_vigil()
            vigil_result = vigil.check_file_content(path, content, source)
            if not vigil_result.allowed:
                return f"BLOCKED by VIGIL: {vigil_result.reason}"
        except ImportError:
            pass  # VIGIL 모듈 없으면 스킵

        try:
            target = Path(path).expanduser().resolve()

            # 허용 경로 확인
            allowed = False
            for allowed_path in config.WRITE_ALLOWED_PATHS:
                try:
                    target.relative_to(Path(allowed_path).resolve())
                    allowed = True
                    break
                except ValueError:
                    continue

            if not allowed:
                return f"ERROR: Write not allowed outside permitted paths. Target: {target}"

            # 차단 패턴 확인
            path_str = str(target).lower()
            for pattern in self.BLOCKED_PATTERNS:
                if pattern in path_str:
                    return f"ERROR: Blocked pattern '{pattern}' in path"

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"ERROR: {e}"

    def list_dir(self, path: str = ".") -> str:
        """디렉토리 목록."""
        try:
            target = Path(path).expanduser().resolve()
            if not target.exists():
                return f"ERROR: Directory not found: {path}"
            items = []
            for item in sorted(target.iterdir()):
                prefix = "[DIR]" if item.is_dir() else "[FILE]"
                items.append(f"{prefix} {item.name}")
            return f"[{target}]\n" + "\n".join(items[:100])
        except Exception as e:
            return f"ERROR: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 자율 정책 (이 섹션은 REZE가 수정 불가 — FORBIDDEN)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# === LOCK 행동 목록 ===
# FREE: 이 목록에 없는 모든 행동
# LOCK: 이 목록에 있는 행동 (주인 승인 필요)

LOCK_ACTIONS = frozenset({
    # 돈 관련 (되돌릴 수 없음)
    "price_change",
    "paid_api_subscribe",
    "refund_process",
    "server_plan_change",

    # 보안 관련 (뚫리면 끝)
    "env_modify",
    "credentials_modify",
    "permissions_critical_change",
    "firewall_change",
    "ssh_change",

    # 데이터 파괴 (복구 불가)
    "db_drop",
    "db_mass_delete",
    "project_dir_delete",
    "backup_delete",
    "git_force_push",

    # 외부 공개 (되돌릴 수 없음)
    "domain_purchase",
    "external_account_create",
    "email_send",
    "external_post",
})


def is_free(action_type: str) -> bool:
    """LOCK이 아닌 모든 행동은 FREE. 이 함수는 수정 불가."""
    return action_type not in LOCK_ACTIONS


# === 자기 수정 화이트리스트 ===
# REZE가 수정할 수 있는 파일 (이 목록 자체는 수정 불가)
# v6.0 Phase 2D-2: 핵심 파일(config.py, ssot.py, reze_core.py)은 VIGIL이 보호

SELF_MODIFIABLE_FILES = [
    "skills/*/SKILL.md",
    # "config.py",          # VIGIL 보호 대상
    "prompts/*.py",
    "utils/*.py",
    "docs/*",
    "reze_daemon.py",
    "reze_tools.py",
    # "ssot.py",            # VIGIL 보호 대상
    "skills_manager.py",
    "reze_alert.py",
    "reze_biz.py",
    # "reze_core.py",       # VIGIL 보호 대상
    "reze_self_healing.py",
    "moltbook_bot.py",
    "self_evolution.py",
]

FORBIDDEN_FILES = [
    ".env",
    "credentials.json",
    "reze_permissions.py",   # 이 파일 자체
]


# === 자원 제한 ===
MAX_DAILY_EVOLUTIONS = 5
MAX_DAILY_BLOG_POSTS = 2
MAX_DAILY_TOKEN_BUDGET = 500_000


# === 블로그 품질 게이트 ===
BLOG_QUALITY_GATE = {
    # 1단계: 객관적 하드체크 (조작 불가)
    "hard_checks": {
        "min_words": 2500,
        "min_headings_h2": 7,
        "min_paragraphs": 15,
        "has_comparison_table": True,
        "has_pros_cons": True,
        "has_pricing_info": True,
        "has_internal_links": 2,
        "no_ai_phrases": [
            "as an AI",
            "I cannot",
            "it's important to note",
            "in today's fast-paced world",
            "in conclusion,",
            "dive into",
            "delve into",
            "game-changer",
            "revolutionize",
            "leverage",
        ],
    },
    # 2단계: 크로스 리뷰 (다른 LLM이 채점)
    "cross_review": {
        "writer": "gemini",
        "reviewer": "groq",
        "min_score": 85,
        "max_retries": 3,
    },
    # 채점 프롬프트
    "review_prompt": """
        이 블로그 글을 TechRadar, Zapier Blog 수준과 비교하라.

        채점 기준 (각 20점, 총 100점):
        1. 실사용 경험 느낌: 직접 써본 것처럼 구체적인가?
           (스크린샷 설명, 구체적 사용 시나리오, 실제 수치)
        2. 정보 밀도: 읽고 나서 바로 결정할 수 있는가?
           (가격, 기능 비교표, 명확한 추천)
        3. 독창성: 다른 AI 글과 구별되는가?
           (고유한 관점, 예상 못한 비교, 실제 팁)
        4. 구조: 훑어보기만 해도 핵심이 잡히는가?
           (명확한 H2, 비교표, TL;DR, 요약)
        5. SEO 자연스러움: 키워드가 억지로 들어간 느낌 없는가?

        85점 미만이면 구체적으로 어디가 약한지 지적하라.
        점수 부풀리지 마. 엄격하게.

        응답 형식:
        SCORE: {점수}
        WEAK: {약한 부분}
        FIX: {구체적 수정 방법}
    """,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 학습 속도 정책 (Phase 3)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7일 검증은 인간 기준. REZE는 24시간 깨어있다.
# 즉시 확인 가능한 건 즉시. 진짜 시간 필요한 것만 기다린다.

LEARNING_SPEED = {
    # 즉시 (5분) — 변경 전후 벤치마크로 바로 확인 가능
    "instant": {
        "triggers": [
            "self_improvement_tech",
            "code_optimization",
            "config_change",
            "prompt_optimization",
            "library_upgrade",
        ],
        "verify_after_minutes": 5,
        "method": "benchmark_before_after",
    },

    # 빠름 (6시간) — 안정성 확인 필요
    "fast": {
        "triggers": [
            "blog_published",
            "seo_change",
            "auto_fix_applied",
            "workflow_change",
            "new_skill_added",
        ],
        "verify_after_hours": 6,
        "method": "compare_metrics",
    },

    # 하루 (24시간) — 외부 반응 필요
    "daily": {
        "triggers": [
            "keyword_opportunity",
            "competitor_response",
            "blog_content_update",
        ],
        "verify_after_hours": 24,
        "method": "daily_comparison",
    },

    # 주간 (7일) — 구글 순위처럼 진짜 시간이 걸리는 것만
    "weekly": {
        "triggers": [
            "seo_ranking_change",
            "domain_authority_change",
        ],
        "verify_after_days": 7,
        "method": "weekly_trend",
    },
}


def get_verification_delay(discovery_type: str) -> dict:
    """발견 유형에 따른 검증 딜레이 반환."""
    for speed, cfg in LEARNING_SPEED.items():
        if discovery_type in cfg["triggers"]:
            return {"speed": speed, **cfg}
    return {"speed": "fast", "verify_after_hours": 6, "method": "compare_metrics"}


# 메타학습 상수
META_LEARNING_THRESHOLD = 30    # 교훈 30개 쌓이면 패턴 추출
MAX_DAILY_LESSONS = 20          # 하루 교훈 최대 20개


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# v4.0 Universal Quality Gates
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

QUALITY_GATES = {
    "blog_article": {
        "hard_checks": {
            "min_words": 1200,
            "max_words": 3500,
            "has_h2": True,
            "has_internal_link": True,
            "has_cta": True,
            "no_banned_phrases": True,
        },
        "cross_review": {
            "writer": "gemini_pro",
            "reviewer": "groq",
            "min_score": 85,
            "max_retries": 2,
            "review_prompt": "TechRadar/Zapier 수준 비교 채점"
        }
    },
    "saas_report": {
        "hard_checks": {
            "has_metrics": True,
            "has_comparison": True,
            "has_action_items": True,
            "max_staleness_hours": 24
        },
        "cross_review": {
            "writer": "gemini_pro",
            "reviewer": "groq",
            "min_score": 75,
            "max_retries": 1
        }
    },
    "email_outreach": {
        "hard_checks": {
            "max_words": 200,
            "has_cta": True,
            "has_unsubscribe": True,
            "no_spam_words": True
        },
        "cross_review": {
            "writer": "gemini_flash",
            "reviewer": "groq",
            "min_score": 80,
            "max_retries": 1
        }
    },
    "code_change": {
        "hard_checks": {
            "has_backup": True,
            "has_health_check": True,
            "has_rollback_plan": True,
            "no_forbidden_files": True
        },
        "test_required": True,
        "cross_review": None
    },
    "strategy_document": {
        "hard_checks": {
            "has_data_backing": True,
            "has_risk_assessment": True,
            "has_alternatives": True,
            "has_timeline": True
        },
        "cross_review": {
            "writer": "gemini_pro",
            "reviewer": "gemini_flash",
            "min_score": 80,
            "max_retries": 2
        }
    },
    "discord_report": {
        "hard_checks": {
            "max_words": 500,
            "has_summary": True,
            "has_numbers": True
        },
        "cross_review": None
    }
}

# 월간 토큰 예산
MONTHLY_TOKEN_BUDGET = {
    "gemini_pro": 1_000_000,
    "gemini_flash": 2_000_000,
    "groq": 5_000_000,
    "cerebras": 10_000_000,
    "tavily": 800,
}
