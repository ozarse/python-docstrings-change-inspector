import ast
import subprocess
import os
from typing import List, Tuple, Optional, Dict, Union

class DocstringInspector:
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

    def _run_git_log_L(self, line_ranges: List[Tuple[int, int]]) -> str:
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
                "--max-count=5" # Limit to last 5 commits to keep output readable
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
                    # The signature ends at the line before the first body statement starts
                    # Note: We take the max of start to ensure we don't go backwards
                    sig_end = max(start, node.body[0].lineno - 1)
                    
                    # Edge case: If the first line of body is on the same line as def (e.g. def x(): pass)
                    if node.body[0].lineno == node.lineno:
                         # For one-liners, the signature isn't distinct from body easily by line number.
                         # We treat the whole line as signature for safety in line-based git tools.
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
            # Skip overloads, usually they don't have docstrings we care about for implementation history
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
        If a docstring exists, it returns [start_of_def, start_of_doc-1] and [end_of_doc+1, end_of_def].
        """
        nodes = self._find_nodes(name)
        ranges = []
        
        for node in nodes:
            start, end = self._get_node_range(node)
            doc_node = self._get_docstring_node(node)
            
            if doc_node:
                # Range 1: Start of func to line before docstring
                if doc_node.lineno > start:
                    ranges.append((start, doc_node.lineno - 1))
                
                # Range 2: Line after docstring to end of func
                if doc_node.end_lineno < end:
                    ranges.append((doc_node.end_lineno + 1, end))
            else:
                # No docstring, return whole range
                ranges.append((start, end))
                
        return ranges

    # ---------------------------------------------------------
    # 5) Git changes for signature
    # ---------------------------------------------------------
    def get_git_history_signature(self, name: str) -> str:
        ranges = self.get_signature_lines(name)
        return self._run_git_log_L(ranges)

    # ---------------------------------------------------------
    # 6) Git changes for docstring
    # ---------------------------------------------------------
    def get_git_history_docstring(self, name: str) -> str:
        ranges = self.get_docstring_lines(name)
        return self._run_git_log_L(ranges)

    # ---------------------------------------------------------
    # 7) Git changes for body (excluding signature and docstring)
    # ---------------------------------------------------------
    def get_git_history_body(self, name: str) -> str:
        """
        Gets history for the function body, excluding signature header and docstring.
        """
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
                # Body starts after docstring
                start_scan = doc_node.end_lineno + 1
            else:
                # Body starts at the first node
                start_scan = node.body[0].lineno
            
            if start_scan <= func_end:
                ranges.append((start_scan, func_end))

        return self._run_git_log_L(ranges)


# --- Example Usage ---
if __name__ == "__main__":
    # Create a dummy python file to test the script on itself or another file
    target_file = "code_inspector.py" 
    target_func = "get_signature_lines" # Analyzing one of the functions above

    try:
        inspector = DocstringInspector(target_file)
        
        print(f"--- Analyzing '{target_func}' in {target_file} ---\n")

        print(f"1. Definition Lines: {inspector.get_definition_lines(target_func)}")
        print(f"2. Signature Lines: {inspector.get_signature_lines(target_func)}")
        print(f"3. Docstring Lines: {inspector.get_docstring_lines(target_func)}")
        print(f"4. Impl (no docstring) Lines: {inspector.get_implementation_without_docstring_lines(target_func)}")
        
        # Note: Git commands will only work if this file is actually inside a git repo
        # print("\n5. Git Signature History:\n", inspector.get_git_history_signature(target_func))
        # print("\n6. Git Docstring History:\n", inspector.get_git_history_docstring(target_func))
        # print("\n7. Git Body History:\n", inspector.get_git_history_body(target_func))

    except Exception as e:
        print(f"Error: {e}")
