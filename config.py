"""REZE Agent Configuration"""
import os
import zoneinfo
from pathlib import Path
from dotenv import load_dotenv

# .env 로딩
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

# === 경로 ===
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "reze_data"
WORKSPACE_DIR = BASE_DIR / "workspace"
SKILLS_DIR = BASE_DIR / "skills"
SCRIPTS_DIR = BASE_DIR / "scripts"

DATA_DIR.mkdir(exist_ok=True)
WORKSPACE_DIR.mkdir(exist_ok=True)

# === API 키 ===
CEREBRAS_API_KEY: str = os.getenv("CEREBRAS_API_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEYS: list[str] = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
GEMINI_API_KEYS: list[str] = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
TAVILY_API_KEYS: list[str] = [k.strip() for k in os.getenv("TAVILY_API_KEYS", "").split(",") if k.strip()]
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
REZE_API_KEY: str = os.getenv("REZE_API_KEY", "")
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")

# === 블로그 DB ===
BLOG_DB = {
    "host": os.getenv("BLOG_DB_HOST", "localhost"),
    "port": int(os.getenv("BLOG_DB_PORT", "5433")),
    "database": os.getenv("BLOG_DB_NAME", "aitoolslab"),
    "user": os.getenv("BLOG_DB_USER", "quotepilot"),
    "password": os.getenv("BLOG_DB_PASS", ""),
}

# === 모델 ===
CEREBRAS_MODEL = "qwen-3-235b-a22b-instruct-2507"
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
GROQ_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"

# OpenRouter (DeepSeek V3 - 최후 폴백)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-chat-v3-0324:free"

GEMINI_PRO_MODEL = "gemini-2.5-pro"
GEMINI_FLASH_MODEL = "gemini-2.5-flash"

# === 에이전트 설정 ===
MAX_ITERATIONS = 15
REFLECTION_THRESHOLD = 3
MAX_TOKENS_PER_TASK = 50_000
DAILY_TOKEN_BUDGET = 500_000
REPL_TIMEOUT = 10   # seconds
SHELL_TIMEOUT = 30  # seconds

# === Truncation ===
MAX_OBSERVATION_TOKENS = 1500
MAX_OBSERVATION_CHARS = int(MAX_OBSERVATION_TOKENS * 3.5)

# === 타임존 ===
KST = zoneinfo.ZoneInfo("Asia/Seoul")

# === 프로바이더별 일일 호출 한도 ===
PROVIDER_DAILY_LIMITS = {
    "cerebras": 999_999,   # 사실상 무제한
    "groq": 1_000,         # free tier
    "gemini_pro": 50,      # 5키 × ~10 RPD (Pro는 보수적)
    "gemini_flash": 250,   # 5키 × ~50 RPD
    "openrouter": 200,     # 보수적 (무료 티어)
}

# === 보안: 쓰기 허용 경로 ===
WRITE_ALLOWED_PATHS = [
    str(BASE_DIR / "workspace"),
    str(BASE_DIR / "skills"),
    str(Path.home() / "ai-tools-lab" / "content"),
    str(Path.home() / "nocodetoolslab" / "content"),
]

# === 보안: Shell 읽기 전용 화이트리스트 ===
SHELL_READ_ONLY = [
    "ls", "cat", "head", "tail", "grep", "find", "df", "free", "uptime",
    "whoami", "pwd", "echo", "date", "wc", "file", "stat", "du",
    "docker ps", "docker stats", "docker logs", "docker inspect", "docker images",
    "pm2 list", "pm2 jlist", "pm2 show", "pm2 logs", "pm2 describe",
    "git status", "git log", "git diff", "git branch", "git remote",
    "systemctl status", "journalctl", "top -bn1",
    "curl -s", "wget -q",
]

# === 보안: 자동 승인 스크립트 ===
SHELL_AUTO_APPROVE = [
    str(SCRIPTS_DIR / "publish-blog.sh"),
]
