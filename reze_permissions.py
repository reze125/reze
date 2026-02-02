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


# === 체이닝 연산자 패턴 (v3.3 보안 핵심) ===
# ;  |  ||  &&  `  $(  ${  > >> < << <( >( \n \r \x00
CHAIN_OPERATORS = re.compile(
    r';|\|{1,2}|&&|`|\$\(|\$\{|>{1,2}\s|<{1,2}\s|<\(|>\(|\x00|\n|\r'
)


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
        elif tool == "final_answer":
            return PermissionTier.AUTO_APPROVE
        return PermissionTier.STANDARD

    def _assess_shell(self, command: str, source: str) -> str:
        """shell 명령 4단계 검사."""
        # Step 1: bash -c / sh -c 내부 추출
        payload = self._extract_shell_c_payload(command)

        # Step 2: 체이닝 연산자 검사 — 있으면 무조건 DANGEROUS
        if CHAIN_OPERATORS.search(payload):
            logger.warning(f"DANGEROUS: chain operator in '{payload[:80]}'")
            return PermissionTier.DANGEROUS

        # Step 3a: 자동 승인 스크립트
        cmd_stripped = payload.strip()
        for approved in config.SHELL_AUTO_APPROVE:
            if cmd_stripped.startswith(approved):
                return PermissionTier.AUTO_APPROVE

        # Step 3b: 읽기 전용 화이트리스트
        cmd_lower = cmd_stripped.lower()
        for readonly in config.SHELL_READ_ONLY:
            if cmd_lower.startswith(readonly.lower()):
                return PermissionTier.AUTO_APPROVE

        # Step 4: source 기반 판단
        if source in ("api", "schedule"):
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
    """

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

    FORBIDDEN_NODES = {ast.Import, ast.ImportFrom}

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
            }
        }
        import math
        self.globals['math'] = math

    def _validate_ast(self, code: str) -> Optional[str]:
        """AST 분석으로 코드 검증. 문제 있으면 에러 메시지 반환."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"Syntax error: {e}"

        for node in ast.walk(tree):
            # 금지된 노드 타입 (import)
            if type(node) in self.FORBIDDEN_NODES:
                return f"Forbidden: {type(node).__name__} not allowed"

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

    def execute(self, code: str) -> str:
        """Python 코드 실행. AST 검증 → 타임아웃 스레드 실행."""
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

    def write(self, path: str, content: str) -> str:
        """파일 쓰기. WRITE_ALLOWED_PATHS 내에서만."""
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
