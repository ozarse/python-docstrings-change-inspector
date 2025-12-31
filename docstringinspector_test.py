import os
import shutil
import subprocess
import time
from docstringinspector import DocstringInspector

# Configuration
REPO_DIR = "test_repo"
FILE_NAME = "math_utils.py"
FILE_PATH = os.path.join(REPO_DIR, FILE_NAME)

def run_cmd(cmd, cwd=REPO_DIR):
    """Helper to run shell commands silently."""
    subprocess.run(cmd, cwd=cwd, shell=True, check=True, stdout=subprocess.DEVNULL)

def write_file(content):
    """Helper to overwrite the python file."""
    with open(FILE_PATH, "w") as f:
        f.write(content)

def setup_repo():
    """Creates a fresh git repo with a python file."""
    if os.path.exists(REPO_DIR):
        shutil.rmtree(REPO_DIR)
    os.makedirs(REPO_DIR)
    
    print(f"1. Initializing Git repo in '{REPO_DIR}'...")
    run_cmd("git init")
    run_cmd("git config user.email 'test@example.com'")
    run_cmd("git config user.name 'Test User'")

    # --- Commit 1: Initial Creation ---
    content_v1 = """
def calculate(a, b):
    \"\"\"
    Initial docstring.
    \"\"\"
    return a + b
"""
    write_file(content_v1)
    run_cmd(f"git add {FILE_NAME}")
    run_cmd("git commit -m 'Initial commit'")
    time.sleep(1) # Sleep ensures git timestamps differ for sorting

    # --- Commit 2: Change Signature (Add type hints) ---
    content_v2 = """
def calculate(a: int, b: int) -> int:
    \"\"\"
    Initial docstring.
    \"\"\"
    return a + b
"""
    write_file(content_v2)
    run_cmd(f"git add {FILE_NAME}")
    run_cmd("git commit -m 'Update signature with type hints'")
    time.sleep(1)

    # --- Commit 3: Change Docstring ---
    content_v3 = """
def calculate(a: int, b: int) -> int:
    \"\"\"
    Calculates the sum of two integers.
    Returns the result.
    \"\"\"
    return a + b
"""
    write_file(content_v3)
    run_cmd(f"git add {FILE_NAME}")
    run_cmd("git commit -m 'Update docstring to be more descriptive'")
    time.sleep(1)

    # --- Commit 4: Change Body (Logic change) ---
    content_v4 = """
def calculate(a: int, b: int) -> int:
    \"\"\"
    Calculates the sum of two integers.
    Returns the result.
    \"\"\"
    result = a + b
    return result
"""
    write_file(content_v4)
    run_cmd(f"git add {FILE_NAME}")
    run_cmd("git commit -m 'Refactor body to use variable'")

def run_test():
    setup_repo()
    
    print("\n2. Analyzing 'calculate' function...")
    inspector = DocstringInspector(FILE_PATH)
    target_func = "calculate"

    # --- Test Static Analysis ---
    print(f"\n[Analysis] Signature Lines: {inspector.get_signature_lines(target_func)}")
    print(f"[Analysis] Docstring Lines: {inspector.get_docstring_lines(target_func)}")
    print(f"[Analysis] Body Lines:      {inspector.get_implementation_without_docstring_lines(target_func)}")

    # --- Test Git History ---
    print("\n" + "="*50)
    print("TESTING GIT HISTORY RETRIEVAL")
    print("="*50)

    print("\n--- History of Signature (Should show type hint addition) ---")
    print(inspector.get_git_history_signature(target_func))

    print("\n--- History of Docstring (Should show text update) ---")
    print(inspector.get_git_history_docstring(target_func))

    print("\n--- History of Body (Should show refactor to 'result = ...') ---")
    print(inspector.get_git_history_body(target_func))

    # Cleanup
    # shutil.rmtree(REPO_DIR) # Uncomment to auto-delete the test folder

if __name__ == "__main__":
    run_test()
