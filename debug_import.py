import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
try:
    from core.services.research.core_types import Evidence, Hypothesis, HypothesisStatus
    print("Imported core_types")
    from core.services.research.conflict_adjudicator import adjudicate_falsification
    print("Imported conflict_adjudicator")
    from core.services.research.data_normalizer import normalize_single_evidence
    print("Imported data_normalizer")
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
