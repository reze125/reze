-- REZE Fish Schema — 물고기 아키텍처 테이블
-- 기존 SSOT 테이블은 그대로 두고 추가만 함

-- 기존 크론잡 44개를 이 테이블로 이관
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,    -- "blog_ai_tools_news"
    cron_expr TEXT NOT NULL,      -- "10:00" 또는 "10:00 0,1,2,3,4,5" (요일 0=월)
    job_type TEXT NOT NULL,       -- "blog", "analytics", "competitor", "report", "health"
    config TEXT DEFAULT '{}',     -- JSON 설정
    last_run TEXT,                -- ISO datetime
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 물고기의 행동 기록 (기억)
CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    action_type TEXT NOT NULL,    -- self_heal, execute_task, run_scheduled, etc.
    summary TEXT,
    success INTEGER,
    tokens_used INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    data TEXT                     -- JSON 추가 정보
);

-- 인프라 상태 이력
CREATE TABLE IF NOT EXISTS infra_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    check_type TEXT,              -- docker, disk, memory, api
    status TEXT,                  -- ok, warning, critical
    details TEXT
);

-- ═══════════════════════════════════════════════════════════════════════
-- EVENT HORIZON v3.0 — 10개 신규 테이블
-- ═══════════════════════════════════════════════════════════════════════

-- 1. 사냥 기억 (Hunt Memory) — 성공한 사냥 경험
CREATE TABLE IF NOT EXISTS hunt_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,           -- H1~H5: trending_news, tool_discovery, competitor_gap, affiliate, evergreen
    source TEXT NOT NULL,             -- tavily, producthunt, hackernews, github, reddit, ga4
    query TEXT,                       -- 검색 쿼리
    target TEXT NOT NULL,             -- 발견한 먹이 (URL, 키워드 등)
    success INTEGER DEFAULT 0,        -- 성공 여부
    score REAL DEFAULT 0.0,           -- 사냥 점수 (0.0-1.0)
    blog_slug TEXT,                   -- 결과 블로그 슬러그
    tokens_used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    metadata TEXT DEFAULT '{}'        -- JSON 추가 정보
);

-- 2. 사냥 패턴 (Hunt Pattern) — 학습된 사냥 패턴
CREATE TABLE IF NOT EXISTS hunt_pattern (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    hour_of_day INTEGER,              -- 0-23, 가장 성공적인 시간
    day_of_week INTEGER,              -- 0-6, 가장 성공적인 요일
    success_rate REAL DEFAULT 0.0,    -- 성공률
    avg_score REAL DEFAULT 0.0,       -- 평균 점수
    sample_count INTEGER DEFAULT 0,   -- 샘플 수
    last_updated TEXT DEFAULT (datetime('now')),
    metadata TEXT DEFAULT '{}'
);

-- 3. 영역 스캔 (Territory Scan) — Accretion Disk 스캔 기록
CREATE TABLE IF NOT EXISTS territory_scan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,             -- tavily, producthunt, hackernews, github, reddit, ga4
    scan_type TEXT NOT NULL,          -- trending, search, monitor
    query TEXT,
    results_count INTEGER DEFAULT 0,
    interesting_count INTEGER DEFAULT 0,  -- 흥미로운 발견 수
    scan_duration_ms INTEGER DEFAULT 0,
    success INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    data TEXT DEFAULT '{}'            -- JSON 결과 요약
);

-- 4. 진화 로그 (Evolution Log) — 자기 개선 기록
CREATE TABLE IF NOT EXISTS evolution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evolution_type TEXT NOT NULL,     -- prompt, strategy, threshold, pattern
    target TEXT NOT NULL,             -- 개선 대상
    before_value TEXT,
    after_value TEXT,
    reason TEXT,                      -- 개선 이유
    impact_score REAL,                -- 영향도 (-1.0 ~ 1.0)
    created_at TEXT DEFAULT (datetime('now')),
    metadata TEXT DEFAULT '{}'
);

-- 5. 중력 우물 (Gravity Well) — Pillar 콘텐츠
CREATE TABLE IF NOT EXISTS gravity_well (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blog TEXT NOT NULL,               -- aitoolslab, nocodetoolslab
    pillar_slug TEXT NOT NULL UNIQUE, -- "best-ai-writing-tools-2025"
    pillar_title TEXT NOT NULL,
    topic_cluster TEXT NOT NULL,      -- "ai-writing"
    target_keywords TEXT,             -- JSON array ["ai writing tools", "best ai writers"]
    cluster_count INTEGER DEFAULT 0,  -- 연결된 클러스터 수
    total_traffic INTEGER DEFAULT 0,  -- 총 트래픽
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    metadata TEXT DEFAULT '{}'
);

-- 6. 클러스터 콘텐츠 (Gravity Well Cluster)
CREATE TABLE IF NOT EXISTS gravity_well_cluster (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pillar_id INTEGER NOT NULL,       -- gravity_well.id FK
    cluster_slug TEXT NOT NULL,
    cluster_title TEXT NOT NULL,
    link_to_pillar INTEGER DEFAULT 1, -- 필러로 링크 여부
    traffic INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (pillar_id) REFERENCES gravity_well(id)
);

-- 7. 블로그 간 내부 링크 (Cross Blog Link)
CREATE TABLE IF NOT EXISTS cross_blog_link (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_blog TEXT NOT NULL,
    from_slug TEXT NOT NULL,
    to_blog TEXT NOT NULL,
    to_slug TEXT NOT NULL,
    anchor_text TEXT,
    link_type TEXT DEFAULT 'related', -- related, pillar, cluster, cta
    clicks INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(from_blog, from_slug, to_blog, to_slug)
);

-- 8. 수익 귀속 (Revenue Attribution)
CREATE TABLE IF NOT EXISTS revenue_attribution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,        -- blog_post, email, affiliate, saas
    source_id TEXT NOT NULL,          -- 블로그 슬러그 또는 캠페인 ID
    revenue_type TEXT NOT NULL,       -- affiliate_click, affiliate_sale, saas_signup, saas_upgrade
    amount REAL DEFAULT 0.0,          -- USD
    currency TEXT DEFAULT 'USD',
    attribution_model TEXT DEFAULT 'last_click',
    created_at TEXT DEFAULT (datetime('now')),
    metadata TEXT DEFAULT '{}'
);

-- 9. 죽은 콘텐츠 (Dead Content) — Hawking Radiation 후보
CREATE TABLE IF NOT EXISTS dead_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blog TEXT NOT NULL,
    slug TEXT NOT NULL,
    title TEXT,
    death_reason TEXT NOT NULL,       -- no_traffic, high_bounce, no_conversion, outdated
    page_views_30d INTEGER DEFAULT 0,
    bounce_rate REAL,
    days_since_publish INTEGER,
    recycled INTEGER DEFAULT 0,       -- 재활용 완료 여부
    recycle_action TEXT,              -- merge, redirect, update, delete
    recycle_target TEXT,              -- 재활용 대상 슬러그
    created_at TEXT DEFAULT (datetime('now')),
    recycled_at TEXT,
    UNIQUE(blog, slug)
);

-- 10. 실험 (Experiment) — A/B 테스트
CREATE TABLE IF NOT EXISTS experiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    hypothesis TEXT NOT NULL,
    experiment_type TEXT NOT NULL,    -- title, cta, layout, timing
    variants TEXT NOT NULL,           -- JSON array of variants
    metrics TEXT NOT NULL,            -- JSON array of metrics to track
    status TEXT DEFAULT 'draft',      -- draft, running, completed, stopped
    winner_variant TEXT,
    confidence REAL,
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    results TEXT DEFAULT '{}'         -- JSON 결과
);

-- ═══════════════════════════════════════════════════════════════════════
-- 인덱스
-- ═══════════════════════════════════════════════════════════════════════

-- 기존 인덱스
CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled);
CREATE INDEX IF NOT EXISTS idx_action_log_type ON action_log(action_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_action_log_timestamp ON action_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_infra_log_type ON infra_log(check_type, timestamp);

-- EVENT HORIZON 인덱스
CREATE INDEX IF NOT EXISTS idx_hunt_memory_strategy ON hunt_memory(strategy, created_at);
CREATE INDEX IF NOT EXISTS idx_hunt_memory_source ON hunt_memory(source, created_at);
CREATE INDEX IF NOT EXISTS idx_hunt_memory_success ON hunt_memory(success, score);
CREATE INDEX IF NOT EXISTS idx_hunt_pattern_strategy ON hunt_pattern(strategy);
CREATE INDEX IF NOT EXISTS idx_territory_scan_source ON territory_scan(source, created_at);
CREATE INDEX IF NOT EXISTS idx_evolution_log_type ON evolution_log(evolution_type, created_at);
CREATE INDEX IF NOT EXISTS idx_gravity_well_blog ON gravity_well(blog, topic_cluster);
CREATE INDEX IF NOT EXISTS idx_gravity_well_cluster_pillar ON gravity_well_cluster(pillar_id);
CREATE INDEX IF NOT EXISTS idx_cross_blog_link_from ON cross_blog_link(from_blog, from_slug);
CREATE INDEX IF NOT EXISTS idx_revenue_attribution_source ON revenue_attribution(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_dead_content_blog ON dead_content(blog, recycled);
CREATE INDEX IF NOT EXISTS idx_experiment_status ON experiment(status);
