from .skill_impl import DeepResearchSkill
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
skill = DeepResearchSkill()

class SkillRequest(BaseModel):
    query: str
    language: str = 'zh'
    field: str = 'chemistry'
    mode: str = 'api'
    extra: dict = None

@app.post("/run")
def run_skill(req: SkillRequest):
    result = skill.run(
        query=req.query,
        language=req.language,
        field=req.field,
        mode=req.mode,
        **(req.extra or {})
    )
    return result
