from .skill_impl import HypothesisGenerationSkill

def plugin_entry(query, language='zh', field='chemistry', **kwargs):
    skill = HypothesisGenerationSkill()
    return skill.run(query=query, language=language, field=field, mode='plugin', **kwargs)
