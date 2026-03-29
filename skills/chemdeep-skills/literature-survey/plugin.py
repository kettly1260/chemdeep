from .skill_impl import LiteratureSurveySkill

# 插件式调用示例
def plugin_entry(query, language='zh', field='chemistry', **kwargs):
    skill = LiteratureSurveySkill()
    return skill.run(query=query, language=language, field=field, mode='plugin', **kwargs)
