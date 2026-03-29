import sys
from pathlib import Path
import logging

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.deep_research import DeepResearchAgent
from config.settings import settings

# Setup logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def mock_notify(msg):
    print(f"\n[BOT] {msg}\n")

def main():
    query = "5-溴-N-(2-羟基苯基)噻吩-2-甲酰胺与B(9,12)-二碘-邻-碳硼烷偶联得到B(9,12)-（N-(2-羟基苯基)噻吩-2-甲酰胺)-邻碳硼烷，有什么合成路径可以实现？"
    
    print("-" * 50)
    print(f"Testing DeepResearchAgent with query:\n{query}")
    print("-" * 50)
    
    agent = DeepResearchAgent(notify_callback=mock_notify)
    
    # Run the agent
    # NOTE: This will attempt to connect to Edge on port 9222.
    # If not running, it might fail or fallback (depending on implementation details, 
    # but we force use_real_browser=True in run()).
    try:
        report, filepath = agent.run(query)
        
        print("-" * 50)
        print("Report Generated:")
        print("-" * 50)
        print(report[:1000] + "...\n(truncated)")
        print("-" * 50)
        print(f"Report saved to: {filepath}")
        
    except Exception as e:
        print(f"Test failed with error: {e}")

if __name__ == "__main__":
    main()
