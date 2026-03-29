"""
化学领域论文评分器
基于元数据快速评分，支持期刊影响因子、机构权重、关键词匹配等维度
"""

import logging
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger("paper_scorer")


class ChemistryPaperScorer:
    """化学领域论文评分器（无AI调用，快速评分）"""

    def __init__(self):
        # 高影响力期刊列表（化学领域）
        self.top_journals = {
            # 综合性顶刊
            "nature": 10.0,
            "science": 10.0,
            "cell": 9.5,
            # 化学综合
            "journal of the american chemical society": 9.5,
            "jacs": 9.5,
            "angewandte chemie": 9.5,
            "angew. chem. int. ed.": 9.5,
            "chemical reviews": 9.5,
            "chemical society reviews": 9.5,
            "accounts of chemical research": 9.0,
            "acs central science": 9.0,
            "chem": 9.0,
            "nature chemistry": 9.5,
            # 材料化学
            "advanced materials": 9.5,
            "adv. mater.": 9.5,
            "advanced functional materials": 9.0,
            "adv. funct. mater.": 9.0,
            "acs nano": 9.0,
            "nano letters": 9.0,
            "nano today": 9.0,
            "materials science and engineering r": 9.0,
            # 分析化学
            "analytical chemistry": 8.5,
            "anal. chem.": 8.5,
            "biosensors and bioelectronics": 9.0,
            "sensors and actuators b": 8.5,
            "sens. actuators b": 8.5,
            "acs sensors": 8.5,
            "trac-trends in analytical chemistry": 9.0,
            # 光谱/荧光相关
            "journal of luminescence": 7.5,
            "photodiagnosis and photodynamic therapy": 6.5,
            "journal of photochemistry and photobiology": 7.0,
            # 有机/无机化学
            "organic letters": 8.5,
            "org. lett.": 8.5,
            "inorganic chemistry": 8.0,
            "inorg. chem.": 8.0,
            "dalton transactions": 7.5,
            "journal of organic chemistry": 7.5,
        }

        # 顶级机构列表
        self.top_institutions = [
            "mit",
            "stanford",
            "harvard",
            "berkeley",
            "caltech",
            "oxford",
            "cambridge",
            "eth zurich",
            "max planck",
            "tsinghua",
            "peking",
            "nanjing",
            "fudan",
            "zhejiang",
            "ustc",
            "xiamen",
            "nankai",
            "wuhan",
            "sichuan",
            "cas",
            "chinese academy",
            "cnrs",
            "nipa",
            "ibm",
            "google",
            "microsoft",
            "huawei",
        ]

        # 关键词权重（荧光探针/传感器相关）
        self.keyword_weights = {
            # 高权重 - 核心领域
            "fluorescent probe": 3.0,
            "fluorescence sensor": 3.0,
            "chemosensor": 3.0,
            "fluorogenic": 3.0,
            "detection limit": 2.5,
            "lod": 2.5,
            "selectivity": 2.5,
            "photostability": 2.5,
            "photobleaching": 2.5,
            # 中权重 - 相关技术
            "aggregation-induced emission": 2.0,
            "aie": 2.0,
            "intramolecular charge transfer": 2.0,
            "ict": 2.0,
            "photoinduced electron transfer": 2.0,
            "pet": 2.0,
            "fluorescence resonance energy transfer": 2.0,
            "fret": 2.0,
            "turn-on": 2.0,
            "turn-off": 2.0,
            "ratiometric": 2.0,
            "near-infrared": 2.0,
            "nir": 2.0,
            "quantum yield": 2.0,
            "stokes shift": 2.0,
            # 低权重 - 通用术语
            "fluorescence": 1.0,
            "luminescence": 1.0,
            "sensor": 1.0,
            "detection": 1.0,
            "probe": 1.0,
            "metal ion": 1.0,
            "anion": 1.0,
            "biomarker": 1.0,
            "bioimaging": 1.5,
            "cell imaging": 1.5,
            # 特定离子
            "fe3+": 2.0,
            "ferric": 2.0,
            "iron": 1.5,
            "cu2+": 2.0,
            "copper": 1.5,
            "zn2+": 2.0,
            "zinc": 1.5,
            "hg2+": 2.0,
            "mercury": 1.5,
            "cd2+": 2.0,
            "cadmium": 1.5,
            "al3+": 2.0,
            "aluminum": 1.5,
        }

        # 方法学关键词
        self.methodology_keywords = [
            "novel",
            "first",
            "new",
            "design",
            "synthesis",
            "mechanism",
            "application",
            "improved",
            "enhanced",
            "sensitive",
            "selective",
            "rapid",
            "simple",
        ]

    def score_paper(self, paper: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算论文分数 (0-10)

        评分维度:
        1. 期刊影响力 (0-3分)
        2. 关键词匹配度 (0-3分)
        3. 作者机构权重 (0-2分)
        4. 摘要质量指标 (0-2分)

        Returns:
            Dict: {score: float, level: str, breakdown: dict}
        """
        score = 0.0
        breakdown = {}

        title = (paper.get("title") or "").lower()
        abstract = (paper.get("abstract") or "").lower()
        journal = (paper.get("source") or paper.get("journal") or "").lower()
        authors = paper.get("authors") or ""
        year = paper.get("year")

        # 确保 year 是整数或 None
        if year is not None:
            try:
                year = int(str(year)[:4])  # 处理 "2023" 或 "2023-01" 等格式
            except (ValueError, TypeError):
                year = None

        # 合并文本用于关键词匹配
        text = title + " " + abstract

        # 1. 期刊影响力 (0-3分)
        journal_score = 0.0
        matched_journal = None
        for j, weight in self.top_journals.items():
            if j in journal:
                journal_score = min(3.0, weight / 3.0)
                matched_journal = j
                break
        score += journal_score
        breakdown["journal_score"] = journal_score
        breakdown["matched_journal"] = matched_journal

        # 2. 关键词匹配度 (0-3分)
        keyword_score = 0.0
        matched_keywords = []
        for kw, weight in self.keyword_weights.items():
            if kw in text:
                keyword_score += weight
                matched_keywords.append(kw)
        keyword_score = min(3.0, keyword_score / 3.0)
        score += keyword_score
        breakdown["keyword_score"] = keyword_score
        breakdown["matched_keywords"] = matched_keywords[:5]

        # 3. 作者机构权重 (0-2分)
        institution_score = 0.0
        matched_institutions = []
        if authors:
            authors_lower = authors.lower()
            for inst in self.top_institutions:
                if inst in authors_lower:
                    institution_score += 0.5
                    matched_institutions.append(inst)
            institution_score = min(2.0, institution_score)
        score += institution_score
        breakdown["institution_score"] = institution_score
        breakdown["matched_institutions"] = matched_institutions

        # 4. 摘要质量指标 (0-2分)
        abstract_quality = 0.0

        # 摘要长度适中
        abstract_len = len(abstract)
        if 500 <= abstract_len <= 3000:
            abstract_quality += 0.5

        # 包含量化结果
        quantitative_indicators = ["%", "fold", "ppm", "ppb", "nm", "μm", "improvement"]
        if any(ind in text for ind in quantitative_indicators):
            abstract_quality += 0.5

        # 包含方法学关键词
        method_count = sum(1 for kw in self.methodology_keywords if kw in text)
        if method_count >= 2:
            abstract_quality += 0.5

        # 包含实验验证
        experiment_indicators = [
            "characterized",
            "measured",
            "observed",
            "detected",
            "tested",
        ]
        if any(ind in text for ind in experiment_indicators):
            abstract_quality += 0.5

        score += abstract_quality
        breakdown["abstract_quality"] = abstract_quality

        # 5. 时效性加分 (0-0.5分)
        recency_bonus = 0.0
        if year:
            try:
                current_year = datetime.now().year
                year_int = int(year) if isinstance(year, (str, int, float)) else None
                if year_int is not None:
                    if current_year - year_int <= 1:
                        recency_bonus = 0.5
                    elif current_year - year_int <= 3:
                        recency_bonus = 0.3
            except (ValueError, TypeError):
                pass
        score += recency_bonus
        breakdown["recency_bonus"] = recency_bonus

        # 最终分数
        final_score = min(10.0, round(score, 2))

        # 评级
        if final_score >= 8.0:
            level = "S"
        elif final_score >= 6.5:
            level = "A"
        elif final_score >= 5.0:
            level = "B"
        elif final_score >= 3.5:
            level = "C"
        else:
            level = "D"

        return {"score": final_score, "level": level, "breakdown": breakdown}

    def filter_by_year(
        self, papers: List[Dict], min_year: int = None, max_year: int = None
    ) -> List[Dict]:
        """
        按年份筛选论文

        Args:
            papers: 论文列表
            min_year: 最小年份（含）
            max_year: 最大年份（含）

        Returns:
            筛选后的论文列表
        """
        if min_year is None and max_year is None:
            return papers

        filtered = []
        current_year = datetime.now().year

        for paper in papers:
            year = paper.get("year")
            if year is None:
                # 无年份信息，保留
                filtered.append(paper)
                continue

            try:
                year_int = int(year) if isinstance(year, str) else year
            except (ValueError, TypeError):
                filtered.append(paper)
                continue

            if min_year and year_int < min_year:
                continue
            if max_year and year_int > max_year:
                continue

            filtered.append(paper)

        logger.info(
            f"年份筛选: {len(papers)} -> {len(filtered)} (min_year={min_year}, max_year={max_year})"
        )
        return filtered

    def score_and_filter(
        self,
        papers: List[Dict],
        min_score: float = 0.0,
        min_year: int = None,
        max_year: int = None,
        sort_by: str = "score",
    ) -> List[Dict]:
        """
        评分并筛选论文

        Args:
            papers: 论文列表
            min_score: 最低分数
            min_year: 最小年份
            max_year: 最大年份
            sort_by: 排序方式 ('score' 或 'year')

        Returns:
            评分并筛选后的论文列表
        """
        # 先按年份筛选
        papers = self.filter_by_year(papers, min_year, max_year)

        # 评分
        scored_papers = []
        for paper in papers:
            result = self.score_paper(paper)
            paper["score"] = result["score"]
            paper["level"] = result["level"]
            paper["score_breakdown"] = result["breakdown"]

            if result["score"] >= min_score:
                scored_papers.append(paper)

        # 排序
        if sort_by == "score":
            scored_papers.sort(key=lambda x: x.get("score", 0), reverse=True)
        elif sort_by == "year":
            scored_papers.sort(key=lambda x: int(x.get("year", 0) or 0), reverse=True)

        logger.info(
            f"评分筛选: {len(papers)} -> {len(scored_papers)} (min_score={min_score})"
        )
        return scored_papers

    def get_score_summary(self, papers: List[Dict]) -> str:
        """生成评分摘要报告"""
        if not papers:
            return "无论文数据"

        s_count = len([p for p in papers if p.get("score", 0) >= 8.0])
        a_count = len([p for p in papers if 6.5 <= p.get("score", 0) < 8.0])
        b_count = len([p for p in papers if 5.0 <= p.get("score", 0) < 6.5])
        c_count = len([p for p in papers if 3.5 <= p.get("score", 0) < 5.0])
        d_count = len([p for p in papers if p.get("score", 0) < 3.5])

        avg_score = sum(p.get("score", 0) for p in papers) / len(papers)

        lines = [
            "📊 论文评分摘要",
            "=" * 30,
            f"📄 总计: {len(papers)} 篇",
            f"📈 平均分: {avg_score:.2f}",
            "",
            "🏆 评级分布:",
            f"  S (≥8.0): {s_count} 篇 ({s_count / len(papers) * 100:.1f}%)",
            f"  A (6.5-8.0): {a_count} 篇 ({a_count / len(papers) * 100:.1f}%)",
            f"  B (5.0-6.5): {b_count} 篇 ({b_count / len(papers) * 100:.1f}%)",
            f"  C (3.5-5.0): {c_count} 篇 ({c_count / len(papers) * 100:.1f}%)",
            f"  D (<3.5): {d_count} 篇 ({d_count / len(papers) * 100:.1f}%)",
        ]

        return "\n".join(lines)


# 全局实例
paper_scorer = ChemistryPaperScorer()
