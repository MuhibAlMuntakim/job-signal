import sys
import os
sys.path.append(os.getcwd())
from jobsignal.ingestion.orchestrator import run_ingestion
from typing import List
from jobsignal.ingestion.schemas import IngestionSummary

print("Import successful")
# We won't actually call it since it hits APIs, but we check the inspect
import inspect
sig = inspect.signature(run_ingestion)
print(f"Signature: {sig}")

# Try to mock it just to check the return type handling
try:
    ret = run_ingestion(queries=[])
    print(f"Return type: {type(ret)}")
    print(f"Return length: {len(ret)}")
    a, b = ret
    print("Unpack successful")
except Exception as e:
    print(f"Error during call/unpack: {e}")
