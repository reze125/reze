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

# === Discord 웹훅 (3채널) ===
DISCORD_WEBHOOK_DAILY = "https://discordapp.com/api/webhooks/1468063975005491383/BnEVg4NwSXpSU0RwXAAHTXKLawOiom1e60voSDRiJk4vbFFsyCjuHTQtxNwd_l9BNJSR"
DISCORD_WEBHOOK_ALERT = "https://discordapp.com/api/webhooks/1468064161589231653/VIMtLQ_pdt4sD8A52ha2Q66Emh-ke23TSyW5dl6PIS1fO_1XTZVX4fLvaFAtcG5A7sKk"
DISCORD_WEBHOOK_BLOG = "https://discordapp.com/api/webhooks/1468064625001103392/pNYzS189NYZVCV2IoNXe6l7icSi_7SIws7TsN9SbeuZokeEVDb0HpVNPH4Wk4S7o8KPV"

# === 블로그 DB ===
BLOG_DB = {
    "host": os.getenv("BLOG_DB_HOST", "localhost"),
    "port": int(os.getenv("BLOG_DB_PORT", "5433")),
    "database": os.getenv("BLOG_DB_NAME", "aitoolslab"),
    "user": os.getenv("BLOG_DB_USER", "quotepilot"),
    "password": os.getenv("BLOG_DB_PASS", ""),
}

# === 모델 ===
CEREBRAS_MODEL = "llama-3.3-70b"
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

# === Self-Refine 설정 (Phase 2C-2) ===
REFINE_ENABLED = True
REFINE_MAX_ITERATIONS = 3
REFINE_MIN_SCORE = 70  # 이 점수 이상이면 통과
REFINE_TYPES = ["blog_article", "saas_report", "strategy_document", "email_outreach"]

# === ADaPT 설정 (Phase 2D-3) ===
ADAPT_ENABLED = True
ADAPT_CONFIDENCE_THRESHOLD = 0.7  # 이 이하면 확인 요청/경고
ADAPT_AUTO_ADJUST = True          # 실행 결과 기반 자동 조정
ADAPT_MAX_ADJUSTMENTS = 3         # 계획당 최대 조정 횟수

# === Acon 자율 제어 설정 (Phase 2D-4) ===
ACON_ENABLED = True
ACON_DAILY_BUDGET = 100           # 일일 자율 행동 예산
ACON_AUTO_APPROVE_THRESHOLD = 0.2  # 위험도 이하면 자동 승인
ACON_REQUIRE_CONFIRM_THRESHOLD = 0.7  # 위험도 이상이면 확인 권장
ACON_MAX_RETRIES = 2              # 실패 시 재시도 횟수

# === LATS 트리 탐색 설정 (Phase 2D-5) ===
LATS_ENABLED = True
LATS_BRANCH_FACTOR = 3            # 각 노드에서 생성할 후보 수
LATS_MAX_DEPTH = 10               # 최대 탐색 깊이
LATS_EXPLORATION_WEIGHT = 1.4     # UCB1 탐색 가중치
LATS_MIN_SCORE_THRESHOLD = 0.3    # 이 점수 이하면 가지치기

# === REZE 페르소나 ===
REZE_OWNER_TITLE = "보스"  # 오너 호칭 (형 → 보스)

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
    str(BASE_DIR / "docs"),
    str(BASE_DIR / "prompts"),
    str(BASE_DIR / "utils"),
    str(Path.home() / "ai-tools-lab" / "src" / "content"),
    str(Path.home() / "nocodetoolslab" / "content"),
]

# === 발견→연결 맵 ===
CONNECTION_MAP = {
    "competitor_price_change": {
        "affects": ["postpilot", "quotepilot", "browserpilot", "agenthub"],
        "actions": ["pricing-analysis", "revenue", "blog 비교 글 업데이트"],
        "urgency": "medium"
    },
    "competitor_new_feature": {
        "affects": ["postpilot", "quotepilot", "browserpilot", "agenthub"],
        "actions": ["기능 수요 분석", "구현 난이도 평가", "차별화 또는 추가"],
        "urgency": "low"
    },
    "new_tool_discovered": {
        "affects": ["blog-aitoolslab", "blog-nocodetoolslab", "affiliate"],
        "actions": ["분석", "어필리에이트 확인", "블로그 글 작성"],
        "urgency": "medium"
    },
    "keyword_opportunity": {
        "affects": ["blog-aitoolslab", "blog-nocodetoolslab"],
        "actions": ["검색량 분석", "article_type 결정", "글 큐 추가"],
        "urgency": "low"
    },
    "service_repeated_failure": {
        "affects": ["해당 서비스", "linux-admin"],
        "actions": ["로그 분석", "근본 원인", "수정", "테스트"],
        "urgency": "high"
    },
    "blog_traffic_spike": {
        "affects": ["blog-seo", "affiliate", "content-repurpose"],
        "actions": ["인기 글 파악", "후속 글 기획", "어필리에이트 최적화"],
        "urgency": "medium"
    },
    "blog_traffic_drop": {
        "affects": ["blog-seo", "analytics"],
        "actions": ["원인 분석", "서버 체크", "SEO 감사"],
        "urgency": "high"
    },
    "security_vulnerability": {
        "affects": ["dependency-audit", "server-hardening"],
        "actions": ["심각도 평가", "패치", "전체 스캔"],
        "urgency": "critical"
    },
    "cost_overrun": {
        "affects": ["cost-tracking", "llm-optimization"],
        "actions": ["비용 분석", "불필요한 호출 줄이기", "모델 전환"],
        "urgency": "medium"
    },
    "self_improvement_tech": {
        "affects": ["reze-core", "self-learning"],
        "actions": ["자기 코드 분석", "적용 가치 평가", "셀프코딩"],
        "urgency": "low"
    }
}

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

# === Phase 4 Part D+E: SaaS & Gumroad ===
LEMONSQUEEZY_API_KEY: str = os.getenv("LEMONSQUEEZY_API_KEY", "")
LEMONSQUEEZY_WEBHOOK_SECRET: str = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
LEMONSQUEEZY_STORE_ID: str = os.getenv("LEMONSQUEEZY_STORE_ID", "")
GUMROAD_ACCESS_TOKEN: str = os.getenv("GUMROAD_ACCESS_TOKEN", "")
GUMROAD_PING_SECRET: str = os.getenv("GUMROAD_PING_SECRET", "")
EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "brevo")
BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")

# SaaS 제품 목록 (LemonSqueezy 연동용)
SAAS_PRODUCTS = {
    "postpilot": {"name": "PostPilot", "type": "subscription"},
    "browserpilot": {"name": "BrowserPilot", "type": "subscription"},
    "agenthub": {"name": "AgentHub", "type": "subscription"},
    "rag-service": {"name": "RAG-as-a-Service", "type": "subscription"},
    "quotepilot": {"name": "QuotePilot", "type": "subscription", "plans": [19, 49, 99]},
}

# Gumroad 제품 목록
GUMROAD_PRODUCTS = {
    "product_1": {"name": "TBD", "type": "digital"},
    "product_2": {"name": "TBD", "type": "digital"},
    "product_3": {"name": "TBD", "type": "digital"},
    "product_4": {"name": "TBD", "type": "digital"},
}

# Discord 웹훅 (수익 알림용 — 기존 ALERT 채널 재사용)
DISCORD_WEBHOOK_REVENUE = DISCORD_WEBHOOK_ALERT


# === v4.0 Tavily API 키 로테이션 ===
_tavily_key_index = 0


def get_tavily_key() -> str:
    """라운드 로빈으로 Tavily API 키 반환."""
    global _tavily_key_index
    keys = TAVILY_API_KEYS if TAVILY_API_KEYS else ([TAVILY_API_KEY] if TAVILY_API_KEY else [])
    if not keys:
        return ""
    key = keys[_tavily_key_index % len(keys)]
    _tavily_key_index += 1
    return key


# ============================================================
# v5.0 SOVEREIGN — Runtime Tunable Settings
# Phase 4에서 REZE가 자기 판단으로 조정할 수 있는 값들.
# 지금은 초기값. 근거 없는 값은 주석에 "arbitrary"로 표시.
# ============================================================

# WorkerPool
WORKER_MAX_CONCURRENT = 3          # arbitrary. Phase 4에서 CPU 보고 조정

# Planner
PLANNER_MAX_REPLANS = 2            # arbitrary. Phase 4에서 성공률 보고 조정
PLANNER_MAX_STEPS = 10             # arbitrary.

# Discovery
DISCOVERY_INTERVAL_MINUTES = 30    # arbitrary. Phase 4에서 변화 빈도 보고 조정

# Feedback
FEEDBACK_CHECK_INTERVAL_HOURS = 1  # arbitrary. Phase 4에서 서비스 특성 보고 조정

# Judgment
JUDGMENT_INTERVAL_HOURS = 6        # arbitrary.

# Task Processing
TASK_PROCESSOR_INTERVAL_MINUTES = 5  # arbitrary.
