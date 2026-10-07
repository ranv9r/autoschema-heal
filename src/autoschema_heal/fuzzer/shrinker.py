"""
Hierarchical Delta-Debugging Counterexample Minimizer (CexShrinker).

Given a mutated payload that triggers an invariant violation or execution panic,
this module shrinks the payload to its minimal reproducible counterexample
by iteratively pruning redundant keys and simplifying scalar values.
"""

from __future__ import annotations
import copy
from typing import Any, Callable, Dict, List, Optional, Tuple


class CounterexampleShrinker:
    """
    Minimizes failing counterexample payloads using structural delta-debugging.
    """

    def __init__(
        self,
        predicate: Optional[Callable[[Any], Tuple[bool, Optional[str]]]] = None,
        oracle_predicate: Optional[Callable[[Any], Tuple[bool, Optional[str]]]] = None,
    ) -> None:
        """
        predicate: function(payload) -> (passed, error_msg).
        Returns False when invariant violation or panic occurs.
        """
        self.predicate = predicate or oracle_predicate
        if self.predicate is None:
            raise ValueError("Must provide a validation predicate function.")

    def shrink(self, failing_payload: Any, max_passes: int = 4) -> Tuple[Any, Optional[str]]:
        """
        Systematically shrinks failing_payload while ensuring predicate(payload)[0] == False.
        Returns (minimal_payload, final_error_message).
        """
        curr = copy.deepcopy(failing_payload)
        initial_passed, initial_err = self.predicate(curr)
        if initial_passed:
            # Not failing to begin with
            return curr, None

        last_err = initial_err

        # Pass 1: Prune dictionary keys at top level and nested levels
        for _ in range(max_passes):
            changed = False
            if isinstance(curr, dict):
                keys = list(curr.keys())
                for k in keys:
                    candidate = copy.deepcopy(curr)
                    del candidate[k]
                    # Verify if removal still triggers the failure
                    try:
                        passed, err = self.predicate(candidate)
                        if not passed:
                            curr = candidate
                            last_err = err
                            changed = True
                    except Exception:
                        pass
            if not changed:
                break

        # Pass 2: Simplify string values (shorten to minimal trigger)
        if isinstance(curr, dict):
            for k, v in list(curr.items()):
                if isinstance(v, str) and len(v) > 5:
                    for test_val in [v[:2], "x", ""]:
                        candidate = copy.deepcopy(curr)
                        candidate[k] = test_val
                        passed, err = self.predicate(candidate)
                        if not passed:
                            curr = candidate
                            last_err = err
                            break

        return curr, last_err
