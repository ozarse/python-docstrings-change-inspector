import ast
import subprocess
import os
import re
from datetime import datetime
from typing import Any, List, Tuple, Optional, Dict, Union

class CodeInspector:
    def __init__(self, file_path: str):
        self.file_path = file_path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found.")

        with open(file_path, "r", encoding="utf-8") as f:
            self.source_code = f.read()
            self.source_lines = self.source_code.splitlines()

        self.tree = ast.parse(self.source_code)

    def _find_nodes(self, name: str) -> List[Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]]:
        """
        Finds all nodes (definitions) matching the name.
        This captures the main definition and any @overload definitions.
        """
        matches = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == name:
                    matches.append(node)
        return matches

    def _get_node_range(self, node) -> Tuple[int, int]:
        """Returns the start and end line numbers (1-based) of a node including decorators."""
        start_line = node.lineno
        # If there are decorators, the definition starts at the first decorator
        if hasattr(node, 'decorator_list') and node.decorator_list:
            start_line = node.decorator_list[0].lineno

        # end_lineno is available in Python 3.8+
        end_line = getattr(node, 'end_lineno', node.lineno)
        return start_line, end_line

    def _get_docstring_node(self, node) -> Optional[ast.Expr]:
        """Returns the AST node for the docstring if it exists."""
        if not hasattr(node, 'body') or not node.body:
            return None

        # Check if first item in body is an expression containing a string
        first_node = node.body[0]
        if (isinstance(first_node, ast.Expr) and
            isinstance(first_node.value, (ast.Str, ast.Constant))):
            # In Py 3.8+ ast.Constant is used for strings
            if isinstance(first_node.value, ast.Constant) and isinstance(first_node.value.value, str):
                return first_node
            # Legacy check for older python versions
            elif isinstance(first_node.value, ast.Str):
                return first_node
        return None

    def _run_git_log_L(self, line_ranges: List[Tuple[int, int]], commits: int = 5) -> str:
        """
        Runs `git log -L` for the specific line ranges.
        """
        if not line_ranges:
            return "No lines found to analyze."

        output_log = []
        for start, end in line_ranges:
            if start > end: continue

            # git log -L <start>,<end>:<file>
            cmd = [
                "git", "log",
                "-L", f"{start},{end}:{self.file_path}",
                f"--max-count={commits}"
            ]

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(self.file_path))
                )
                if result.returncode != 0:
                    output_log.append(f"Error reading lines {start}-{end}: {result.stderr.strip()}")
                else:
                    output_log.append(f"--- History for lines {start}-{end} ---\n{result.stdout}")
            except Exception as e:
                output_log.append(f"Git execution failed: {str(e)}")

        return "\n".join(output_log)

    # ---------------------------------------------------------
    # 1) Find code lines for definition
    # ---------------------------------------------------------
    def get_definition_lines(self, name: str) -> List[Tuple[int, int]]:
        """Returns list of (start, end) tuples for all definitions (including overloads)."""
        nodes = self._find_nodes(name)
        return [self._get_node_range(n) for n in nodes]

    # ---------------------------------------------------------
    # 2) Find code lines for function signature (including overloads)
    # ---------------------------------------------------------
    def get_signature_lines(self, name: str) -> List[Tuple[int, int]]:
        """
        Returns line ranges for the signature.
        Includes full body of @overloads (since they are just signatures)
        and the header of the actual implementation (decorators + def line).
        """
        nodes = self._find_nodes(name)
        ranges = []

        # This makes a change as a test.
        for node in nodes:
            start, end = self._get_node_range(node)

            # check if this is an overload (usually empty body or just ...)
            is_overload = False
            if hasattr(node, 'decorator_list'):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == 'overload':
                        is_overload = True
                    elif isinstance(dec, ast.Attribute) and dec.attr == 'overload':
                        is_overload = True

            if is_overload:
                ranges.append((start, end))
            else:
                # It's the implementation. Signature ends before the first body statement.
                if node.body:
                    sig_end = max(start, node.body[0].lineno - 1)
                    if node.body[0].lineno == node.lineno:
                         sig_end = node.lineno
                    ranges.append((start, sig_end))
                else:
                    ranges.append((start, end))

        return ranges

    # ---------------------------------------------------------
    # 3) Find code lines for the docstring
    # ---------------------------------------------------------
    def get_docstring_lines(self, name: str) -> List[Tuple[int, int]]:
        """Returns line ranges of the docstring for the main implementation."""
        nodes = self._find_nodes(name)
        ranges = []

        for node in nodes:
            doc_node = self._get_docstring_node(node)
            if doc_node:
                ranges.append((doc_node.lineno, doc_node.end_lineno))

        return ranges

    # ---------------------------------------------------------
    # 4) Find code lines for everything BUT the docstring
    # ---------------------------------------------------------
    def get_implementation_without_docstring_lines(self, name: str) -> List[Tuple[int, int]]:
        """
        Returns line ranges for the function excluding the docstring.
        """
        nodes = self._find_nodes(name)
        ranges = []

        for node in nodes:
            start, end = self._get_node_range(node)
            doc_node = self._get_docstring_node(node)

            if doc_node:
                if doc_node.lineno > start:
                    ranges.append((start, doc_node.lineno - 1))
                if doc_node.end_lineno < end:
                    ranges.append((doc_node.end_lineno + 1, end))
            else:
                ranges.append((start, end))

        return ranges

    # ---------------------------------------------------------
    # Git Wrappers
    # ---------------------------------------------------------
    def get_git_history_signature(self, name: str) -> str:
        ranges = self.get_signature_lines(name)
        return self._run_git_log_L(ranges)

    def get_git_history_docstring(self, name: str) -> str:
        ranges = self.get_docstring_lines(name)
        return self._run_git_log_L(ranges)

    def get_git_history_body(self, name: str) -> str:
        nodes = self._find_nodes(name)
        ranges = []

        for node in nodes:
            # We ignore overloads here as they are pure signature
            is_overload = False
            if hasattr(node, 'decorator_list'):
                 for dec in node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == 'overload': is_overload = True
                    elif isinstance(dec, ast.Attribute) and dec.attr == 'overload': is_overload = True

            if is_overload or not node.body:
                continue

            doc_node = self._get_docstring_node(node)
            func_end = getattr(node, 'end_lineno', node.lineno)

            start_scan = -1
            if doc_node:
                start_scan = doc_node.end_lineno + 1
            else:
                start_scan = node.body[0].lineno

            if start_scan <= func_end:
                ranges.append((start_scan, func_end))

        return self._run_git_log_L(ranges)

    def parse_git_log_to_dict(self, log_output: str) -> Dict[str, Dict[str, Any]]:
        """Parses a raw git log string into a dictionary of dictionaries.
        Structure:
        {
            "commit_hash": {
                "author_name": str,
                "author_email": str,
                "date": str,
                "message": str,
                "diff": str
            },
            ...
        }
        """
        commits = {}
        current_hash = None
        current_data = {}

        commit_pattern = re.compile(r'^commit\s+([0-9a-f]{40})')
        author_pattern = re.compile(r'^Author:\s+(.+)\s+<(.+)>')
        date_pattern = re.compile(r'^Date:\s+(.+)')
        diff_start_pattern = re.compile(r'^diff\s--git')

        lines = log_output.splitlines()
        state = "HEADER"

        for line in lines:
            commit_match = commit_pattern.match(line)
            if commit_match:
                if current_hash and current_data:
                    current_data['message'] = "\n".join(current_data['message']).strip()
                    current_data['diff'] = "\n".join(current_data['diff'])
                    commits[current_hash] = current_data

                current_hash = commit_match.group(1)
                current_data = {
                    'author_name': None, 'author_email': None, 'date': None,
                    'message': [], 'diff': []
                }
                state = "HEADER"
                continue

            if current_hash is None: continue

            if state == "HEADER":
                author_match = author_pattern.match(line)
                if author_match:
                    current_data['author_name'] = author_match.group(1).strip()
                    current_data['author_email'] = author_match.group(2).strip()
                    continue

                date_match = date_pattern.match(line)
                if date_match:
                    current_data['date'] = date_match.group(1).strip()
                    state = "MESSAGE"
                    continue

            elif state == "MESSAGE":
                if diff_start_pattern.match(line):
                    state = "DIFF"
                    current_data['diff'].append(line)
                    continue
                current_data['message'].append(line)

            elif state == "DIFF":
                current_data['diff'].append(line)

        if current_hash and current_data:
            current_data['message'] = "\n".join(current_data['message']).strip()
            current_data['diff'] = "\n".join(current_data['diff'])
            commits[current_hash] = current_data

        return commits

    # ---------------------------------------------------------
    # NEW: Consistency Logic
    # ---------------------------------------------------------

    def _get_latest_commit_info(self, history_dict: Dict[str, Any]) -> Tuple[datetime, str]:
        """
        Extracts the datetime and hash of the latest commit from the parsed log dictionary.
        Returns (datetime.min, "") if history is empty.
        """
        if not history_dict:
            return datetime.min.replace(tzinfo=None), ""

        # history_dict preserves insertion order (Python 3.7+), and git log returns newest first.
        # So the first key is the latest commit.
        latest_hash = next(iter(history_dict))
        date_str = history_dict[latest_hash]['date']

        # Git default date format: "Fri Jan 11 20:23:51 2026 +0100"
        # We use %z to handle timezone info.
        try:
            dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %Y %z")
        except ValueError:
            # Fallback if format differs, though git default is fairly standard.
            # Using datetime.min ensures this component is treated as "very old"
            return datetime.min.replace(tzinfo=None), latest_hash

        return dt, latest_hash

    def check_function_consistency(self, name: str) -> List[str]:
        """
        Compares the latest Git commits for Signature, Docstring, and Body.
        Returns a list of warning notes if inconsistencies are found.
        """
        warnings = []

        # 1. Fetch raw logs
        raw_sig = self.get_git_history_signature(name)
        raw_doc = self.get_git_history_docstring(name)
        raw_body = self.get_git_history_body(name)

        # 2. Parse logs to dictionaries
        dict_sig = self.parse_git_log_to_dict(raw_sig)
        dict_doc = self.parse_git_log_to_dict(raw_doc)
        dict_body = self.parse_git_log_to_dict(raw_body)

        # 3. Get latest dates and hashes
        # Note: We rely on direct comparison of datetimes (which handles timezone awareness)
        date_sig, hash_sig = self._get_latest_commit_info(dict_sig)
        date_doc, hash_doc = self._get_latest_commit_info(dict_doc)
        date_body, hash_body = self._get_latest_commit_info(dict_body)

        # 4. Perform Checks

        # Condition A: If the body was updated, and the signature and docstring were not updated afterward
        # Logic: Body Date > Signature Date AND Body Date > Docstring Date
        if date_body > date_sig and date_body > date_doc:
            warnings.append(
                f"Check the docstring or function, as the body was updated. "
                f"(Body commit: {hash_sig})"
            )

        # Condition B: If the signature was updated, and the docstring was not updated afterward
        # Logic: Signature Date > Docstring Date
        if date_sig > date_doc:
            warnings.append(
                f"Check the docstring, as the signature was updated. "
                f"(Signature commit: {hash_sig})"
            )

        return warnings

def main():
    target_file = os.path.abspath(__file__) # Analyze this file itself
    target_func = "check_function_consistency"

    try:
        inspector = CodeInspector(target_file)

        print(f"--- Analyzing Consistency for '{target_func}' ---\n")

        notes = inspector.check_function_consistency(target_func)

        if notes:
            for note in notes:
                print(f"[!] {note}")
        else:
            print("[+] No inconsistencies found in commit history.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()