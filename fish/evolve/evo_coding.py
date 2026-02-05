"""
Evolutionary Coding — REZE v6.0 SOVEREIGN
진화적 코딩 (유전 알고리즘)

프롬프트와 전략을 유전 알고리즘으로 진화시킵니다.
선택 → 교차 → 변이 → 적합도 평가 → 반복

가동 조건: experiment_queue 완료 10회 이상
"""

import json
import random
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

logger = logging.getLogger("reze.evolve.evo_coding")


class GeneType(Enum):
    """유전자 유형"""
    PROMPT = "prompt"           # 프롬프트 템플릿
    STRATEGY = "strategy"       # 전략 파라미터
    WEIGHT = "weight"           # 가중치
    THRESHOLD = "threshold"     # 임계값


@dataclass
class Gene:
    """유전자"""
    gene_id: str
    gene_type: GeneType
    value: Any
    metadata: Dict = field(default_factory=dict)


@dataclass
class Individual:
    """개체 (유전자 집합)"""
    individual_id: str
    generation: int
    genes: List[Gene] = field(default_factory=list)
    fitness: float = 0.0
    parent_ids: List[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class Population:
    """개체군"""
    population_id: str
    domain: str  # 진화 대상 도메인
    generation: int
    individuals: List[Individual] = field(default_factory=list)
    best_fitness: float = 0.0
    avg_fitness: float = 0.0


class EvoCoding:
    """
    진화적 코딩 엔진.
    유전 알고리즘으로 프롬프트/전략 최적화.
    """

    # 기본 설정
    POPULATION_SIZE = 10
    ELITE_COUNT = 2
    MUTATION_RATE = 0.1
    CROSSOVER_RATE = 0.7

    def __init__(self, ssot, llm_router=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router

    async def is_active(self) -> bool:
        """활성화 조건: experiment_queue 완료 10회 이상"""
        try:
            row = self.conn.execute("""
                SELECT COUNT(*) FROM experiment_queue
                WHERE status = 'completed'
            """).fetchone()
            return row[0] >= 10
        except:
            return False

    async def initialize_population(
        self,
        domain: str,
        seed_genes: List[Dict] = None
    ) -> Population:
        """
        초기 개체군 생성.

        Args:
            domain: 진화 대상 도메인 (e.g., "hunt_prompt", "quality_threshold")
            seed_genes: 시드 유전자 (없으면 랜덤 생성)

        Returns:
            Population
        """
        pop_id = f"pop_{domain}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        population = Population(
            population_id=pop_id,
            domain=domain,
            generation=0
        )

        # 개체 생성
        for i in range(self.POPULATION_SIZE):
            individual = await self._create_individual(
                domain, 0, seed_genes, i
            )
            population.individuals.append(individual)

        # DB에 저장
        self._save_population(population)

        logger.info("Initialized population %s with %d individuals",
                    pop_id, len(population.individuals))

        return population

    async def _create_individual(
        self,
        domain: str,
        generation: int,
        seed_genes: List[Dict] = None,
        index: int = 0
    ) -> Individual:
        """개체 생성"""
        ind_id = f"ind_{domain}_{generation}_{index}_{random.randint(1000, 9999)}"

        individual = Individual(
            individual_id=ind_id,
            generation=generation,
            created_at=datetime.utcnow().isoformat()
        )

        if seed_genes and index < len(seed_genes):
            # 시드에서 생성
            for sg in seed_genes[index] if isinstance(seed_genes[index], list) else [seed_genes[index]]:
                gene = Gene(
                    gene_id=f"gene_{ind_id}_{len(individual.genes)}",
                    gene_type=GeneType(sg.get("type", "weight")),
                    value=sg.get("value"),
                    metadata=sg.get("metadata", {})
                )
                individual.genes.append(gene)
        else:
            # 랜덤 생성
            individual.genes = await self._generate_random_genes(domain)

        return individual

    async def _generate_random_genes(self, domain: str) -> List[Gene]:
        """도메인별 랜덤 유전자 생성"""
        genes = []

        if domain == "hunt_prompt":
            # 프롬프트 구성 요소
            genes.append(Gene(
                gene_id=f"gene_tone_{random.randint(1000, 9999)}",
                gene_type=GeneType.PROMPT,
                value=random.choice(["formal", "casual", "technical", "friendly"]),
                metadata={"component": "tone"}
            ))
            genes.append(Gene(
                gene_id=f"gene_length_{random.randint(1000, 9999)}",
                gene_type=GeneType.WEIGHT,
                value=random.uniform(0.5, 2.0),
                metadata={"component": "length_multiplier"}
            ))
            genes.append(Gene(
                gene_id=f"gene_detail_{random.randint(1000, 9999)}",
                gene_type=GeneType.THRESHOLD,
                value=random.uniform(0.3, 0.9),
                metadata={"component": "detail_level"}
            ))

        elif domain == "quality_threshold":
            # 품질 임계값
            genes.append(Gene(
                gene_id=f"gene_min_words_{random.randint(1000, 9999)}",
                gene_type=GeneType.THRESHOLD,
                value=random.randint(100, 500),
                metadata={"component": "min_words"}
            ))
            genes.append(Gene(
                gene_id=f"gene_min_score_{random.randint(1000, 9999)}",
                gene_type=GeneType.THRESHOLD,
                value=random.uniform(0.5, 0.9),
                metadata={"component": "min_quality_score"}
            ))

        elif domain == "strategy_weights":
            # 전략 가중치
            strategies = ["trend_snipe", "gap_fill", "comparison", "deep_guide", "news_jack"]
            for strategy in strategies:
                genes.append(Gene(
                    gene_id=f"gene_{strategy}_{random.randint(1000, 9999)}",
                    gene_type=GeneType.WEIGHT,
                    value=random.uniform(0.1, 1.0),
                    metadata={"strategy": strategy}
                ))

        else:
            # 기본: 3개 가중치
            for i in range(3):
                genes.append(Gene(
                    gene_id=f"gene_w{i}_{random.randint(1000, 9999)}",
                    gene_type=GeneType.WEIGHT,
                    value=random.uniform(0.0, 1.0),
                    metadata={"index": i}
                ))

        return genes

    async def evaluate_fitness(
        self,
        individual: Individual,
        domain: str
    ) -> float:
        """
        적합도 평가.

        Args:
            individual: 평가할 개체
            domain: 도메인

        Returns:
            적합도 점수 (0.0-1.0)
        """
        # 도메인별 평가 로직
        if domain == "hunt_prompt":
            fitness = await self._evaluate_prompt_fitness(individual)
        elif domain == "quality_threshold":
            fitness = await self._evaluate_threshold_fitness(individual)
        elif domain == "strategy_weights":
            fitness = await self._evaluate_strategy_fitness(individual)
        else:
            # 기본: LLM 평가
            fitness = await self._evaluate_with_llm(individual, domain)

        individual.fitness = fitness
        return fitness

    async def _evaluate_prompt_fitness(self, individual: Individual) -> float:
        """프롬프트 적합도 평가"""
        # 과거 실험 결과에서 유사한 설정의 성과 조회
        try:
            # 유전자에서 설정 추출
            config = {g.metadata.get("component"): g.value for g in individual.genes}

            # 유사 실험 결과 조회
            rows = self.conn.execute("""
                SELECT AVG(CAST(
                    json_extract(result, '$.quality_score') AS REAL
                )) as avg_quality
                FROM experiment_queue
                WHERE status = 'completed'
                  AND variant_b LIKE ?
                LIMIT 20
            """, (f"%{config.get('tone', '')}%",)).fetchone()

            if rows and rows[0]:
                return min(rows[0] / 10.0, 1.0)

        except:
            pass

        # 폴백: 랜덤 적합도
        return random.uniform(0.3, 0.7)

    async def _evaluate_threshold_fitness(self, individual: Individual) -> float:
        """임계값 적합도 평가"""
        try:
            thresholds = {g.metadata.get("component"): g.value for g in individual.genes}

            min_words = thresholds.get("min_words", 200)
            min_score = thresholds.get("min_quality_score", 0.7)

            # 해당 임계값으로 통과한 콘텐츠의 실제 성과 조회
            rows = self.conn.execute("""
                SELECT AVG(quality_score) as avg,
                       COUNT(*) as cnt
                FROM hunt_log
                WHERE LENGTH(content) >= ? * 5
                  AND quality_score >= ?
            """, (min_words, min_score * 10)).fetchone()

            if rows and rows[1] > 0:
                # 성과 + 통과율 균형
                performance = (rows[0] or 5) / 10.0
                pass_rate = min(rows[1] / 100.0, 1.0)
                return performance * 0.7 + pass_rate * 0.3

        except:
            pass

        return random.uniform(0.3, 0.7)

    async def _evaluate_strategy_fitness(self, individual: Individual) -> float:
        """전략 가중치 적합도 평가"""
        try:
            weights = {g.metadata.get("strategy"): g.value for g in individual.genes}

            total_fitness = 0
            count = 0

            for strategy, weight in weights.items():
                # 해당 전략의 실제 성과 조회
                row = self.conn.execute("""
                    SELECT AVG(quality_score), COUNT(*)
                    FROM hunt_log
                    WHERE strategy = ?
                """, (strategy,)).fetchone()

                if row and row[1] > 0:
                    # 가중치와 실제 성과의 상관관계
                    actual_performance = (row[0] or 5) / 10.0
                    # 높은 가중치가 높은 성과 전략과 매칭되면 좋음
                    correlation = 1.0 - abs(weight - actual_performance)
                    total_fitness += correlation
                    count += 1

            if count > 0:
                return total_fitness / count

        except:
            pass

        return random.uniform(0.3, 0.7)

    async def _evaluate_with_llm(self, individual: Individual, domain: str) -> float:
        """LLM 기반 적합도 평가"""
        if not self.llm:
            return random.uniform(0.3, 0.7)

        genes_desc = [
            f"{g.gene_type.value}: {g.value} ({g.metadata})"
            for g in individual.genes
        ]

        prompt = f"""Evaluate the fitness of this configuration for {domain}:

Genes:
{chr(10).join(genes_desc)}

Rate the fitness from 0.0 to 1.0 based on:
- Coherence of values
- Balance of parameters
- Expected effectiveness

Respond with only a number between 0.0 and 1.0:"""

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=50
            )

            text = response.text if hasattr(response, 'text') else str(response)
            # 숫자 추출
            import re
            match = re.search(r'(\d+\.?\d*)', text)
            if match:
                return min(max(float(match.group(1)), 0.0), 1.0)

        except:
            pass

        return random.uniform(0.3, 0.7)

    def select_parents(self, population: Population) -> List[Tuple[Individual, Individual]]:
        """
        부모 선택 (토너먼트 선택).

        Args:
            population: 개체군

        Returns:
            부모 쌍 리스트
        """
        parents = []
        num_pairs = (self.POPULATION_SIZE - self.ELITE_COUNT) // 2

        for _ in range(num_pairs):
            # 토너먼트 선택
            parent1 = self._tournament_select(population.individuals)
            parent2 = self._tournament_select(population.individuals)

            # 같은 개체 피하기
            attempts = 0
            while parent2.individual_id == parent1.individual_id and attempts < 5:
                parent2 = self._tournament_select(population.individuals)
                attempts += 1

            parents.append((parent1, parent2))

        return parents

    def _tournament_select(self, individuals: List[Individual], k: int = 3) -> Individual:
        """토너먼트 선택"""
        tournament = random.sample(individuals, min(k, len(individuals)))
        return max(tournament, key=lambda x: x.fitness)

    def crossover(self, parent1: Individual, parent2: Individual) -> Tuple[Individual, Individual]:
        """
        교차 연산.

        Args:
            parent1, parent2: 부모 개체

        Returns:
            자식 개체 2개
        """
        if random.random() > self.CROSSOVER_RATE:
            # 교차 안 함 - 부모 복사
            return self._clone_individual(parent1), self._clone_individual(parent2)

        # 단일점 교차
        min_len = min(len(parent1.genes), len(parent2.genes))
        if min_len < 2:
            return self._clone_individual(parent1), self._clone_individual(parent2)

        crossover_point = random.randint(1, min_len - 1)

        child1_genes = parent1.genes[:crossover_point] + parent2.genes[crossover_point:]
        child2_genes = parent2.genes[:crossover_point] + parent1.genes[crossover_point:]

        child1 = Individual(
            individual_id=f"child_{random.randint(10000, 99999)}",
            generation=parent1.generation + 1,
            genes=[self._clone_gene(g) for g in child1_genes],
            parent_ids=[parent1.individual_id, parent2.individual_id],
            created_at=datetime.utcnow().isoformat()
        )

        child2 = Individual(
            individual_id=f"child_{random.randint(10000, 99999)}",
            generation=parent1.generation + 1,
            genes=[self._clone_gene(g) for g in child2_genes],
            parent_ids=[parent1.individual_id, parent2.individual_id],
            created_at=datetime.utcnow().isoformat()
        )

        return child1, child2

    def mutate(self, individual: Individual) -> Individual:
        """
        변이 연산.

        Args:
            individual: 변이 대상 개체

        Returns:
            변이된 개체
        """
        for gene in individual.genes:
            if random.random() < self.MUTATION_RATE:
                gene.value = self._mutate_value(gene)
                gene.gene_id = f"mut_{gene.gene_id}"

        return individual

    def _mutate_value(self, gene: Gene) -> Any:
        """유전자 값 변이"""
        if gene.gene_type == GeneType.WEIGHT:
            # 가중치: 가우시안 노이즈
            new_val = gene.value + random.gauss(0, 0.1)
            return max(0.0, min(1.0, new_val))

        elif gene.gene_type == GeneType.THRESHOLD:
            # 임계값: 가우시안 노이즈
            if isinstance(gene.value, int):
                new_val = gene.value + random.randint(-20, 20)
                return max(0, new_val)
            else:
                new_val = gene.value + random.gauss(0, 0.05)
                return max(0.0, min(1.0, new_val))

        elif gene.gene_type == GeneType.PROMPT:
            # 프롬프트: 선택지 중 랜덤
            options = gene.metadata.get("options", ["formal", "casual", "technical", "friendly"])
            return random.choice(options)

        elif gene.gene_type == GeneType.STRATEGY:
            # 전략: JSON 수정
            if isinstance(gene.value, dict):
                key = random.choice(list(gene.value.keys())) if gene.value else None
                if key:
                    gene.value[key] = random.uniform(0, 1)
            return gene.value

        return gene.value

    def _clone_individual(self, individual: Individual) -> Individual:
        """개체 복제"""
        return Individual(
            individual_id=f"clone_{individual.individual_id}_{random.randint(1000, 9999)}",
            generation=individual.generation + 1,
            genes=[self._clone_gene(g) for g in individual.genes],
            fitness=0.0,
            parent_ids=[individual.individual_id],
            created_at=datetime.utcnow().isoformat()
        )

    def _clone_gene(self, gene: Gene) -> Gene:
        """유전자 복제"""
        return Gene(
            gene_id=f"clone_{gene.gene_id}",
            gene_type=gene.gene_type,
            value=gene.value if not isinstance(gene.value, (list, dict)) else json.loads(json.dumps(gene.value)),
            metadata=dict(gene.metadata)
        )

    async def evolve_generation(self, population: Population) -> Population:
        """
        한 세대 진화.

        Args:
            population: 현재 개체군

        Returns:
            다음 세대 개체군
        """
        # 1. 적합도 평가
        for ind in population.individuals:
            if ind.fitness == 0.0:
                await self.evaluate_fitness(ind, population.domain)

        # 2. 정렬 (적합도 내림차순)
        population.individuals.sort(key=lambda x: x.fitness, reverse=True)

        # 3. 엘리트 보존
        new_individuals = [
            self._clone_individual(ind)
            for ind in population.individuals[:self.ELITE_COUNT]
        ]

        # 4. 부모 선택 + 교차 + 변이
        parents = self.select_parents(population)

        for parent1, parent2 in parents:
            child1, child2 = self.crossover(parent1, parent2)
            child1 = self.mutate(child1)
            child2 = self.mutate(child2)
            new_individuals.extend([child1, child2])

        # 5. 새 개체군 생성
        new_population = Population(
            population_id=population.population_id,
            domain=population.domain,
            generation=population.generation + 1,
            individuals=new_individuals[:self.POPULATION_SIZE]
        )

        # 6. 통계 업데이트
        fitnesses = [ind.fitness for ind in new_population.individuals if ind.fitness > 0]
        if fitnesses:
            new_population.best_fitness = max(fitnesses)
            new_population.avg_fitness = sum(fitnesses) / len(fitnesses)

        # 7. DB 저장
        self._save_population(new_population)

        logger.info("Generation %d: best=%.3f, avg=%.3f",
                    new_population.generation,
                    new_population.best_fitness,
                    new_population.avg_fitness)

        return new_population

    async def run_evolution(
        self,
        domain: str,
        generations: int = 10,
        seed_genes: List[Dict] = None
    ) -> Dict:
        """
        진화 실행.

        Args:
            domain: 진화 대상 도메인
            generations: 세대 수
            seed_genes: 시드 유전자

        Returns:
            진화 결과
        """
        result = {
            "domain": domain,
            "generations_run": 0,
            "initial_best": 0.0,
            "final_best": 0.0,
            "improvement": 0.0,
            "best_individual": None
        }

        # 초기 개체군
        population = await self.initialize_population(domain, seed_genes)

        # 초기 적합도 평가
        for ind in population.individuals:
            await self.evaluate_fitness(ind, domain)

        population.individuals.sort(key=lambda x: x.fitness, reverse=True)
        result["initial_best"] = population.individuals[0].fitness if population.individuals else 0

        # 세대 진화
        for gen in range(generations):
            population = await self.evolve_generation(population)
            result["generations_run"] = gen + 1

            # 조기 종료 (수렴)
            if population.best_fitness >= 0.95:
                logger.info("Early convergence at generation %d", gen + 1)
                break

        # 최종 결과
        if population.individuals:
            best = max(population.individuals, key=lambda x: x.fitness)
            result["final_best"] = best.fitness
            result["best_individual"] = {
                "id": best.individual_id,
                "fitness": best.fitness,
                "genes": [
                    {"type": g.gene_type.value, "value": g.value, "metadata": g.metadata}
                    for g in best.genes
                ]
            }

        result["improvement"] = result["final_best"] - result["initial_best"]

        return result

    def _save_population(self, population: Population):
        """개체군 DB 저장"""
        try:
            # 개체군 메타
            self.conn.execute("""
                INSERT OR REPLACE INTO evo_populations
                (population_id, domain, generation, best_fitness, avg_fitness, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                population.population_id,
                population.domain,
                population.generation,
                population.best_fitness,
                population.avg_fitness,
                datetime.utcnow().isoformat()
            ))

            # 개체들
            for ind in population.individuals:
                self.conn.execute("""
                    INSERT OR REPLACE INTO evo_individuals
                    (individual_id, population_id, generation, genes, fitness,
                     parent_ids, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    ind.individual_id,
                    population.population_id,
                    ind.generation,
                    json.dumps([
                        {"type": g.gene_type.value, "value": g.value, "metadata": g.metadata}
                        for g in ind.genes
                    ]),
                    ind.fitness,
                    json.dumps(ind.parent_ids),
                    ind.created_at
                ))

            self.conn.commit()

        except Exception as e:
            logger.error("Failed to save population: %s", e)

    def get_best_individual(self, domain: str) -> Optional[Dict]:
        """도메인의 최고 적합도 개체 반환"""
        try:
            row = self.conn.execute("""
                SELECT individual_id, genes, fitness
                FROM evo_individuals
                WHERE population_id LIKE ?
                ORDER BY fitness DESC
                LIMIT 1
            """, (f"pop_{domain}%",)).fetchone()

            if row:
                return {
                    "individual_id": row[0],
                    "genes": json.loads(row[1]),
                    "fitness": row[2]
                }

        except:
            pass

        return None

    def get_evolution_history(self, domain: str) -> List[Dict]:
        """도메인의 진화 이력"""
        try:
            rows = self.conn.execute("""
                SELECT generation, best_fitness, avg_fitness, updated_at
                FROM evo_populations
                WHERE domain = ?
                ORDER BY generation DESC
                LIMIT 50
            """, (domain,)).fetchall()

            return [
                {
                    "generation": r[0],
                    "best_fitness": r[1],
                    "avg_fitness": r[2],
                    "updated_at": r[3]
                }
                for r in rows
            ]

        except:
            return []
