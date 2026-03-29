from .skill_impl import VerificationDesignSkill

def plugin_entry(query, language='zh', field='chemistry', **kwargs):
    skill = VerificationDesignSkill()
    return skill.run(query=query, language=language, field=field, mode='plugin', **kwargs)
