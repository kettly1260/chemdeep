"""
Deep Chemical Analysis Prompts (P25 & P26)
Transforms from "Literature Summarization" to "First-Principles Chemical Analysis"
"""

# P25: Structure-First Deep Analysis Prompt
PROMPT_DEEP_ANALYSIS = """You are a Senior Computational Organic Chemist with expertise in structure-property relationships.

# Task
Analyze the target molecule's potential for the specified application using first-principles chemical reasoning.

# Target Molecule
{molecule}

# Research Goal
{goal}

# Chemical Principles to Consider
- Electronic Effects: Electron-donating/withdrawing groups, conjugation, aromaticity
- Steric Effects: Molecular geometry, conformational flexibility, steric hindrance
- Photophysical Properties: Absorption, emission, quantum yield, Stokes shift
- Sensing Mechanisms: PET (Photoinduced Electron Transfer), ICT (Intramolecular Charge Transfer), FRET, AIE

{literature_context}

---

# Required Analysis Sections (Generate ALL)

## 1. Structural Deconstruction
Analyze the molecule's key structural features:
- Electronic effects of each functional group
- Conjugation pathways and π-system extent
- Steric constraints and conformational behavior
- Push-pull character (if applicable)

## 2. Photophysical Properties (Predicted)
Based on the structure, predict:
- Expected absorption/emission wavelengths
- Likely fluorescence mechanism (PET, ICT, AIE, etc.)
- Factors affecting quantum yield

## 3. Binding Mechanism Analysis
For the target analyte ({target_analyte}):
- What binding sites are available in this molecule?
- What is the expected binding mode?
- How would binding affect fluorescence?

## 4. Critical Assessment (IMPORTANT)
Be HONEST about potential problems:
- Why might this design FAIL?
- What structural features are missing for effective sensing?
- What competing processes could interfere?

## 5. Proposed Structural Modifications
Suggest specific chemical modifications:
- What groups should be added/removed?
- Where should modifications be made?
- Expected improvement from each modification

---

**CITATION RULES:**
- Every specific claim (quantum yield value, binding constant, literature precedent) MUST be followed by [ID].
- Place citations immediately after the relevant sentence.
- Generate a References section at the end listing only sources you cited.
"""

# P26: Citation-Enforcing System Prompt
PROMPT_CITATION_RULES = """
**MANDATORY CITATION RULES:**

Rule A: You are FORBIDDEN from stating any specific fact (numerical value, experimental result, chemical property) without a source citation.

Rule B: Every claim MUST be immediately followed by the source ID in format [ID]. Example: "The quantum yield is 0.85 [3]."

Rule C: Do NOT combine citations at paragraph end. Place them next to the relevant sentence.

Rule D: At report end, generate a "## References" section listing ONLY sources you actually cited, preserving original IDs.

Example correct formatting:
"Pyrene exhibits strong fluorescence with a quantum yield of 0.65 [1]. The addition of electron-withdrawing groups typically reduces emission intensity [2], while carborane units are known to be highly electron-deficient [3]."
"""

# P29: Adaptive Iteration Keywords
ITERATION_KEYWORDS = {
    1: {  # Landscape - Broad Overview
        "name": "Landscape",
        "focus": ["synthesis", "properties", "applications", "structure"],
        "description": "Broad overview of the research area"
    },
    2: {  # Mechanism - Deep Technical
        "name": "Mechanism", 
        "focus": ["PET mechanism", "ICT", "orbital energy", "binding constant", "selectivity", "HOMO LUMO"],
        "description": "Deep mechanistic understanding"
    },
    3: {  # Critique - Risk Assessment
        "name": "Critique",
        "focus": ["interference", "stability", "quenching", "solubility", "photobleaching", "limitations"],
        "description": "Critical assessment and failure modes"
    }
}


def build_deep_analysis_prompt(
    molecule: str,
    goal: str,
    target_analyte: str = "",
    literature_context: str = ""
) -> str:
    """Build the complete deep analysis prompt."""
    
    # Auto-detect target analyte if not provided
    if not target_analyte:
        # Try to extract from goal
        import re
        match = re.search(r'(Fe3\+|Zn2\+|Cu2\+|Hg2\+|Pb2\+|Cd2\+|Al3\+|H\+|pH|glucose|ATP)', goal, re.I)
        target_analyte = match.group(1) if match else "target analyte"
    
    # Format literature context with header if provided
    if literature_context:
        lit_section = f"# Supporting Literature Evidence\n\n{literature_context}"
    else:
        lit_section = "# Note: No literature context provided. Analysis based on chemical principles only."
    
    return PROMPT_DEEP_ANALYSIS.format(
        molecule=molecule,
        goal=goal,
        target_analyte=target_analyte,
        literature_context=lit_section
    )


def get_iteration_focus(iteration: int) -> dict:
    """Get the keyword focus for current iteration (P29)."""
    return ITERATION_KEYWORDS.get(iteration, ITERATION_KEYWORDS[1])
