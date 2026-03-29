import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from core.services.research.core_types import Evidence
from core.services.research.data_normalizer import normalize_single_evidence

def test():
    print("Starting T5 debug")
    mock_response = '''```json
    {
        "concentration": {
            "value": 0.5,
            "unit": "mg/mL",
            "original": "500 ug/mL"
        }
    }
    ```'''
    
    # Patch where it is imported
    with patch('core.services.research.data_normalizer.simple_chat', return_value=mock_response) as mock_chat:
        ev = Evidence(paper_id="DOI_Unit", paper_title="Paper Unit")
        ev.key_variables = {"concentration": "500 ug/mL"}
        
        print("Calling normalize_single_evidence")
        normalize_single_evidence(ev)
        
        print(f"Normalized: {ev.normalized_values}")
        if ev.normalized_values.get("concentration") == 0.5:
             print("Assertion Passed")
        else:
             print("Assertion Failed")

try:
    test()
    print("T5 Logic Finished")
except Exception as e:
    import traceback
    traceback.print_exc()
