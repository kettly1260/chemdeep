from .._common.interface import SkillInterface
from .mcp_pipeline import ChemDeepPipeline

class LiteratureSurveySkill(SkillInterface):
    def __init__(self):
        super().__init__(name='literature-survey')
        self.pipeline = ChemDeepPipeline()

    def _run(self, query, language, field, mode, **kwargs):
        # 实际调用chemdeep mcp工具链，完成全流程
        result = self.pipeline.run_full_pipeline(
            query=query,
            language=language,
            field=field,
            min_year=kwargs.get('min_year'),
            max_results=kwargs.get('max_results', 20),
            min_score=kwargs.get('min_score', 5)
        )
        return {
            'skill': self.name,
            'query': query,
            'language': language,
            'field': field,
            'mode': mode,
            'result': result
        }
