from .skill_impl import HypothesisGenerationSkill

def before_run_hook(query, language, field, mode, **kwargs):
    print(f"[HOOK] Before run: {query}, {language}, {field}, {mode}")

def after_run_hook(result):
    print(f"[HOOK] After run: {result}")

skill = HypothesisGenerationSkill()
skill.register_hook('before_run', before_run_hook)
skill.register_hook('after_run', after_run_hook)

run = skill.run
