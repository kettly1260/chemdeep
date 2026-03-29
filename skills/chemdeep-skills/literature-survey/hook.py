from .skill_impl import LiteratureSurveySkill

# 示例：注册hook实现流程扩展
def before_run_hook(query, language, field, mode, **kwargs):
    print(f"[HOOK] Before run: {query}, {language}, {field}, {mode}")

def after_run_hook(result):
    print(f"[HOOK] After run: {result}")

skill = LiteratureSurveySkill()
skill.register_hook('before_run', before_run_hook)
skill.register_hook('after_run', after_run_hook)

# 供外部调用
run = skill.run
