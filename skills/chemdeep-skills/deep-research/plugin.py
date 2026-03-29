from .skill_impl import DeepResearchSkill

def plugin_entry(query, language='zh', field='chemistry', **kwargs):
    skill = DeepResearchSkill()
    return skill.run(query=query, language=language, field=field, mode='plugin', **kwargs)
